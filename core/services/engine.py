"""
core/services/engine.py  (M3.4 — relocated from iscs_workflow)

The run engine, now in pure core/: the capability-registry bridge (legacy-executor
adapters + registry/coverage) and ProcedureRunner (sequential flow executor). No UI
or OS-automation imports — pyautogui-using executors live in
adapters/driven/input/legacy_executors.py (resolved lazily), expected-state /
evidence / FrameSampler are pulled from core / perception lazily inside methods.

This is what makes a headless author->run->report cycle possible: importing this
module pulls NO tkinter. iscs_workflow re-exports ProcedureRunner / ExecContext /
the bridge as shims so dialogs, baru, plugins and tests are unchanged.

Note on `core_registry`: the dispatcher reads it from THIS module's namespace. Tests
that drive _execute_procedure / registry_step_coverage patch
`core.services.engine.core_registry`; the wf-level alias is what the (still-in-wf)
_dynamic_catalogue palette reads.
"""
from __future__ import annotations

import datetime
import logging
import time
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AutoClick")

from core.domain.flow import (
    ProcedureCategory, ProcedureStatus, ProcedureType,
    Procedure, ProcedureFlow,
)
from core.domain.results import ProcedureResult, ExecutionTrace


# ═════════════════════════════════════════════════════════════════════════════
#  CAPABILITY REGISTRY BRIDGE  (Phase 1 — additive; see ARCHITECTURE_DESIGN.md)
# ═════════════════════════════════════════════════════════════════════════════
# Single source of truth mapping each ProcedureType to the ProcedureRunner method
# that executes it. Used by BOTH the runtime dispatch in _execute_procedure and
# the legacy capability adapters registered below — so they can never drift.
_LEGACY_METHOD_MAP: Dict["ProcedureType", str] = {
    ProcedureType.TRIGGER_ALARM            : "_exec_trigger_alarm",
    ProcedureType.RESET_ALARM              : "_exec_reset_alarm",
    ProcedureType.NAVIGATE_HOME            : "_exec_navigate_home",
    ProcedureType.NAVIGATE_ALARM_LIST      : "_exec_navigate_alarm_list",
    ProcedureType.NAVIGATE_EVENT_LIST      : "_exec_navigate_event_list",
    ProcedureType.NAVIGATE_EQUIP_PAGE      : "_exec_navigate_equip_page",
    ProcedureType.VERIFY_ALARM_PANEL       : "_exec_verify_alarm_panel",
    ProcedureType.VERIFY_NORMALIZE         : "_exec_verify_normalize",
    ProcedureType.VERIFY_ALARM_LIST        : "_exec_verify_alarm_list",
    ProcedureType.VERIFY_EVENT_LIST        : "_exec_verify_event_list",
    ProcedureType.VERIFY_EQUIP_PAGE        : "_exec_verify_equip_page",
    ProcedureType.DELAY                    : "_exec_delay",
    ProcedureType.SCREENSHOT               : "_exec_screenshot",
    ProcedureType.CLICK                    : "_exec_click",
    ProcedureType.RIGHT_CLICK              : "_exec_right_click",
    ProcedureType.HOTKEY                   : "_exec_hotkey",
    ProcedureType.TYPE_TEXT                : "_exec_type_text",
    ProcedureType.VERIFY_ALARM_PANEL_CUSTOM: "_exec_verify_alarm_panel_custom",
    ProcedureType.VERIFY_CUSTOM            : "_exec_verify_custom",
}


def _category_for(proc_type: "ProcedureType") -> str:
    """Classify a ProcedureType into a capability category."""
    v = proc_type.value
    if v.startswith("verify"):
        return "verification"
    if v in ("delay", "screenshot"):
        return "utility"
    return "action"


try:
    from iscs_core import (
        CapabilityMeta, CapabilityRegistry, StepResult, StepStatus,
        registry as core_registry,
        bus as core_bus,
        StepStarted, StepCompleted, VerificationPassed, VerificationFailed,
        IOPointStarted, IOPointCompleted,
    )
    _CORE_OK = True
except Exception as _core_err:   # pragma: no cover - exercised only when core absent
    CapabilityMeta = CapabilityRegistry = StepResult = StepStatus = None
    core_registry = None
    core_bus = None
    StepStarted = StepCompleted = VerificationPassed = VerificationFailed = None
    IOPointStarted = IOPointCompleted = None
    _CORE_OK = False
    logger.info("iscs_workflow: iscs_core unavailable — capability bridge disabled (%s)", _core_err)


def _noop_log(_msg: str) -> None:
    pass


if _CORE_OK:

    @dataclass
    class LegacyExecContext:
        """Carries the collaborators a legacy ``_exec_*`` needs, so a stateless
        capability adapter can invoke it. Bridges the old executor signature
        ``(proc, exec_ctx, sampler_ok, log)`` to the uniform ``execute(ctx)``."""
        runner: Any
        proc: "Procedure"
        exec: "ExecContext"
        sampler_ok: bool = False
        log: Callable[[str], None] = _noop_log

    def _to_step_status(status: Any) -> "StepStatus":
        # Map by NAME, not value: ProcedureStatus.ERROR == "error" (lowercase)
        # but StepStatus.ERROR == "ERROR". Names match (PASS/FAIL/SKIP/ERROR).
        name = getattr(status, "name", str(status)).upper()
        try:
            return StepStatus[name]
        except KeyError:
            return StepStatus.ERROR

    class LegacyCapabilityAdapter:
        """Wraps one ``ProcedureRunner._exec_*`` method as a Capability keyed by
        the ProcedureType value. Behavior-preserving: ``execute`` forwards to the
        existing executor and normalizes its ``(status, verify_results,
        screenshot)`` return into a ``StepResult``."""

        def __init__(self, proc_type: "ProcedureType", method_name: str):
            self.proc_type   = proc_type
            self.key         = proc_type.value
            self.method_name = method_name
            self.meta = CapabilityMeta(
                name        = proc_type.name.replace("_", " ").title(),
                category    = _category_for(proc_type),
                description = f"Legacy adapter for {proc_type.value}",
            )

        def execute(self, ctx: "LegacyExecContext") -> "StepResult":
            # M3.4: executors live in adapters/driven/input/legacy_executors.py; they
            # take the runner explicitly (was a bound self._exec_* method).
            from adapters.driven.input import legacy_executors as _legacy_exec
            fn = getattr(_legacy_exec, self.method_name)
            status, verify_results, screenshot = fn(ctx.runner, ctx.proc, ctx.exec, ctx.sampler_ok, ctx.log)
            return StepResult(
                status     = _to_step_status(status),
                screenshot = screenshot or "",
                data       = {"verify_results": verify_results},
            )

    def register_legacy_capabilities(into: "Optional[CapabilityRegistry]" = None,
                                     *, override: bool = False) -> "CapabilityRegistry":
        """Register a LegacyCapabilityAdapter for every ProcedureType.
        Idempotent: existing keys are skipped unless ``override=True``."""
        target = into if into is not None else core_registry
        for proc_type, method_name in _LEGACY_METHOD_MAP.items():
            if target.has(proc_type.value) and not override:
                continue
            target.register(LegacyCapabilityAdapter(proc_type, method_name), override=override)
        return target

    # Auto-register into the global core registry at import time (FR-3 style).
    register_legacy_capabilities()

else:   # pragma: no cover - exercised only when core absent
    LegacyExecContext = None
    LegacyCapabilityAdapter = None

    def register_legacy_capabilities(into=None, *, override: bool = False):
        return None


def registry_step_coverage(reg: "Optional[CapabilityRegistry]" = None):
    """Diagnostic (FR-19 / NFR-9): which ``ProcedureType`` step keys resolve in
    ``reg`` (defaults to the global capability registry). Returns
    ``(covered, missing)`` lists of enum values.

    After startup discovery every value should be covered — by a plugin or, as a
    safety net, a ``LegacyCapabilityAdapter`` — which proves the direct legacy
    ``_exec_*`` fallback in ``_execute_procedure`` is vestigial. A non-empty
    ``missing`` means a step type would fall through to the legacy executor."""
    reg = reg if reg is not None else core_registry
    covered, missing = [], []
    for proc_type in ProcedureType:
        if reg is not None and reg.has(proc_type.value):
            covered.append(proc_type.value)
        else:
            missing.append(proc_type.value)
    return covered, missing


# ═════════════════════════════════════════════════════════════════════════════
#  SHARED EXECUTION CONTEXT  (caches, state, avoids redundant ops)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ExecContext:
    """
    Mutable shared state passed between procedure executors within one point run.

    Caches expensive results (trigger time, samplers, resolved bboxes) so
    subsequent procedures don't need to repeat them.
    """
    point_id         : str
    pt               : dict               # raw point dict from IO list
    trigger_idx      : int  = 0
    reset_idx        : int  = 0
    expected_alarm   : dict = field(default_factory=dict)
    expected_norm    : dict = field(default_factory=dict)
    trigger_ok       : bool = False
    trigger_time     : Optional[datetime.datetime] = None
    trigger_ns       : Optional[int]  = None
    reset_ok         : bool = False
    reset_ns         : Optional[int]  = None
    sampler          : Any  = None          # FrameSampler or None
    norm_sampler     : Any  = None
    resolved_bbox    : Optional[Tuple]= None
    anchor_mgr       : Optional[Any]  = None
    zones_dict       : Dict[str, Any] = field(default_factory=dict)
    sc_dir           : Optional[Path] = None
    point_idx        : int  = 0
    extra            : Dict[str, Any] = field(default_factory=dict)  # future use


# ═════════════════════════════════════════════════════════════════════════════
#  PROCEDURE RUNNER  (sequential executor)
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class _StandaloneCtx:
    """Minimal context mockup for standalone flow runs to avoid point-loop exceptions."""
    sc_dir: Path
    point_idx: int = 0
    point_id: str = "StandaloneFlow"
    pt: dict = field(default_factory=dict)
    trigger_idx: int = 0
    reset_idx: int = 0
    expected_alarm: dict = field(default_factory=dict)
    expected_norm: dict = field(default_factory=dict)
    trigger_ok: bool = False
    trigger_time: Optional[datetime.datetime] = None
    trigger_ns: Optional[int] = None
    reset_ok: bool = False
    reset_ns: Optional[int] = None
    sampler: Any = None
    norm_sampler: Any = None
    resolved_bbox: Optional[Tuple] = None
    zones_dict: Dict[str, Any] = field(default_factory=dict)
    
class ProcedureRunner:
    """
    Executes a ProcedureFlow for every IO point in a scenario.

    Parameters
    ----------
    flow         : ProcedureFlow
    verifier     : ISCSVerifier instance (from baru.py)
    handler      : protocol handler (ModbusProtocol, etc.)
    config       : APP_CONFIG dict
    on_log       : callable(str)
    stop_event   : threading.Event
    pause_event  : threading.Event
    """

    def __init__(
        self,
        flow         : ProcedureFlow,
        verifier     : Any,
        handler      : Any,
        config       : dict,
        on_log       : Callable[[str], None],
        stop_event   : threading.Event,
        pause_event  : threading.Event,
        event_bus    : Any = None,
    ):
        self.flow         = flow
        self.verifier     = verifier
        self.handler      = handler
        self.config       = config
        self.on_log       = on_log
        self._stop        = stop_event
        self._pause       = pause_event
        # Lifecycle event bus (FR-28). Defaults to the shared core bus; pass an
        # explicit bus to isolate, or None to disable emission entirely. Optional
        # so existing callers (positional args) keep working unchanged.
        self.event_bus    = event_bus if event_bus is not None else core_bus

    def _emit(self, event: Any) -> None:
        """Publish a lifecycle event if a bus is present. Never raises — delivery
        is isolated inside EventBus.publish (a bad subscriber can't break a run)."""
        bus = getattr(self, "event_bus", None)
        if bus is not None and event is not None:
            try:
                bus.publish(event)
            except Exception:   # pragma: no cover - defensive belt-and-braces
                logger.exception("event publish failed for %s", type(event).__name__)

    # ── Public entry point ───────────────────────────────────────────────────

    def run_scenario(
        self,
        sc,
        sc_dir        : Path,
        pass_num      : int,
        s_idx         : int,
        on_progress   : Optional[Callable] = None,
        points_override: Optional[list]    = None,
    ) -> List[ExecutionTrace]:
        """
        Execute the procedure flow for every IO point in the scenario.

        points_override: if provided, only run points whose point_id is in this list.
        Returns list[ExecutionTrace] — one per IO point run.
        """
        # --- Pre-execution Validation ---
        points_to_run = getattr(sc, "iscs_points", [])
        if not points_to_run:
            msg = (
                "Incomplete Setup Error: No IO points are configured or imported. "
                "The execution engine requires at least one target IO point to run a sequence. "
                "Please import an IO list or configure points before starting."
            )
            self.on_log(f"[ERROR] {msg}")
            raise ValueError(msg)

        if points_override is not None:
            override_set  = set(points_override)
            points_to_run = [pt for pt in points_to_run
                             if pt.get("point_id") in override_set]
            if not points_to_run:
                msg = (
                    "Incomplete Setup Error: The selected points filter resulted in 0 points to run. "
                    "Please verify that your selection contains active points."
                )
                self.on_log(f"[ERROR] {msg}")
                raise ValueError(msg)

        # --- Honour IO-folder deletions ---
        # When the flow is organised into IO groups, the tree of folders is the
        # source of truth for WHICH points run. Deleting a folder in the editor
        # should drop that point from the run, even though it still exists in the
        # imported IO list (sc.iscs_points). Keep only points that still have a
        # matching folder. (Flat-mode flows with no IO groups are unaffected.)
        if self.flow.has_io_groups():
            live_point_ids = {g.point_id for g in self.flow.io_groups}
            filtered = [pt for pt in points_to_run
                        if pt.get("point_id") in live_point_ids]
            dropped = len(points_to_run) - len(filtered)
            if dropped > 0:
                self.on_log(f"[Info] {dropped} IO point(s) skipped — their folder was "
                            f"removed from the Execution Flow.")
            points_to_run = filtered
            if not points_to_run:
                msg = ("Incomplete Setup Error: All IO folders were removed from the "
                       "Execution Flow, so there is nothing to run. Re-add at least one "
                       "IO folder or re-import the IO list.")
                self.on_log(f"[ERROR] {msg}")
                raise ValueError(msg)

        traces: List[ExecutionTrace] = []

        for i, pt in enumerate(points_to_run):
            if self._stop.is_set():
                break

            self._check_pause()
            if self._stop.is_set():
                break

            point_id = pt.get("point_id", f"pt_{i}")
            self.on_log(f"[{i+1}/{len(points_to_run)}] Testing: {point_id}")

            if on_progress:
                on_progress(point_id, i + 1, len(points_to_run))

            trace = self._run_point(pt, i, sc_dir)
            
            # Logic improvement: After point completes, clear visual caches
            if hasattr(self.verifier, "anchor_mgr") and self.verifier.anchor_mgr:
                self.verifier.anchor_mgr.clear_resolution_cache()

            traces.append(trace)

            for line in trace.format_trace_log():
                self.on_log(line)

        return traces

    # ── Per-point execution ──────────────────────────────────────────────────

    def run_standalone(
        self,
        sc,
        sc_dir: Path,
        on_progress: Optional[Callable] = None
    ) -> List[ProcedureResult]:
        """Executes the procedure flow once sequentially without point loop context."""
        results = []
        ctx = _StandaloneCtx(sc_dir=sc_dir)
        
        # Pull zones from the current scenario setup
        zones_dict = {}
        for page_zones in getattr(sc, "zones_per_page", {}).values():
            for zt, z in page_zones.items():
                if zt not in zones_dict:
                    zones_dict[zt] = z
        for z in getattr(sc, "zones", []):
            if z.zone_type not in zones_dict:
                zones_dict[z.zone_type] = z
        ctx.zones_dict = zones_dict

        try:
            from iscs_Sampler_Anchor import FrameSampler
            SAMPLER_OK = True
            alarm_zone = zones_dict.get("alarm_panel")
            if alarm_zone:
                ctx.resolved_bbox = (alarm_zone.x1, alarm_zone.y1, alarm_zone.x2, alarm_zone.y2)
        except ImportError:
            SAMPLER_OK = False

        enabled_steps = self.flow.enabled_procedures
        for i, proc in enumerate(enabled_steps):
            if self._stop.is_set():
                break
            self._check_pause()
            if self._stop.is_set():
                break

            if on_progress:
                on_progress(proc.name, i + 1, len(enabled_steps))

            res = self._execute_procedure(proc, ctx, SAMPLER_OK)
            results.append(res)
        return results
        
    def _run_point(self, pt: dict, idx: int, sc_dir: Path) -> ExecutionTrace:
        # M3.4: expected-state helpers now live in core (no longer a baru tendril).
        from core.services.expected_state import _get_state_indices, build_expected

        point_id = pt.get("point_id", f"pt_{idx}")
        trace    = ExecutionTrace(point_id=point_id, start_time=datetime.datetime.now())

        try:
            from iscs_Sampler_Anchor import FrameSampler
            SAMPLER_OK = True
        except ImportError:
            SAMPLER_OK = False

        # Build shared execution context
        trigger_idx, reset_idx = _get_state_indices(pt)
        ctx = ExecContext(
            point_id       = point_id,
            pt             = pt,
            trigger_idx    = trigger_idx,
            reset_idx      = reset_idx,
            expected_alarm = build_expected(pt, trigger_idx),
            expected_norm  = build_expected(pt, reset_idx),
            zones_dict     = self.verifier.zones if hasattr(self.verifier, "zones") else {},
            sc_dir         = sc_dir,
            point_idx      = idx,
            anchor_mgr     = getattr(self.verifier, "anchor_mgr", None)
        )

        if ctx.anchor_mgr:
            ctx.anchor_mgr.clear_resolution_cache()

        # Pre-resolve alarm panel bbox once
        alarm_zone = getattr(self.verifier, "alarm_zone", None)
        if alarm_zone:
            ctx.resolved_bbox = (alarm_zone.x1, alarm_zone.y1, alarm_zone.x2, alarm_zone.y2)
            anchor_mgr = getattr(self.verifier, "anchor_mgr", None)
            if anchor_mgr:
                resolved = anchor_mgr.resolve("alarm_panel")
                if resolved:
                    ctx.resolved_bbox = resolved

        # Track which dependencies passed (for conditional skipping)
        passed_names: set[str] = set()
        failed_names: set[str] = set()

        # ── Resolve steps: use IO group if tree structure exists ──────────
        point_id_key = ctx.point_id
        io_group = None
        if self.flow.has_io_groups():
            io_group = self.flow.get_io_group_by_point(point_id_key)
        steps_to_run = io_group.enabled_steps if io_group else self.flow.enabled_procedures

        for proc in steps_to_run:
            if self._stop.is_set():
                break

            # Dependency gate: skip if a required prior step failed
            if proc.depends_on:
                blocked = [dep for dep in proc.depends_on if dep in failed_names]
                if blocked:
                    pr = self._make_skip_result(proc, f"Skipped — dependency failed: {blocked}")
                    trace.results.append(pr)
                    continue

            pr = self._execute_procedure(proc, ctx, SAMPLER_OK)
            trace.results.append(pr)

            if pr.passed:
                passed_names.add(proc.name)
            elif pr.failed:
                failed_names.add(proc.name)

        trace.end_time = datetime.datetime.now()

        # Always record basic trigger timing so the report can show "when the
        # alarm was triggered" even on PASSING points or pure custom-check
        # points (the full failure_diagnostics block is only built on FAIL).
        try:
            import datetime as _dt2
            trig_dt = ctx.trigger_time
            if trig_dt is None and ctx.trigger_ns:
                trig_dt = _dt2.datetime.fromtimestamp(ctx.trigger_ns / 1e9)
            trace.shared_ctx["trigger_info"] = {
                "trigger_time": trig_dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if trig_dt else "N/A",
                "trigger_value": (ctx.expected_alarm or {}).get("trigger_value", "N/A"),
                "point_id": self_point_id if (self_point_id := getattr(trace, "point_id", "")) else "",
            }
        except Exception:
            pass

        # Failure evidence collection (unchanged from SuiteRunner)
        if trace.overall == "FAIL":
            all_verify = [vr for pr in trace.results for vr in pr.verify_results]
            try:
                from core.services.evidence_collector import FailureEvidenceCollector
                import datetime as _dt
                diag = FailureEvidenceCollector.collect(
                    session_dir   = sc_dir,
                    point_idx     = idx,
                    pt            = pt,
                    point_results = all_verify,
                    verifier      = self.verifier,
                    trigger_time  = ctx.trigger_time,
                    expected_alarm= ctx.expected_alarm,
                    config        = self.config,
                    reset_time    = _dt.datetime.fromtimestamp(ctx.reset_ns / 1e9) if ctx.reset_ns else None,
                    expected_norm = ctx.expected_norm,
                )
                trace.shared_ctx["failure_diagnostics"] = diag
            except Exception as fe:
                logger.warning(f"ProcedureRunner: FailureEvidenceCollector failed: {fe}")

        return trace

    # ── Procedure dispatcher ────────────────────────────────────────────────═

    def _execute_procedure(
        self,
        proc       : Procedure,
        ctx        : ExecContext,
        sampler_ok : bool,
    ) -> ProcedureResult:
        """Route a Procedure to the appropriate executor method."""
        t0 = datetime.datetime.now()
        logs: List[str] = []

        def log(msg: str):
            logs.append(msg)
            self.on_log(f"  [{proc.name}] {msg}")

        if _CORE_OK:
            self._emit(StepStarted(step_key=proc.proc_type.value, step_name=proc.name))

        try:
            # ── Capability registry path (P1.3) ─────────────────────────────────
            # Resolve the capability for this step's key from the registry and run
            # it through the uniform execute(ctx) contract. Falls back to the direct
            # legacy method when the registry is unavailable or the key is unregistered.
            cap = None
            if core_registry is not None:
                try:
                    cap = core_registry.get(proc.proc_type.value)
                except Exception:
                    cap = None

            if cap is not None:
                exec_ctx    = LegacyExecContext(runner=self, proc=proc, exec=ctx,
                                                sampler_ok=sampler_ok, log=log)
                step_result = cap.execute(exec_ctx)
                status         = ProcedureStatus[step_result.status.name]
                verify_results = step_result.data.get("verify_results", [])
                screenshot     = step_result.screenshot
            else:
                # M3.4: the legacy executors moved to the input adapter; resolve by
                # name there and pass the runner (self) explicitly.
                from adapters.driven.input import legacy_executors as _legacy_exec
                method_name = _LEGACY_METHOD_MAP.get(proc.proc_type)
                fn = getattr(_legacy_exec, method_name, None) if method_name else None
                if fn is None:
                    raise NotImplementedError(f"No executor for {proc.proc_type}")
                # The legacy executor is a deliberate safety net. When the registry
                # is present but had no capability for this key, that's a degraded
                # state (missing/failed plugin) worth surfacing (NFR-9). When the
                # registry is absent (iscs_core unavailable) this is expected
                # pure-legacy mode, so we stay quiet.
                if core_registry is not None:
                    log(f"⚠ no registered capability for {proc.proc_type.value!r} — "
                        f"using legacy executor (check plugin discovery)")
                status, verify_results, screenshot = fn(self, proc, ctx, sampler_ok, log)

        except Exception as exc:
            status         = ProcedureStatus.ERROR
            verify_results = []
            screenshot     = ""
            error_detail   = f"{type(exc).__name__}: {exc}"
            log(f"EXCEPTION — {error_detail}")
            logger.error(f"ProcedureRunner._execute_procedure [{proc.name}]: {exc}", exc_info=True)
        else:
            error_detail = ""

        t1  = datetime.datetime.now()
        dur = (t1 - t0).total_seconds() * 1000

        if _CORE_OK:
            status_name = getattr(status, "name", str(status)).upper()
            self._emit(StepCompleted(step_key=proc.proc_type.value, step_name=proc.name,
                                     status=status_name, duration_ms=dur))
            if _category_for(proc.proc_type) == "verification":
                if status_name == "PASS":
                    self._emit(VerificationPassed(step_key=proc.proc_type.value,
                                                  step_name=proc.name))
                elif status_name in ("FAIL", "ERROR"):
                    self._emit(VerificationFailed(step_key=proc.proc_type.value,
                                                  step_name=proc.name,
                                                  message=error_detail or ""))

        return ProcedureResult(
            procedure_name  = proc.name,
            proc_type       = proc.proc_type.value,
            status          = status,
            start_time      = t0,
            end_time        = t1,
            duration_ms     = dur,
            log_lines       = logs,
            verify_results  = verify_results,
            error_detail    = error_detail,
            screenshot_path = screenshot,
        )

    # ── Action / verification executors ───────────────────────────────────────
    # M3.4: the legacy _exec_* fallback executors moved to
    # adapters/driven/input/legacy_executors.py (keeps pyautogui out of the
    # engine). LegacyCapabilityAdapter + the dispatcher's fallback call them there.

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _sleep(self, seconds: float, granularity: float = 0.05):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop.is_set():
                return
            time.sleep(min(granularity, deadline - time.monotonic()))

    def _check_pause(self):
        if not self._pause.is_set():
            while not self._pause.wait(timeout=0.2):
                if self._stop.is_set():
                    return

    @staticmethod
    def _make_skip_result(proc: Procedure, reason: str) -> ProcedureResult:
        now = datetime.datetime.now()
        return ProcedureResult(
            procedure_name = proc.name,
            proc_type      = proc.proc_type.value,
            status         = ProcedureStatus.SKIP,
            start_time     = now,
            end_time       = now,
            duration_ms    = 0.0,
            log_lines      = [reason],
        )
