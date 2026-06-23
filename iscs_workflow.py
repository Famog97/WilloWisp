"""
iscs_workflow.py
════════════════════════════════════════════════════════════════════════════
ISCS Automation Framework — Configurable Procedure Execution Engine
════════════════════════════════════════════════════════════════════════════

Drop-in companion to baru.py (AutoClick ISCS Framework).

Architecture
────────────
  UI (baru.py SuiteRunnerTab / ScenarioCard)
    ↓
  ProcedureFlow   — ordered list of Procedure objects per scenario
    ↓
  ProcedureRunner — sequential executor, produces ExecutionTrace
    ↓
  Existing ISCSVerifier / Protocol / Navigation / OCR logic (unchanged)

Key design decisions
────────────────────
• Zero changes required to the existing UI, Verifier, or report system.
• SuiteRunner._run_scenario() is replaced by ProcedureRunner.run_scenario().
• Procedures are plain dataclasses — JSON-serialisable, no hidden state.
• Auto-registration builds a smart default flow from a scenario's config,
  so existing scenarios work without manual procedure setup.
• The ExecutionTrace is shaped identically to the sc_results list that
  ReportManager.generate_reports() already expects, so reports keep working.

Usage (minimal integration, single import)
──────────────────────────────────────────
    from iscs_workflow import ProcedureFlow, ProcedureRunner, auto_register_procedures

    # inside SuiteRunner._run_scenario():
    flow   = auto_register_procedures(sc, zones_dict, nav)
    runner = ProcedureRunner(flow, verifier, handler, config, on_log, stop_event, pause_event)
    result = runner.run_scenario(sc, sc_dir, pass_num, s_idx)
    sc_results.extend(result.flat_records)   # same shape as before

Tkinter UI — ProcedureFlowDialog
─────────────────────────────────
    Call ProcedureFlowDialog(master, flow).show()  from a scenario card button.
    The dialog lets users reorder / enable / disable / inspect procedures.
    It does NOT run; it only edits the ProcedureFlow in place.
"""

from __future__ import annotations

import datetime
import logging
import time
import threading
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AutoClick")

try:
    import iscs_OCR
except ImportError:
    iscs_OCR = None

try:
    from iscs_assets import AssetManager, BindingExecutor, StepBinding, BindingType
    _ASSETS_OK = True
except ImportError:
    AssetManager    = None
    BindingExecutor = None
    StepBinding     = None
    BindingType     = None
    _ASSETS_OK      = False

try:
    from PIL import Image, ImageGrab
    _PIL_OK = True
except ImportError:
    Image = None
    ImageGrab = None
    _PIL_OK = False

try:
    from PIL import ImageTk
    _PILTK_OK = True
except ImportError:
    ImageTk = None
    _PILTK_OK = False


# ═════════════════════════════════════════════════════════════════════════════
#  ENUMERATIONS  &  CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

class ProcedureCategory(str, Enum):
    ACTION       = "action"       # trigger, reset, navigate, click
    VERIFICATION = "verification" # OCR / color checks
    UTILITY      = "utility"      # delay, screenshot, state check


class ProcedureStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASS    = "PASS"
    FAIL    = "FAIL"
    SKIP    = "SKIP"
    ERROR   = "error"


class ProcedureType(str, Enum):
    # ── Action
    TRIGGER_ALARM       = "trigger_alarm"
    RESET_ALARM         = "reset_alarm"
    NAVIGATE_HOME       = "navigate_home"
    NAVIGATE_ALARM_LIST = "navigate_alarm_list"
    NAVIGATE_EVENT_LIST = "navigate_event_list"
    NAVIGATE_EQUIP_PAGE = "navigate_equipment_page"
    # ── Verification
    VERIFY_ALARM_PANEL  = "verify_alarm_panel"
    VERIFY_NORMALIZE    = "verify_normalize"
    VERIFY_ALARM_LIST   = "verify_alarm_list"
    VERIFY_EVENT_LIST   = "verify_event_list"
    VERIFY_EQUIP_PAGE   = "verify_equipment_page"
    # ── Utility
    DELAY               = "delay"
    SCREENSHOT          = "screenshot"
    # ── / Custom
    CLICK           = "click"
    RIGHT_CLICK     = "right_click"
    HOTKEY          = "hotkey"
    TYPE_TEXT       = "type_text"
    VERIFY_ALARM_PANEL_CUSTOM = "verify_alarm_panel_custom"
    VERIFY_CUSTOM             = "verify_custom"   # asset-bound custom verify step


# ── Dynamic (plugin) step types (P6.3) ───────────────────────────────────────
# Decouples the Procedure model from the closed ProcedureType enum: a plugin can
# define a brand-new step key and it round-trips + executes (via the registry)
# without being added to the enum. Enum members stay the canonical built-ins.
_PROC_TYPE_SENTINEL = object()


class _DynamicProcType:
    """A ProcedureType-like wrapper for plugin step keys not in the enum. Quacks
    like an enum member: exposes .value and .name, compares + hashes by value, so
    all existing `proc_type.value` / `== ProcedureType.X` code keeps working."""
    __slots__ = ("value", "name")

    def __init__(self, key):
        self.value = str(key)
        self.name  = str(key).upper()

    def __eq__(self, other):
        return getattr(other, "value", _PROC_TYPE_SENTINEL) == self.value

    def __hash__(self):
        return hash(self.value)

    def __repr__(self):
        return f"<DynamicProcType {self.value!r}>"


def _resolve_proc_type(key):
    """Return the ProcedureType for a known key, else a _DynamicProcType (P6.3)."""
    if isinstance(key, (ProcedureType, _DynamicProcType)):
        return key
    try:
        return ProcedureType(key)
    except ValueError:
        return _DynamicProcType(str(key))


# ═════════════════════════════════════════════════════════════════════════════
#  PROCEDURE  DATACLASS
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Procedure:
    """
    A single, independent execution unit in a scenario flow.

    Attributes
    ----------
    proc_type   : ProcedureType  – what this step does
    category    : ProcedureCategory
    name        : str            – human-readable label shown in UI / logs
    enabled     : bool           – if False this step is skipped at runtime
    order       : int            – execution sequence (lower = earlier)
    params      : dict           – step-specific config (e.g. delay_sec, step_label)
    description : str            – tooltip / help text
    depends_on  : list[str]      – names of procedures that must PASS first (optional)
    """
    proc_type   : ProcedureType
    category    : ProcedureCategory
    name        : str
    enabled     : bool             = True
    order       : int              = 0
    params      : Dict[str, Any]   = field(default_factory=dict)
    description : str              = ""
    depends_on  : List[str]        = field(default_factory=list)
    # ── New fields (backward-compatible — both default to safe no-op values) ──
    step_id     : str              = ""    # e.g. STP_0001, stable unique identity
    binding     : Optional[dict]   = None  # StepBinding.to_dict() or None

    def to_dict(self) -> dict:
        d = {
            "proc_type":   self.proc_type.value,
            "category":    self.category.value,
            "name":        self.name,
            "enabled":     self.enabled,
            "order":       self.order,
            "params":      self.params,
            "description": self.description,
            "depends_on":  self.depends_on,
            "step_id":     self.step_id,
        }
        if self.binding is not None:
            d["binding"] = self.binding
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Optional[Procedure]":
        raw = d.get("proc_type")
        if not raw:
            return None                      # malformed entry (no type) — drop
        # P6.3: unknown keys are KEPT as a dynamic type (a plugin may provide them),
        # not dropped — they round-trip and execute via the registry, or surface a
        # clear ERROR at runtime if nothing handles them.
        proc_type = _resolve_proc_type(raw)
        raw = d.get("proc_type")
        if not raw:
            return None                      # malformed entry (no type) — drop
        # P6.3: unknown keys are KEPT as a dynamic type (a plugin may provide them),
        # not dropped — they round-trip and execute via the registry, or surface a
        # clear ERROR at runtime if nothing handles them.
        proc_type = _resolve_proc_type(raw)
        try:
            category = ProcedureCategory(d["category"])
        except (ValueError, KeyError):
            category = ProcedureCategory.UTILITY
        return cls(
            proc_type   = proc_type,
            category    = category,
            name        = d.get("name", "Unknown Step"),
            enabled     = d.get("enabled", True),
            order       = d.get("order", 0),
            params      = d.get("params", {}),
            description = d.get("description", ""),
            depends_on  = d.get("depends_on", []),
            step_id     = d.get("step_id", ""),
            binding     = d.get("binding", None),
    )


# ═════════════════════════════════════════════════════════════════════════════
#  PROCEDURE RESULT  (per-step trace entry)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ProcedureResult:
    """Execution outcome for a single Procedure step."""
    procedure_name  : str
    proc_type       : str
    status          : ProcedureStatus
    start_time      : datetime.datetime
    end_time        : datetime.datetime
    duration_ms     : float
    log_lines       : List[str]         = field(default_factory=list)
    verify_results  : List[Any]         = field(default_factory=list)   # list[VerifyResult]
    error_detail    : str               = ""
    screenshot_path : str               = ""

    @property
    def passed(self) -> bool:
        return self.status == ProcedureStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status == ProcedureStatus.FAIL

    def summary_line(self, idx: int) -> str:
        icon = "✓" if self.passed else ("–" if self.status == ProcedureStatus.SKIP else "✗")
        dur  = f"{self.duration_ms:.0f}ms"
        return f"[Step {idx:02d}] [{icon}] {self.procedure_name:<28}  {self.status.value:<6}  {dur}"


# ═════════════════════════════════════════════════════════════════════════════
#  EXECUTION TRACE  (one full point run)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ExecutionTrace:
    """
    Complete execution trace for one IO point across all procedure steps.

    flat_records mirrors the structure of sc_results entries that
    SuiteRunner currently builds and ReportManager.generate_reports() reads.
    This means the existing report pipeline works without modification.
    """
    point_id     : str
    start_time   : datetime.datetime
    end_time     : Optional[datetime.datetime] = None
    results      : List[ProcedureResult]       = field(default_factory=list)
    shared_ctx   : Dict[str, Any]              = field(default_factory=dict)

    @property
    def overall(self) -> str:
        if any(r.failed for r in self.results):
            return "FAIL"
        if all(r.status == ProcedureStatus.SKIP for r in self.results):
            return "SKIP"
        return "PASS"

    @property
    def total_duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return 0.0

    def _find(self, step_key: str, field: str = "msg") -> str:
        """Helper: pull msg or status from VerifyResult by step key."""
        for pr in self.results:
            for vr in pr.verify_results:
                if hasattr(vr, "step") and vr.step == step_key:
                    return getattr(vr, field, "")
        return ""

    def _status_prefix(self, prefix: str) -> str:
        for pr in self.results:
            for vr in pr.verify_results:
                if hasattr(vr, "step") and vr.step.startswith(prefix) and vr.status == "FAIL":
                    return "FAIL"
        has_any = any(
            hasattr(vr, "step") and vr.step.startswith(prefix)
            for pr in self.results for vr in pr.verify_results
        )
        return "PASS" if has_any else "SKIP"

    @property
    def flat_records(self) -> List[dict]:
        """
        Returns a list containing one dict shaped exactly like the sc_results
        entries SuiteRunner builds, so ReportManager.generate_reports() works
        without any changes.
        """
        screenshot = next(
            (r.screenshot_path for r in self.results if r.screenshot_path), ""
        )
        diag = self.shared_ctx.get("failure_diagnostics")
        trig_info = self.shared_ctx.get("trigger_info")

        rec = {
            "point_id":             self.point_id,
            "overall":              self.overall,
            "failure_diagnostics":  diag,
            "trigger_info":         trig_info,
            # ── Alarm Panel — Trigger
            "trigger_datetime":     self._find("alarm_panel/datetime"),
            "trigger_identifier":   self._find("alarm_panel/identifier"),
            "trigger_description":  self._find("alarm_panel/description"),
            "trigger_value":        self._find("alarm_panel/value"),
            "trigger_severity":     self._find("alarm_panel/severity"),
            "trigger_color":        self._find("alarm_panel/color"),
            "trigger_overall":      self._status_prefix("alarm_panel"),
            # ── Alarm Panel — Normalize
            "norm_datetime":        self._find("normalize/datetime"),
            "norm_identifier":      self._find("normalize/identifier"),
            "norm_value":           self._find("normalize/value"),
            "norm_severity":        self._find("normalize/severity"),
            "norm_color":           self._find("normalize/color"),
            "norm_overall":         self._status_prefix("normalize"),
            # ── Alarm List — Trigger
            "al_trigger_identifier": self._find("alarm_list/trigger/identifier"),
            "al_trigger_value":      self._find("alarm_list/trigger/value"),
            "al_trigger_severity":   self._find("alarm_list/trigger/severity"),
            "al_trigger_color":      self._find("alarm_list/trigger/color"),
            "al_trigger_overall":    self._status_prefix("alarm_list/trigger"),
            # ── Alarm List — Normalize
            "al_norm_value":         self._find("alarm_list/normalize/value"),
            "al_norm_color":         self._find("alarm_list/normalize/color"),
            "al_norm_overall":       self._status_prefix("alarm_list/normalize"),
            # ── Event List — Trigger
            "ev_trigger_identifier": self._find("event_list/trigger/identifier"),
            "ev_trigger_value":      self._find("event_list/trigger/value"),
            "ev_trigger_severity":   self._find("event_list/trigger/severity"),
            "ev_trigger_color":      self._find("event_list/trigger/color"),
            "ev_trigger_overall":    self._status_prefix("event_list/trigger"),
            # ── Event List — Normalize
            "ev_norm_value":         self._find("event_list/normalize/value"),
            "ev_norm_color":         self._find("event_list/normalize/color"),
            "ev_norm_overall":       self._status_prefix("event_list/normalize"),
            # ── Equipment Page
            "eq_overall":  self._status_prefix("equipment"),
            "eq_detail":   self._find("equipment/identifier"),
            # ── Screenshot
            "screenshot":  screenshot,
            # ── Asset-bound custom verify steps (VERIFY_CUSTOM) ──
            "custom_checks": self._collect_custom_checks(),
        }
        return [rec]

    def _collect_custom_checks(self) -> List[dict]:
        """
        Collects results from VERIFY_CUSTOM steps (asset-bound bindings).
        These carry expected/actual/asset_name attributes set by
        ProcedureRunner._exec_verify_custom via BindingExecutor.
        Returns a list of dicts ready for ReportManager rendering.
        """
        out = []
        for pr in self.results:
            if pr.proc_type != ProcedureType.VERIFY_CUSTOM.value:
                continue
            for vr in pr.verify_results:
                out.append({
                    "name":       pr.procedure_name,
                    "status":     getattr(vr, "status", "FAIL"),
                    "message":    getattr(vr, "message", getattr(vr, "msg", "")),
                    "expected":   getattr(vr, "expected", ""),
                    "actual":     getattr(vr, "actual", ""),
                    "asset_name": getattr(vr, "asset_name", ""),
                    "asset_id":   getattr(vr, "asset_id", ""),
                    "screenshot": getattr(vr, "screenshot", ""),
                })
        return out

    def format_trace_log(self) -> List[str]:
        """Returns pretty-printed execution trace log lines."""
        lines = [f"  ┌─ {self.point_id} — {self.overall} ───────────────────────"]
        for idx, pr in enumerate(self.results, 1):
            lines.append(f"  │  {pr.summary_line(idx)}")
            for vr in pr.verify_results:
                if hasattr(vr, "step") and hasattr(vr, "status") and hasattr(vr, "msg"):
                    icon = "✓" if vr.status == "PASS" else ("–" if vr.status == "SKIP" else "✗")
                    field = vr.step.split("/")[-1].upper().ljust(12)
                    lines.append(f"  │    [{icon}] {field} {vr.msg}")
            if pr.error_detail:
                lines.append(f"  │    [!] {pr.error_detail}")
        lines.append(f"  └{'─' * 50}")
        return lines


# ═════════════════════════════════════════════════════════════════════════════
#  PROCEDURE FLOW  (ordered collection of procedures for one scenario)
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
#  IO GROUP  — one folder per IO point in the flow tree
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class IOGroup:
    """
    One IO point's folder in the flow tree.
    Contains the ordered Procedure steps that run for that specific point.

    io_id     : stable unique ID  e.g. IO_0001
    point_id  : maps to iscs_points[i]["point_id"]
    label     : human-readable "Equipment: Attribute"
    steps     : ordered list of Procedure steps for this IO point
    """
    io_id    : str
    point_id : str
    label    : str             = ""
    steps    : List[Procedure] = field(default_factory=list)

    @property
    def enabled_steps(self) -> List[Procedure]:
        return [s for s in sorted(self.steps, key=lambda p: p.order) if s.enabled]

    @property
    def ordered_steps(self) -> List[Procedure]:
        return sorted(self.steps, key=lambda p: p.order)

    def add_step(self, proc: Procedure) -> None:
        if proc.order == 0 and self.steps:
            proc.order = max(p.order for p in self.steps) + 10
        self.steps.append(proc)

    def get(self, name: str) -> Optional[Procedure]:
        return next((s for s in self.steps if s.name == name), None)

    def remove_step(self, name: str) -> bool:
        before = len(self.steps)
        self.steps = [p for p in self.steps if p.name != name]
        return len(self.steps) < before

    def to_dict(self) -> dict:
        return {
            "io_id":    self.io_id,
            "point_id": self.point_id,
            "label":    self.label,
            "steps":    [s.to_dict() for s in self.ordered_steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IOGroup":
        steps = [Procedure.from_dict(sd) for sd in d.get("steps", [])]
        steps = [s for s in steps if s is not None]
        return cls(
            io_id    = d.get("io_id", ""),
            point_id = d.get("point_id", ""),
            label    = d.get("label", ""),
            steps    = steps,
        )


# ── ID generators (module-level counters, reset per session) ──────────────────
_io_group_counter  = 0
_step_id_counter   = 0

def _next_io_id() -> str:
    global _io_group_counter
    _io_group_counter += 1
    return f"IO_{_io_group_counter:04d}"

def _next_step_id() -> str:
    global _step_id_counter
    _step_id_counter += 1
    return f"STP_{_step_id_counter:04d}"


# ═════════════════════════════════════════════════════════════════════════════
#  FLOW SCHEMA VERSIONING  (FR-27)
# ═════════════════════════════════════════════════════════════════════════════
# Persisted flows carry a schema_version so older/newer saved data can coexist.
# Bump FLOW_SCHEMA_VERSION when the on-disk shape changes and register a migrator
# keyed by the version it upgrades FROM. Migrators are applied in sequence until
# the dict reaches the current version (Chain of Responsibility).
FLOW_SCHEMA_VERSION = 1

# {from_version: callable(dict) -> dict}. Empty today (v1 is the first version);
# the mechanism is in place so a future v1→v2 change is a one-line addition.
_FLOW_MIGRATORS: Dict[int, Callable[[dict], dict]] = {}


def register_flow_migrator(from_version: int, fn: Callable[[dict], dict]) -> None:
    """Register a migrator that upgrades a flow dict FROM `from_version` to the next."""
    _FLOW_MIGRATORS[from_version] = fn


def _migrate_flow_dict(d: dict, migrators: Optional[Dict[int, Callable[[dict], dict]]] = None,
                       current: int = FLOW_SCHEMA_VERSION) -> dict:
    """Upgrade a persisted flow dict to the current schema version.

    - Missing schema_version is treated as the current version (legacy data saved
      before versioning is, by definition, in the current shape).
    - A version newer than this app supports raises a clear error (don't silently
      mangle data written by a newer build).
    """
    migrators = _FLOW_MIGRATORS if migrators is None else migrators
    version = d.get("schema_version", current)
    if not isinstance(version, int):
        version = current
    if version > current:
        raise ValueError(
            f"Flow schema_version {version} is newer than supported ({current}). "
            f"Upgrade the application to load this flow."
        )
    while version < current:
        migrator = migrators.get(version)
        if migrator is None:
            raise ValueError(f"No migrator registered to upgrade flow schema from v{version}.")
        d = migrator(d)
        version += 1
    return d


# ═════════════════════════════════════════════════════════════════════════════
#  FLOW SCHEMA VERSIONING  (FR-27)
# ═════════════════════════════════════════════════════════════════════════════
# Persisted flows carry a schema_version so older/newer saved data can coexist.
# Bump FLOW_SCHEMA_VERSION when the on-disk shape changes and register a migrator
# keyed by the version it upgrades FROM. Migrators are applied in sequence until
# the dict reaches the current version (Chain of Responsibility).
FLOW_SCHEMA_VERSION = 1

# {from_version: callable(dict) -> dict}. Empty today (v1 is the first version);
# the mechanism is in place so a future v1→v2 change is a one-line addition.
_FLOW_MIGRATORS: Dict[int, Callable[[dict], dict]] = {}


def register_flow_migrator(from_version: int, fn: Callable[[dict], dict]) -> None:
    """Register a migrator that upgrades a flow dict FROM `from_version` to the next."""
    _FLOW_MIGRATORS[from_version] = fn


def _migrate_flow_dict(d: dict, migrators: Optional[Dict[int, Callable[[dict], dict]]] = None,
                       current: int = FLOW_SCHEMA_VERSION) -> dict:
    """Upgrade a persisted flow dict to the current schema version.

    - Missing schema_version is treated as the current version (legacy data saved
      before versioning is, by definition, in the current shape).
    - A version newer than this app supports raises a clear error (don't silently
      mangle data written by a newer build).
    """
    migrators = _FLOW_MIGRATORS if migrators is None else migrators
    version = d.get("schema_version", current)
    if not isinstance(version, int):
        version = current
    if version > current:
        raise ValueError(
            f"Flow schema_version {version} is newer than supported ({current}). "
            f"Upgrade the application to load this flow."
        )
    while version < current:
        migrator = migrators.get(version)
        if migrator is None:
            raise ValueError(f"No migrator registered to upgrade flow schema from v{version}.")
        d = migrator(d)
        version += 1
    return d


class ProcedureFlow:
    """
    Ordered, configurable list of Procedure steps for a scenario.

    Supports:
      • reorder   – move a step up/down
      • enable / disable individual steps
      • add / remove custom steps
      • serialise / deserialise to JSON (stored alongside scenario card config)
    """

    def __init__(self, procedures: Optional[List[Procedure]] = None,
                 io_groups: Optional[List["IOGroup"]] = None):
        self._procedures: List[Procedure] = sorted(
            procedures or [], key=lambda p: p.order
        )
        # IO folder tree — one IOGroup per imported IO point
        self.io_groups: List["IOGroup"] = io_groups or []

    # ── IO group helpers ─────────────────────────────────────────────────

    def get_io_group(self, io_id: str) -> Optional["IOGroup"]:
        return next((g for g in self.io_groups if g.io_id == io_id), None)

    def get_io_group_by_point(self, point_id: str) -> Optional["IOGroup"]:
        return next((g for g in self.io_groups if g.point_id == point_id), None)

    def add_io_group(self, group: "IOGroup") -> None:
        self.io_groups.append(group)

    def remove_io_group(self, io_id: str) -> bool:
        before = len(self.io_groups)
        self.io_groups = [g for g in self.io_groups if g.io_id != io_id]
        return len(self.io_groups) < before

    def has_io_groups(self) -> bool:
        return bool(self.io_groups)


    # ── Ordered read access ──────────────────────────────────────────────────

    @property
    def procedures(self) -> List[Procedure]:
        return sorted(self._procedures, key=lambda p: p.order)

    @property
    def enabled_procedures(self) -> List[Procedure]:
        return [p for p in self.procedures if p.enabled]

    def __len__(self) -> int:
        return len(self._procedures)

    def __iter__(self):
        return iter(self.procedures)

    # ── Mutation ─────────────────────────────────────────────────────────────

    def add(self, proc: Procedure) -> None:
        if proc.order == 0 and self._procedures:
            proc.order = max(p.order for p in self._procedures) + 10
        self._procedures.append(proc)

    def remove(self, name: str) -> bool:
        before = len(self._procedures)
        self._procedures = [p for p in self._procedures if p.name != name]
        return len(self._procedures) < before

    def set_enabled(self, name: str, enabled: bool) -> bool:
        for p in self._procedures:
            if p.name == name:
                p.enabled = enabled
                return True
        return False

    def move_up(self, name: str) -> bool:
        procs = self.procedures
        idx = next((i for i, p in enumerate(procs) if p.name == name), None)
        if idx is None or idx == 0:
            return False
        procs[idx].order, procs[idx - 1].order = procs[idx - 1].order, procs[idx].order
        return True

    def move_down(self, name: str) -> bool:
        procs = self.procedures
        idx = next((i for i, p in enumerate(procs) if p.name == name), None)
        if idx is None or idx >= len(procs) - 1:
            return False
        procs[idx].order, procs[idx + 1].order = procs[idx + 1].order, procs[idx].order
        return True

    def get(self, name: str) -> Optional[Procedure]:
        return next((p for p in self._procedures if p.name == name), None)

    def duplicate(self, name: str) -> Optional["Procedure"]:
        """Clone a procedure, appending a unique suffix to the name, and insert it directly after the original."""
        orig = self.get(name)
        if orig is None:
            return None
        # Find a unique name: "Step Name (2)", "(3)", ...
        base = orig.name
        suffix = 2
        while True:
            candidate = f"{base} ({suffix})"
            if self.get(candidate) is None:
                break
            suffix += 1
        # Insert order: halfway between orig and the next step, or orig+5
        procs = self.procedures
        orig_idx = next(i for i, p in enumerate(procs) if p.name == name)
        if orig_idx < len(procs) - 1:
            next_order = procs[orig_idx + 1].order
            new_order  = orig.order + max(1, (next_order - orig.order) // 2)
        else:
            new_order = orig.order + 5
        import copy
        clone = copy.deepcopy(orig)
        clone.name  = candidate
        clone.order = new_order
        self._procedures.append(clone)
        return clone

    # ── Serialise ────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d = {
            "schema_version": FLOW_SCHEMA_VERSION,
            "procedures": [p.to_dict() for p in self.procedures],
        }
        d = {
            "schema_version": FLOW_SCHEMA_VERSION,
            "procedures": [p.to_dict() for p in self.procedures],
        }
        if self.io_groups:
            d["io_groups"] = [g.to_dict() for g in self.io_groups]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProcedureFlow":
        d = _migrate_flow_dict(d)                      # upgrade older saved data first (FR-27)
        d = _migrate_flow_dict(d)                      # upgrade older saved data first (FR-27)
        procs  = [Procedure.from_dict(pd) for pd in d.get("procedures", [])]
        groups = [IOGroup.from_dict(gd)   for gd in d.get("io_groups",  [])]
        return cls(procedures=procs, io_groups=groups)

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, s: str) -> "ProcedureFlow":
        import json
        return cls.from_dict(json.loads(s))


# ═════════════════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION  — smart default flow from scenario config
# ═════════════════════════════════════════════════════════════════════════════

def auto_register_procedures(sc, zones_dict: dict, nav: dict) -> ProcedureFlow:
    """
    Build a smart default ProcedureFlow from a scenario's existing config.

    This is called once per scenario run when no saved flow is available, or
    can be called to regenerate defaults after a scenario config change.

    Parameters
    ----------
    sc          : Scenario-like object (has .iscs_points, .card_cfg, etc.)
    zones_dict  : dict[str, Zone]  – merged zones for the scenario
    nav         : dict             – navigation coordinates from card_cfg

    Returns
    -------
    ProcedureFlow with sensible default steps pre-populated.
    """
    procs: List[Procedure] = []
    order = 10  # step counter (increments by 10 so users can insert between)

    def _xy(key: str) -> Tuple[int, int]:
        return nav.get(key, {}).get("x", 0), nav.get(key, {}).get("y", 0)

    has_points      = bool(getattr(sc, "iscs_points", []))
    has_alarm_panel = "alarm_panel"    in zones_dict
    has_alarm_list  = "alarm_list"     in zones_dict
    has_event_list  = "event_list"     in zones_dict
    has_equip_page  = "equipment_page" in zones_dict
    hm_x, hm_y     = _xy("home_btn")
    al_x, al_y     = _xy("alarm_list_btn")
    ev_x, ev_y     = _xy("event_list_btn")
    rc_x, rc_y     = _xy("rightclick_row1")
    pg_x, pg_y     = _xy("rightclick_page_btn")
    has_home        = (hm_x != 0 or hm_y != 0)
    has_al_nav      = (al_x != 0 or al_y != 0)
    has_ev_nav      = (ev_x != 0 or ev_y != 0)
    has_equip_nav   = (rc_x != 0 and rc_y != 0 and pg_x != 0 and pg_y != 0)

    # ── 1. Trigger Alarm ─────────────────────────────────────────────────────
    if has_points:
        procs.append(Procedure(
            proc_type   = ProcedureType.TRIGGER_ALARM,
            category    = ProcedureCategory.ACTION,
            name        = "Trigger Alarm",
            order       = order,
            description = "Send alarm signal via configured protocol (Modbus/SNMP).",
        ))
        order += 10

    # ── 2. Verify Alarm Panel ────────────────────────────────────────────────
    if has_alarm_panel:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_ALARM_PANEL,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Alarm Panel",
            order       = order,
            description = "OCR + color check on the alarm panel zone after trigger.",
            depends_on  = ["Trigger Alarm"],
        ))
        order += 10

    # ── 3. Navigate → Alarm List ─────────────────────────────────────────────
    if has_home or has_al_nav:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_ALARM_LIST,
            category    = ProcedureCategory.ACTION,
            name        = "Navigate to Alarm List",
            order       = order,
            enabled     = has_al_nav,
            params      = {"home_x": hm_x, "home_y": hm_y,
                           "al_x": al_x,   "al_y": al_y},
            description = "Click Home then Alarm List nav button.",
        ))
        order += 10

    # ── 4. Verify Alarm List ─────────────────────────────────────────────────
    if has_alarm_list:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_ALARM_LIST,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Alarm List",
            order       = order,
            enabled     = has_al_nav,
            description = "OCR + color check on the alarm list zone.",
            depends_on  = ["Navigate to Alarm List"],
        ))
        order += 10

    # ── 5. Navigate → Event List ─────────────────────────────────────────────
    if has_home or has_ev_nav:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_EVENT_LIST,
            category    = ProcedureCategory.ACTION,
            name        = "Navigate to Event List",
            order       = order,
            enabled     = has_ev_nav,
            params      = {"home_x": hm_x, "home_y": hm_y,
                           "ev_x": ev_x,   "ev_y": ev_y},
            description = "Click Home then Event List nav button.",
        ))
        order += 10

    # ── 6. Verify Event List ─────────────────────────────────────────────────
    if has_event_list:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_EVENT_LIST,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Event List",
            order       = order,
            enabled     = has_ev_nav,
            description = "OCR + color check on the event list zone.",
            depends_on  = ["Navigate to Event List"],
        ))
        order += 10

    # ── 7. Navigate → Equipment Page ─────────────────────────────────────────
    if has_equip_nav or has_equip_page:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_EQUIP_PAGE,
            category    = ProcedureCategory.ACTION,
            name        = "Navigate to Equipment Page",
            order       = order,
            enabled     = has_equip_nav,
            params      = {"home_x": hm_x, "home_y": hm_y,
                           "rc_x": rc_x,   "rc_y": rc_y,
                           "pg_x": pg_x,   "pg_y": pg_y},
            description = "Click Home, right-click alarm row, open equipment page.",
        ))
        order += 10

    # ── 8. Verify Equipment Page ─────────────────────────────────────────────
    if has_equip_page:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_EQUIP_PAGE,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Equipment Page",
            order       = order,
            enabled     = has_equip_nav,
            description = "OCR check on the equipment detail page.",
            depends_on  = ["Navigate to Equipment Page"],
        ))
        order += 10

    # ── 9. Navigate Home (pre-reset) ─────────────────────────────────────────
    if has_home:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_HOME,
            category    = ProcedureCategory.ACTION,
            name        = "Return to Home",
            order       = order,
            description = "Click Home button to return to main view before reset.",
            params      = {"home_x": hm_x, "home_y": hm_y},
        ))
        order += 10

    # ── 10. Reset Alarm ──────────────────────────────────────────────────────
    if has_points:
        procs.append(Procedure(
            proc_type   = ProcedureType.RESET_ALARM,
            category    = ProcedureCategory.ACTION,
            name        = "Reset Alarm",
            order       = order,
            description = "Send reset/normalize signal via configured protocol.",
        ))
        order += 10

    # ── 11. Verify Normalized State ──────────────────────────────────────────
    if has_alarm_panel:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_NORMALIZE,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Normalize State",
            order       = order,
            description = "OCR + color check that the alarm panel returned to normal.",
            depends_on  = ["Reset Alarm"],
        ))
        order += 10

    flow = ProcedureFlow(procs)

    # ── Build IO group tree from imported points ──────────────────────────
    points = getattr(sc, "iscs_points", []) or []
    if points:
        step_counter = [0]
        for pt in points:
            pid   = pt.get("point_id", "")
            equip = pt.get("equipment_description", pt.get("equip_desc", ""))
            attr  = pt.get("attribute_description",  pt.get("attr_desc",  ""))
            lbl   = f"{equip}: {attr}".strip(": ") if (equip or attr) else pid

            group = IOGroup(
                io_id    = _next_io_id(),
                point_id = pid,
                label    = lbl,
            )
            # Clone the shared procs template into this IO group
            # Each step gets a unique step_id for stable referencing
            import copy
            for p in procs:
                clone = copy.deepcopy(p)
                clone.step_id = _next_step_id()
                group.steps.append(clone)
            flow.add_io_group(group)

    return flow


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
    ):
        self.flow         = flow
        self.verifier     = verifier
        self.handler      = handler
        self.config       = config
        self.on_log       = on_log
        self._stop        = stop_event
        self._pause       = pause_event

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
        from baru import _get_state_indices, build_expected  # late import — keeps module independent

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
                from baru import FailureEvidenceCollector
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

        try:
            dispatch = {
                ProcedureType.TRIGGER_ALARM       : self._exec_trigger_alarm,
                ProcedureType.RESET_ALARM         : self._exec_reset_alarm,
                ProcedureType.NAVIGATE_HOME       : self._exec_navigate_home,
                ProcedureType.NAVIGATE_ALARM_LIST : self._exec_navigate_alarm_list,
                ProcedureType.NAVIGATE_EVENT_LIST : self._exec_navigate_event_list,
                ProcedureType.NAVIGATE_EQUIP_PAGE : self._exec_navigate_equip_page,
                ProcedureType.VERIFY_ALARM_PANEL  : self._exec_verify_alarm_panel,
                ProcedureType.VERIFY_NORMALIZE    : self._exec_verify_normalize,
                ProcedureType.VERIFY_ALARM_LIST   : self._exec_verify_alarm_list,
                ProcedureType.VERIFY_EVENT_LIST   : self._exec_verify_event_list,
                ProcedureType.VERIFY_EQUIP_PAGE   : self._exec_verify_equip_page,
                ProcedureType.DELAY               : self._exec_delay,
                ProcedureType.SCREENSHOT          : self._exec_screenshot,
                ProcedureType.CLICK               : self._exec_click,
                ProcedureType.RIGHT_CLICK         : self._exec_right_click,
                ProcedureType.HOTKEY              : self._exec_hotkey,
                ProcedureType.TYPE_TEXT           : self._exec_type_text,
                ProcedureType.VERIFY_ALARM_PANEL_CUSTOM: self._exec_verify_alarm_panel_custom,
                ProcedureType.VERIFY_CUSTOM             : self._exec_verify_custom,
            }
            fn = dispatch.get(proc.proc_type)
            if fn is None:
                raise NotImplementedError(f"No executor for {proc.proc_type}")

            status, verify_results, screenshot = fn(proc, ctx, sampler_ok, log)

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

    # ── Action executors ─────────────────────────────────────────────────────

    def _exec_trigger_alarm(self, proc, ctx, sampler_ok, log):
        if not ctx.pt:
            log("SKIPPED: Standalone run contains no active Modbus/SNMP IO point.")
            return ProcedureStatus.SKIP, [], ""
        try:
            from iscs_Sampler_Anchor import FrameSampler
        except ImportError:
            sampler_ok = False

        # 1. Trigger the alarm FIRST
        self.handler.trigger_alarm(ctx.pt)
        ctx.trigger_time = datetime.datetime.now()
        ctx.trigger_ns   = time.time_ns()
        ctx.trigger_ok   = True
        log(f"Alarm triggered at {ctx.trigger_time.strftime('%H:%M:%S.%f')[:-3]}")

        # 2. Start the frame sampler IMMEDIATELY after trigger
        if sampler_ok and ctx.resolved_bbox:
            dur = float(self.config.get("detection_duration_sec", 8.0))
            ims = int(self.config.get("sampler_interval_ms", 100))
            ctx.sampler = FrameSampler(ctx.resolved_bbox, duration_sec=dur, interval_ms=ims)
            ctx.sampler.start()
            log("FrameSampler started (running concurrently).")

        return ProcedureStatus.PASS, [], ""

    def _exec_reset_alarm(self, proc, ctx, sampler_ok, log):
        if not ctx.pt:
            log("SKIPPED: Standalone run contains no active Modbus/SNMP IO point.")
            return ProcedureStatus.SKIP, [], ""
        try:
            from iscs_Sampler_Anchor import FrameSampler
        except ImportError:
            sampler_ok = False

        # 1. Reset the alarm FIRST
        self.handler.reset_alarm(ctx.pt)
        ctx.reset_ns = time.time_ns()
        ctx.reset_ok = True
        log("Alarm reset.")

        # 2. Start the normalization sampler IMMEDIATELY after reset
        if sampler_ok and ctx.resolved_bbox:
            dur = float(self.config.get("detection_duration_sec", 8.0))
            ims = int(self.config.get("sampler_interval_ms", 100))
            ctx.norm_sampler = FrameSampler(ctx.resolved_bbox, duration_sec=dur, interval_ms=ims)
            ctx.norm_sampler.start()
            log("Normalization sampler started (running concurrently).")

        return ProcedureStatus.PASS, [], ""

    def _exec_navigate_home(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            log("pyautogui not available — navigation skipped.")
            return ProcedureStatus.SKIP, [], ""

        params    = proc.params
        nav_wait  = self.config.get("nav_wait_sec", 1.0)
        hm_x      = params.get("home_x", 0) or ctx.extra.get("home_x", 0)
        hm_y      = params.get("home_y", 0) or ctx.extra.get("home_y", 0)
        if hm_x == 0 and hm_y == 0:
            return ProcedureStatus.SKIP, [], ""

        pyautogui.click(hm_x, hm_y)
        self._sleep(nav_wait)
        log(f"Clicked Home ({hm_x}, {hm_y}).")
        return ProcedureStatus.PASS, [], ""

    def _exec_navigate_alarm_list(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            return ProcedureStatus.SKIP, [], ""

        params   = proc.params
        nav_wait = self.config.get("nav_wait_sec", 1.0)
        hm_x, hm_y = params.get("home_x", 0), params.get("home_y", 0)
        al_x, al_y = params.get("al_x", 0),   params.get("al_y", 0)

        if al_x == 0 and al_y == 0:
            return ProcedureStatus.SKIP, [], ""

        if hm_x or hm_y:
            pyautogui.click(hm_x, hm_y);  self._sleep(nav_wait)
        pyautogui.click(al_x, al_y);      self._sleep(nav_wait)
        log(f"Navigated to Alarm List ({al_x}, {al_y}).")
        return ProcedureStatus.PASS, [], ""

    def _exec_navigate_event_list(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            return ProcedureStatus.SKIP, [], ""

        params   = proc.params
        nav_wait = self.config.get("nav_wait_sec", 1.0)
        hm_x, hm_y = params.get("home_x", 0), params.get("home_y", 0)
        ev_x, ev_y = params.get("ev_x", 0),   params.get("ev_y", 0)

        if ev_x == 0 and ev_y == 0:
            return ProcedureStatus.SKIP, [], ""

        if hm_x or hm_y:
            pyautogui.click(hm_x, hm_y);  self._sleep(nav_wait)
        pyautogui.click(ev_x, ev_y);      self._sleep(nav_wait)
        log(f"Navigated to Event List ({ev_x}, {ev_y}).")
        return ProcedureStatus.PASS, [], ""

    def _exec_navigate_equip_page(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            return ProcedureStatus.SKIP, [], ""

        params   = proc.params
        nav_wait = self.config.get("nav_wait_sec", 1.0)
        hm_x, hm_y = params.get("home_x", 0), params.get("home_y", 0)
        rc_x, rc_y = params.get("rc_x", 0),   params.get("rc_y", 0)
        pg_x, pg_y = params.get("pg_x", 0),   params.get("pg_y", 0)

        if rc_x == 0 or pg_x == 0:
            return ProcedureStatus.SKIP, [], ""

        if hm_x or hm_y:
            pyautogui.click(hm_x, hm_y);       self._sleep(nav_wait)
        click_delay = self.config.get("click_delay", 1.5)
        pyautogui.rightClick(rc_x, rc_y);      self._sleep(click_delay)
        pyautogui.click(pg_x, pg_y);           self._sleep(nav_wait)
        log(f"Navigated to Equipment Page via right-click ({rc_x},{rc_y}) → ({pg_x},{pg_y}).")
        return ProcedureStatus.PASS, [], ""

    # ── Verification executors ────────────────────────────────────────────────

    def _exec_verify_alarm_panel(self, proc, ctx, sampler_ok, log):
        if not ctx.expected_alarm:
            log("SKIPPED: No expected point state loaded for verification.")
            return ProcedureStatus.SKIP, [], ""
        log(f"Checking TRIGGER state (v{ctx.trigger_idx})…")
        results = self.verifier.verify_alarm_panel(
            ctx.expected_alarm, ctx.sc_dir,
            point_idx   = ctx.point_idx,
            trigger_time= ctx.trigger_time,
            file_suffix = "alarm_panel_trigger",
            sampler     = ctx.sampler,
            trigger_ns  = ctx.trigger_ns,
        )
        status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
        ss = next((r.screenshot for r in results if getattr(r, "screenshot", "")), "")
        log(f"→ {status.value}  ({sum(1 for r in results if r.status=='PASS')}/{len(results)} checks passed)")
        return status, results, ss

    def _exec_verify_normalize(self, proc, ctx, sampler_ok, log):
        log(f"Checking NORMALIZE state (v{ctx.reset_idx})…")
        results = self.verifier.verify_alarm_panel(
            ctx.expected_norm, ctx.sc_dir,
            point_idx   = ctx.point_idx,
            trigger_time= None,
            file_suffix = "alarm_panel_normalize",
            sampler     = ctx.norm_sampler,
            trigger_ns  = ctx.reset_ns,
        )
        # Re-tag step names to "normalize/…" (matches existing report field mapping)
        for r in results:
            r.step = r.step.replace("alarm_panel/", "normalize/")

        status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
        log(f"→ {status.value}")
        return status, results, ""

    def _exec_verify_alarm_list(self, proc, ctx, sampler_ok, log):
        al_zone = ctx.zones_dict.get("alarm_list")
        if not al_zone:
            return ProcedureStatus.SKIP, [], ""

        try:
            from iscs_Sampler_Anchor import FrameSampler
            _al_bbox = (al_zone.x1, al_zone.y1, al_zone.x2, al_zone.y2)
            dur = float(self.config.get("sampler_duration_sec", 2.0))
            ims = int(self.config.get("sampler_interval_ms", 100))
            _al_s = FrameSampler(_al_bbox, duration_sec=dur, interval_ms=ims)
            _al_s.start()
            _al_s.join(timeout=dur + 0.5)
            _al_ns = time.time_ns()
        except ImportError:
            _al_s, _al_ns = None, time.time_ns()

        results = self.verifier.verify_list(
            "alarm_list", ctx.expected_alarm, al_zone,
            ctx.sc_dir, point_idx=ctx.point_idx,
            sampler=_al_s, trigger_ns=_al_ns,
        )
        for r in results:
            r.step = r.step.replace("alarm_list/", "alarm_list/trigger/")

        status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
        log(f"→ {status.value}")
        return status, results, ""

    def _exec_verify_event_list(self, proc, ctx, sampler_ok, log):
        ev_zone = ctx.zones_dict.get("event_list")
        if not ev_zone:
            return ProcedureStatus.SKIP, [], ""

        try:
            from iscs_Sampler_Anchor import FrameSampler
            _ev_bbox = (ev_zone.x1, ev_zone.y1, ev_zone.x2, ev_zone.y2)
            dur = float(self.config.get("sampler_duration_sec", 2.0))
            ims = int(self.config.get("sampler_interval_ms", 100))
            _ev_s = FrameSampler(_ev_bbox, duration_sec=dur, interval_ms=ims)
            _ev_s.start()
            _ev_s.join(timeout=dur + 0.5)
            _ev_ns = time.time_ns()
        except ImportError:
            _ev_s, _ev_ns = None, time.time_ns()

        results = self.verifier.verify_list(
            "event_list", ctx.expected_alarm, ev_zone,
            ctx.sc_dir, point_idx=ctx.point_idx,
            sampler=_ev_s, trigger_ns=_ev_ns,
        )
        for r in results:
            r.step = r.step.replace("event_list/", "event_list/trigger/")

        status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
        log(f"→ {status.value}")
        return status, results, ""

    def _exec_verify_equip_page(self, proc, ctx, sampler_ok, log):
        eq_zone = ctx.zones_dict.get("equipment_page")
        if not eq_zone:
            return ProcedureStatus.SKIP, [], ""

        results = self.verifier.verify_inspector(
            ctx.expected_alarm, eq_zone, ctx.sc_dir, point_idx=ctx.point_idx
        )
        for r in results:
            r.step = "equipment/" + r.step

        status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
        log(f"→ {status.value}")
        return status, results, ""

    def _exec_delay(self, proc, ctx, sampler_ok, log):
        delay = float(proc.params.get("delay_sec", 1.0))
        log(f"Waiting {delay:.1f}s…")
        self._sleep(delay)
        return ProcedureStatus.PASS, [], ""

    def _exec_screenshot(self, proc, ctx, sampler_ok, log):
        try:
            from PIL import ImageGrab
            p = proc.params
            x1, y1, x2, y2 = p.get("x1", 0), p.get("y1", 0), p.get("x2", 0), p.get("y2", 0)
            # If all coordinates are 0, grab the whole screen
            _bbox = (x1, y1, x2, y2) if any([x1, y1, x2, y2]) else None
            img = ImageGrab.grab(bbox=_bbox, all_screens=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = ctx.sc_dir / f"{ctx.point_idx:04d}_manual_ss_{ts}.png"
            img.save(str(path))
            log(f"Screenshot saved → {path.name}")
            return ProcedureStatus.PASS, [], str(path)
        except Exception as exc:
            log(f"Screenshot failed: {exc}")
            return ProcedureStatus.FAIL, [], ""

    # ── / Custom executors ───────────────────────────────────────────────

    def _exec_click(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
        x, y = int(proc.params.get("x", 0)), int(proc.params.get("y", 0))
        wait = float(proc.params.get("wait_after", 0.5))
        if x == 0 and y == 0:
            log("Click: no coords."); return ProcedureStatus.SKIP, [], ""
        pyautogui.click(x, y); self._sleep(wait)
        log(f"Clicked ({x}, {y})  wait={wait}s")
        return ProcedureStatus.PASS, [], ""

    def _exec_right_click(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
        x, y = int(proc.params.get("x", 0)), int(proc.params.get("y", 0))
        wait = float(proc.params.get("wait_after", 0.5))
        if x == 0 and y == 0:
            log("Right Click: no coords."); return ProcedureStatus.SKIP, [], ""
        pyautogui.rightClick(x, y); self._sleep(wait)
        log(f"Right-clicked ({x}, {y})  wait={wait}s")
        return ProcedureStatus.PASS, [], ""

    def _exec_hotkey(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
        keys_raw = proc.params.get("keys", "")
        if not keys_raw:
            log("Hotkey: no keys."); return ProcedureStatus.SKIP, [], ""
        wait = float(proc.params.get("wait_after", 0.5))
        keys = [k.strip() for k in str(keys_raw).lower().split("+")]
        pyautogui.hotkey(*keys); self._sleep(wait)
        log(f"Hotkey: {' + '.join(keys)}")
        return ProcedureStatus.PASS, [], ""

    def _exec_type_text(self, proc, ctx, sampler_ok, log):
        try:
            import pyautogui
        except ImportError:
            log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
        text = str(proc.params.get("text", ""))
        x, y = int(proc.params.get("x", 0)), int(proc.params.get("y", 0))
        wait = float(proc.params.get("wait_after", 0.3))
        interval = float(proc.params.get("interval", 0.05))
        if x and y:
            pyautogui.click(x, y); self._sleep(0.2)
        pyautogui.typewrite(text, interval=interval); self._sleep(wait)
        log(f"Typed {len(text)} chars")
        return ProcedureStatus.PASS, [], ""

    def _exec_verify_alarm_panel_custom(self, proc, ctx, sampler_ok, log):
        custom = {}
        for k, pk in [("color","expected_color"),("identifier","expected_identifier"),("severity","expected_severity")]:
            if pk in proc.params:
                custom[k] = proc.params[pk]
        expected = custom if custom else ctx.expected_alarm
        log("Standalone alarm panel check...")
        results = self.verifier.verify_alarm_panel(
            expected, ctx.sc_dir,
            point_idx   = ctx.point_idx,
            trigger_time= None,
            file_suffix = proc.params.get("file_suffix", "alarm_panel_custom"),
            sampler     = None,
            trigger_ns  = None,
        )
        status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
        ss = next((r.screenshot for r in results if getattr(r, "screenshot", "")), "")
        log(f"-> {status.value}  ({sum(1 for r in results if r.status=='PASS')}/{len(results)} checks passed)")
        return status, results, ss

    # ── Asset-bound custom verify step ────────────────────────────────────

    def _exec_verify_custom(self, proc, ctx, sampler_ok, log):
        """
        Execute a VERIFY_CUSTOM step that uses the asset binding system.
        If _ASSETS_OK is False (module not installed), step is skipped.
        If binding is missing, step is skipped with a warning.
        """
        if not _ASSETS_OK or BindingExecutor is None:
            log("SKIPPED: iscs_assets module not available")
            return ProcedureStatus.SKIP, [], ""

        binding_dict = proc.binding
        if not binding_dict:
            log("SKIPPED: step has no binding configured")
            return ProcedureStatus.SKIP, [], ""

        try:
            binding = StepBinding.from_dict(binding_dict)
        except Exception as e:
            log(f"SKIPPED: could not parse binding — {e}")
            return ProcedureStatus.SKIP, [], ""

        log(f"Executing asset binding [{binding.type}] "
            f"asset={binding.asset_id!r} region={binding.region_id!r}")

        executor = BindingExecutor()
        result   = executor.execute(binding)

        status_str = result.get("status", "FAIL")
        msg        = result.get("message", "")
        expected   = result.get("expected", "")
        actual     = result.get("actual", "")
        score      = result.get("score", 0.0)

        log(f"-> {status_str}  {msg}")
        if expected or actual:
            log(f"   expected={expected!r}  actual={actual!r}  score={score:.3f}")

        # Wrap into a VerifyResult-compatible dict for the report
        from types import SimpleNamespace
        vr = SimpleNamespace(
            status     = status_str,
            step       = proc.name,
            message    = msg,
            expected   = expected,
            actual     = actual,
            screenshot = "",
        )

        if status_str == "SKIP" or binding.on_fail == "skip":
            return ProcedureStatus.SKIP, [vr], ""
        if status_str == "PASS":
            return ProcedureStatus.PASS, [vr], ""
        return ProcedureStatus.FAIL, [vr], ""

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


# ═════════════════════════════════════════════════════════════════════════════
#  TKINTER UI — ProcedureFlowDialog
# ═════════════════════════════════════════════════════════════════════════════


_STEP_CATALOGUE = [
    ("Click", "click", "action",
     {"x": 0, "y": 0, "wait_after": 0.5},
     "Click any screen coordinate. Fully independent of IO point."),
    ("Right Click", "right_click", "action",
     {"x": 0, "y": 0, "wait_after": 0.5},
     "Right-click an absolute screen coordinate."),
    ("Hotkey", "hotkey", "action",
     {"keys": "ctrl+f5", "wait_after": 0.5},
     "Press a keyboard shortcut, e.g. ctrl+f5, alt+f4, enter, escape."),
    ("Type Text", "type_text", "action",
     {"text": "", "x": 0, "y": 0, "wait_after": 0.3, "interval": 0.05},
     "Type text. Set x/y to click a field first (0 = skip click)."),
    ("Verify Alarm Panel (standalone)", "verify_alarm_panel_custom", "verification",
     {"file_suffix": "alarm_panel_custom"},
     "Re-check alarm panel anywhere in the flow, independent of Trigger Alarm."),
    ("Verify Custom (asset bound)", "verify_custom", "verification",
     {},
     "Verify a screen region against a text or image asset from the Asset Manager."),
    ("Delay", "delay", "utility",
     {"delay_sec": 1.0},
     "Pause for N seconds."),
    ("Screenshot", "screenshot", "utility",
     {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
     "Capture a screenshot of a specific region. Leave all 0 to capture entire screen."),
]

_PARAM_META = {
    "x":           ("int",   "X coordinate"),
    "y":           ("int",   "Y coordinate"),
    "wait_after":  ("float", "Wait after (sec)"),
    "delay_sec":   ("float", "Delay (sec)"),
    "keys":        ("str",   "Keys (e.g. ctrl+f5)"),
    "text":        ("str",   "Text to type"),
    "interval":    ("float", "Typing interval (sec)"),
    "file_suffix": ("str",   "File suffix"),
    "clicks":      ("json",  "Clicks (JSON list)"),
    "x1":          ("int",   "Left (x1)"),
    "y1":          ("int",   "Top (y1)"),
    "x2":          ("int",   "Right (x2)"),
    "y2":          ("int",   "Bottom (y2)"),
}

_ENT_STYLE = dict(bg="#181818", fg="#eee", font=("Consolas", 10),
                  insertbackground="#eee", relief="flat", bd=6)
_LBL_STYLE = dict(bg="#0f0f0f", fg="#aaa", font=("Consolas", 9), anchor="w")


def _dynamic_catalogue():
    """The Add-Step palette (P4.1): the curated _STEP_CATALOGUE plus any registered
    capability that opts in via meta.addable=True. Capability params_schema becomes
    the field set (rendered generically by _rebuild_params' fallback), so a new
    addable plugin appears in the palette with no edits here.

    Since P6.3 the Procedure model accepts arbitrary string keys (via
    _DynamicProcType), so an addable plugin with a brand-new key appears here and
    can be added, saved, loaded, and executed — no enum entry required."""
    entries = list(_STEP_CATALOGUE)
    if not _CORE_OK or core_registry is None:
        return entries
    have  = {c[1] for c in entries}
    try:
        caps = core_registry.list()
    except Exception:
        return entries
    for cap in caps:
        meta = getattr(cap, "meta", None)
        key  = getattr(cap, "key", None)
        if meta is None or not getattr(meta, "addable", False):
            continue
        if not key or key in have:           # P6.3: no enum-backed filter — any addable plugin
            continue
        entries.append((meta.name, key, meta.category,
                        dict(getattr(meta, "params_schema", {}) or {}),
                        getattr(meta, "description", "")))
        have.add(key)
    return entries


def _dynamic_catalogue():
    """The Add-Step palette (P4.1): the curated _STEP_CATALOGUE plus any registered
    capability that opts in via meta.addable=True. Capability params_schema becomes
    the field set (rendered generically by _rebuild_params' fallback), so a new
    addable plugin appears in the palette with no edits here.

    Since P6.3 the Procedure model accepts arbitrary string keys (via
    _DynamicProcType), so an addable plugin with a brand-new key appears here and
    can be added, saved, loaded, and executed — no enum entry required."""
    entries = list(_STEP_CATALOGUE)
    if not _CORE_OK or core_registry is None:
        return entries
    have  = {c[1] for c in entries}
    try:
        caps = core_registry.list()
    except Exception:
        return entries
    for cap in caps:
        meta = getattr(cap, "meta", None)
        key  = getattr(cap, "key", None)
        if meta is None or not getattr(meta, "addable", False):
            continue
        if not key or key in have:           # P6.3: no enum-backed filter — any addable plugin
            continue
        entries.append((meta.name, key, meta.category,
                        dict(getattr(meta, "params_schema", {}) or {}),
                        getattr(meta, "description", "")))
        have.add(key)
    return entries


# ═════════════════════════════════════════════════════════════════════════════
#  REGION CAPTURE — shared multi-monitor "draw a box on screen" overlay
# ═════════════════════════════════════════════════════════════════════════════

def _detect_monitors():
    """
    Returns a list of monitor-like objects with .x, .y, .width, .height, .name
    Mirrors AddStepDialog._get_monitors but available at module level for
    reuse by RegionPickerFrame and the verify-custom wizard.
    """
    try:
        import __main__
        detect = getattr(__main__, "detect_monitors", None)
        if detect:
            mons = detect()
            if mons:
                return mons
        app = getattr(__main__, "app", None)
        mons = getattr(app, "monitors", None)
        if mons:
            return mons
        mon = getattr(app, "active_mon", None)
        if mon:
            return [mon]
    except Exception:
        pass

    class _M:
        x = 0; y = 0; width = 1920; height = 1080; name = "Primary"
    return [_M()]


def _monitor_index_for_point(monitors, px, py) -> int:
    """Returns the index of the monitor whose bounds contain (px, py), else 0."""
    for i, mon in enumerate(monitors):
        x, y = getattr(mon, "x", 0), getattr(mon, "y", 0)
        w, h = getattr(mon, "width", 1920), getattr(mon, "height", 1080)
        if x <= px < x + w and y <= py < y + h:
            return i
    return 0


def capture_region_overlay(master, tk, on_captured, on_cancel=None):
    """
    Opens a multi-monitor drag-to-select overlay (same visual style as the
    existing 'Draw' bbox picker). On mouse release:
        on_captured(x1, y1, x2, y2, monitor_index, screenshot_image_or_None)
    is called — screenshot_image is a PIL.Image crop of that region
    (or None if Pillow/ImageGrab is unavailable or the grab fails).

    On Escape, on_cancel() is called if provided.
    `master` is withdrawn while the overlay is shown and restored afterward.
    """
    monitors = _detect_monitors()
    master.withdraw()
    overlays = []
    state = {"start": None, "rect": None, "done": False}

    def _cleanup():
        if state["done"]:
            return
        state["done"] = True
        for o in overlays:
            try: o.destroy()
            except Exception: pass
        master.deiconify(); master.lift(); master.focus_force()

    def _press(e, cv, ox, oy):
        state["start"] = (e.x_root, e.y_root)
        if state["rect"]:
            try: cv.delete(state["rect"])
            except Exception: pass
        state["rect"] = None

    def _drag(e, cv, ox, oy):
        if not state["start"]:
            return
        sx, sy = state["start"]
        if state["rect"]:
            try: cv.delete(state["rect"])
            except Exception: pass
        state["rect"] = cv.create_rectangle(
            sx - ox, sy - oy, e.x_root - ox, e.y_root - oy,
            outline="#69ff9a", width=2, fill="#69ff9a", stipple="gray25")

    def _release(e):
        if not state["start"] or state["done"]:
            return
        sx, sy = state["start"]
        x1, y1 = min(sx, e.x_root), min(sy, e.y_root)
        x2, y2 = max(sx, e.x_root), max(sy, e.y_root)
        _cleanup()

        if x2 - x1 < 2 or y2 - y1 < 2:
            return  # ignore accidental zero-size drags

        mon_idx = _monitor_index_for_point(monitors, (x1 + x2) // 2, (y1 + y2) // 2)

        img = None
        if _PIL_OK:
            try:
                img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
            except Exception:
                img = None

        on_captured(int(x1), int(y1), int(x2), int(y2), mon_idx, img)

    for mon in monitors:
        ov = tk.Toplevel(master)
        ov.geometry(f"{mon.width}x{mon.height}+{mon.x}+{mon.y}")
        ov.overrideredirect(True); ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.25); ov.configure(bg="#1a1a2e")
        c = tk.Canvas(ov, bg="#1a1a2e", highlightthickness=0, cursor="crosshair")
        c.pack(fill="both", expand=True)
        c.create_text(mon.width // 2, 28,
            text="✂  Drag to define the region  |  Esc to cancel",
            fill="#ffffff", font=("Consolas", 12, "bold"))
        ox, oy = mon.x, mon.y
        c.bind("<ButtonPress-1>",   lambda e, cv=c, ox=ox, oy=oy: _press(e, cv, ox, oy))
        c.bind("<B1-Motion>",       lambda e, cv=c, ox=ox, oy=oy: _drag(e, cv, ox, oy))
        c.bind("<ButtonRelease-1>", lambda e: _release(e))

        def _esc(e):
            _cleanup()
            if on_cancel:
                on_cancel()
        ov.bind("<Escape>", _esc)
        overlays.append(ov)

    if overlays:
        overlays[0].focus_force()


class RegionPickerFrame:
    """
    Embeddable widget for picking a screen region — either by drawing a new
    box on screen, or selecting a previously-saved named Region from the
    Asset Manager. Shows a live thumbnail preview of whatever the region
    currently contains.

    Attributes (read after on_change fires, or at any time):
        .coords         -> (x1, y1, x2, y2) or None
        .screenshot     -> PIL.Image of the captured region, or None
        .region_id      -> saved Region's id if picked from library, else None
        .monitor_index  -> int

    on_change(picker_instance) is called whenever the selection changes.
    """

    THUMB_MAX_W = 280
    THUMB_MAX_H = 90

    def __init__(self, parent, tk, ttk, on_change=None):
        self.coords        = None
        self.screenshot    = None
        self.region_id     = None
        self.monitor_index = 0
        self._on_change    = on_change
        self._tk           = tk
        self._thumb_img    = None  # keep reference — PhotoImage needs it

        self.frame = tk.Frame(parent, bg="#0f0f0f")
        self._build(tk, ttk)

    def _build(self, tk, ttk):
        bs = dict(font=("Consolas", 9, "bold"), relief="flat", padx=10, pady=5, cursor="hand2")

        self._status_var = tk.StringVar(
            value="No region selected — draw one on screen, or pick a saved region.")
        tk.Label(self.frame, textvariable=self._status_var, bg="#161616", fg="#aaa",
                 font=("Consolas", 9), wraplength=460, anchor="w", justify="left",
                 padx=8, pady=6).pack(fill="x", pady=(0, 6))

        # Thumbnail preview
        self._thumb_label = tk.Label(self.frame, bg="#0a0a0a", fg="#444",
                                      font=("Consolas", 8),
                                      width=int(self.THUMB_MAX_W / 7),
                                      height=int(self.THUMB_MAX_H / 16))
        self._thumb_label.pack(fill="x", pady=(0, 6))
        self._set_thumb_placeholder()

        # Buttons
        bf = tk.Frame(self.frame, bg="#0f0f0f")
        bf.pack(fill="x")
        tk.Button(bf, text="🖌 Draw New Region", bg="#1a3a1a", fg="#69ff9a",
                  command=self._draw_new, **bs).pack(side="left", padx=(0, 6))
        if _ASSETS_OK:
            tk.Button(bf, text="📂 Saved Region", bg="#1a2030", fg="#82b4ff",
                      command=self._pick_saved, **bs).pack(side="left")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set_thumb_placeholder(self, text="(no preview)"):
        self._thumb_img = None
        self._thumb_label.configure(image="", text=text, compound="center")

    def _top(self):
        return self.frame.winfo_toplevel()

    def _capture(self, coords):
        if not _PIL_OK:
            return None
        try:
            x1, y1, x2, y2 = coords
            return ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
        except Exception:
            return None

    def _refresh_display(self):
        if not self.coords:
            self._status_var.set("No region selected — draw one on screen, or pick a saved region.")
            self._set_thumb_placeholder()
            return

        x1, y1, x2, y2 = self.coords
        w, h = x2 - x1, y2 - y1
        if self.region_id and _ASSETS_OK:
            region = AssetManager.instance().get_region(self.region_id)
            label = f"{region.name} ({self.region_id})" if region else self.region_id
            self._status_var.set(f"Saved region: {label}  —  {w}×{h} px  "
                                  f"•  Monitor {self.monitor_index + 1}")
        else:
            self._status_var.set(f"Custom region  —  {w}×{h} px  "
                                  f"•  Monitor {self.monitor_index + 1}")

        if self.screenshot is not None and _PILTK_OK:
            try:
                img = self.screenshot.copy()
                img.thumbnail((self.THUMB_MAX_W, self.THUMB_MAX_H))
                self._thumb_img = ImageTk.PhotoImage(img)
                self._thumb_label.configure(image=self._thumb_img, text="")
            except Exception:
                self._set_thumb_placeholder("(preview unavailable)")
        else:
            self._set_thumb_placeholder(
                "(preview unavailable — Pillow not installed)" if not _PIL_OK else "(no preview)")

    # ── actions ───────────────────────────────────────────────────────────────

    def _draw_new(self):
        capture_region_overlay(self._top(), self._tk, self._on_captured)

    def _on_captured(self, x1, y1, x2, y2, monitor_index, img):
        self.coords        = (x1, y1, x2, y2)
        self.monitor_index = monitor_index
        self.screenshot    = img
        self.region_id     = None
        self._refresh_display()
        if self._on_change:
            self._on_change(self)

    def _pick_saved(self):
        if not _ASSETS_OK:
            return
        dlg = _AssetPickerDialog(self._top(), "region")
        self._top().wait_window(dlg.win)
        if not dlg.result:
            return
        region = AssetManager.instance().get_region(dlg.result)
        if not region:
            return
        self.coords        = region.coords
        self.monitor_index = region.monitor_index
        self.region_id     = region.id
        self.screenshot    = self._capture(self.coords)
        self._refresh_display()
        if self._on_change:
            self._on_change(self)

    def set_region(self, coords, monitor_index=0, region_id=None, capture=True):
        """Programmatically set the region (e.g. when pre-filling for edit)."""
        self.coords        = tuple(coords)
        self.monitor_index = monitor_index
        self.region_id     = region_id
        self.screenshot    = self._capture(self.coords) if capture else None
        self._refresh_display()


class AddStepDialog:
    """
    Modal form for creating a brand-new, independent Procedure step.
    Opened by the '+ Add Step' button in ProcedureFlowDialog.
    self.result holds the new Procedure, or None if cancelled.
    """
    def __init__(self, master, flow, monitor=None, edit_step=None):
        """
        edit_step: if provided, the dialog opens in EDIT mode — pre-filled
        with this Procedure's current type/name/params, and on save mutates
        this same object in place (preserving step_id, enabled, order,
        depends_on, binding). If None, behaves as before (create new).
        """
        try:
            import tkinter as tk
            from tkinter import ttk, messagebox as mb
        except ImportError:
            self.result = None
            self.win    = type("W", (), {"destroy": lambda s: None})()
            return

        self.flow        = flow
        self.monitor     = monitor
        self.result      = None
        self._tk         = tk
        self._mb         = mb
        self._param_vars = {}
        self._edit_step  = edit_step
        self._is_edit    = edit_step is not None
        self._catalogue  = _dynamic_catalogue()    # P4.1: registry-extensible palette
        self._catalogue  = _dynamic_catalogue()    # P4.1: registry-extensible palette

        win = tk.Toplevel(master)
        win.title("Edit Step" if self._is_edit else "Add New Step")
        win.configure(bg="#0f0f0f")
        win.geometry("520x520")
        win.resizable(True, True)
        win.attributes("-topmost", True)
        win.grab_set()
        self.win = win
        self._build(win, tk, ttk)

    def _build(self, win, tk, ttk):
        is_edit = self._is_edit
        # Resolve catalogue entry matching the step being edited (if any)
        edit_entry = None
        if is_edit:
            edit_entry = next((c for c in self._catalogue
            edit_entry = next((c for c in self._catalogue
                               if c[1] == self._edit_step.proc_type.value), None)
        self._type_combo_active = (not is_edit) or (edit_entry is not None)

        if is_edit:
            tk.Label(win, text="✏  EDIT STEP", bg="#0f0f0f",
                     fg="#82b4ff", font=("Consolas", 13, "bold")).pack(
                     anchor="w", padx=14, pady=(10, 4))
        else:
            tk.Label(win, text="+ Add New Step", bg="#0f0f0f",
                     fg="#69ff9a", font=("Consolas", 13, "bold")).pack(
                     anchor="w", padx=14, pady=(10, 4))

        # Type selector — editable for catalogue types, read-only label otherwise
        tk.Label(win, text="Step Type", **_LBL_STYLE).pack(fill="x", padx=14)
        if self._type_combo_active:
            initial_entry = edit_entry if is_edit else self._catalogue[0]
            initial_entry = edit_entry if is_edit else self._catalogue[0]
            self._type_var = tk.StringVar(value=initial_entry[0])
            cb = ttk.Combobox(win, textvariable=self._type_var, state="readonly",
                               values=[c[0] for c in self._catalogue],
                               values=[c[0] for c in self._catalogue],
                               font=("Consolas", 10))
            cb.pack(fill="x", padx=14, pady=(0, 4))
            cb.bind("<<ComboboxSelected>>", self._on_type_change)
        else:
            type_label = self._edit_step.proc_type.value.replace("_", " ").title()
            tk.Label(win, text=type_label, bg="#181818", fg="#888",
                     font=("Consolas", 10), anchor="w", padx=8, pady=6,
                     relief="flat").pack(fill="x", padx=14, pady=(0, 4))

        # Description
        if is_edit:
            desc_text = self._edit_step.description or (edit_entry[4] if edit_entry else "")
            if not self._type_combo_active:
                desc_text = (desc_text + "\n\n" if desc_text else "") + \
                    "(This step's type is set automatically and can't be changed here.)"
        else:
            desc_text = self._catalogue[0][4]
            desc_text = self._catalogue[0][4]
        self._desc_var = tk.StringVar(value=desc_text)
        tk.Label(win, textvariable=self._desc_var, bg="#161616", fg="#555",
                 font=("Consolas", 8), wraplength=460, anchor="w",
                 justify="left", padx=8, pady=4).pack(fill="x", padx=14, pady=(0, 6))

        # Name
        tk.Label(win, text="Step Name  (unique in this flow)", **_LBL_STYLE).pack(fill="x", padx=14)
        name_initial = self._edit_step.name if is_edit else self._catalogue[0][0]
        name_initial = self._edit_step.name if is_edit else self._catalogue[0][0]
        self._name_var = tk.StringVar(value=name_initial)
        tk.Entry(win, textvariable=self._name_var, **_ENT_STYLE).pack(
                 fill="x", padx=14, pady=(0, 8))

        # Params
        self._pframe = tk.Frame(win, bg="#0f0f0f")
        self._pframe.pack(fill="both", expand=True, padx=14)
        if is_edit:
            if edit_entry is not None:
                # Catalogue type — use catalogue's param shape, overlay current values
                _, _, _, defaults, _ = edit_entry
                params_dict = {k: self._edit_step.params.get(k, v) for k, v in defaults.items()}
            else:
                # Non-catalogue (auto-generated) — show whatever params exist as-is
                params_dict = dict(self._edit_step.params)
            self._rebuild_params(params_dict, tk)
        else:
            self._rebuild_params(self._catalogue[0][3], tk)
            self._rebuild_params(self._catalogue[0][3], tk)

        # Buttons
        bf = tk.Frame(win, bg="#0f0f0f")
        bf.pack(fill="x", padx=14, pady=10)
        bs = dict(font=("Consolas", 9, "bold"), relief="flat", padx=12, pady=5)
        if is_edit:
            tk.Button(bf, text="💾 Save Changes", bg="#1a2a3a", fg="#82b4ff",
                      command=self._on_add, **bs).pack(side="left", padx=2)
        else:
            tk.Button(bf, text="+ Add to Flow", bg="#1a3a1a", fg="#69ff9a",
                      command=self._on_add, **bs).pack(side="left", padx=2)
        tk.Button(bf, text="Cancel", bg="#222", fg="#aaa",
                  command=win.destroy, **bs).pack(side="left", padx=2)

    def _rebuild_params(self, params_dict, tk):
        """
        params_dict: plain {key: value} dict defining both which fields to
        show AND their initial values. For Add mode this is a catalogue
        entry's defaults; for Edit mode it's the step's current values
        (optionally shaped by the catalogue's key set).
        """
        for w in self._pframe.winfo_children():
            w.destroy()
        self._param_vars = {}
        import json as _j
        keys      = list(params_dict.keys())
        has_xy    = "x" in keys and "y" in keys
        has_bbox  = all(k in keys for k in ("x1","y1","x2","y2"))
        bbox_done = False
        for key, default in params_dict.items():
            meta = _PARAM_META.get(key, ("str", key.replace("_", " ").title()))
            wt, label = meta
            row = tk.Frame(self._pframe, bg="#0f0f0f")
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, width=24, **_LBL_STYLE).pack(side="left")
            val = _j.dumps(default) if wt == "json" else str(default)
            var = tk.StringVar(value=val)
            self._param_vars[key] = (var, wt)
            tk.Entry(row, textvariable=var, **_ENT_STYLE).pack(
                     side="left", fill="x", expand=True, padx=(0, 4))
            # Pick button on X and Y rows
            if key in ("x", "y") and has_xy:
                tk.Button(row, text="Pick",
                          bg="#2a1f3a", fg="#c084fc",
                          font=("Consolas", 8, "bold"), relief="flat",
                          padx=6, pady=3, cursor="hand2",
                          command=self._pick_xy).pack(side="left")
            # Draw button on first bbox row only
            elif key in ("x1","y1","x2","y2") and has_bbox and not bbox_done:
                bbox_done = True
                tk.Button(row, text="Draw",
                          bg="#1a2a3a", fg="#60a5fa",
                          font=("Consolas", 8, "bold"), relief="flat",
                          padx=6, pady=3, cursor="hand2",
                          command=self._draw_bbox).pack(side="left")
            # Hotkey dictionary info guide helper
            elif key == "keys":
                tk.Button(row, text="📖 Keys Info",
                          bg="#1e2a3a", fg="#60a5fa",
                          font=("Consolas", 8, "bold"), relief="flat",
                          padx=6, pady=3, cursor="hand2",
                          command=self._show_keys_info).pack(side="left")
    def _get_monitors(self):
        try:
            import __main__
            detect = getattr(__main__, "detect_monitors", None)
            if detect:
                return detect()
            mon = getattr(getattr(__main__, "app", None), "active_mon", None)
            if mon:
                return [mon]
        except Exception:
            pass
        class _M:
            x=0; y=0; width=1920; height=1080; name="Primary"
        return [_M()]

    def _pick_xy(self):
        import tkinter as tk
        monitors = self._get_monitors()
        try:
            import __main__
            mon = getattr(getattr(__main__, "app", None), "active_mon", monitors[0])
        except Exception:
            mon = monitors[0]
        self.win.withdraw()
        def on_picked(x, y):
            self.win.deiconify(); self.win.lift(); self.win.focus_force()
            if "x" in self._param_vars: self._param_vars["x"][0].set(str(int(x)))
            if "y" in self._param_vars: self._param_vars["y"][0].set(str(int(y)))
        try:
            import __main__
            CPO = getattr(__main__, "CoordinatePickOverlay", None)
            if CPO:
                CPO(self.win, mon, on_picked); return
        except Exception:
            pass
        # Fallback — exact replica of CoordinatePickOverlay
        ov = tk.Toplevel(self.win)
        ov.geometry(f"{mon.width}x{mon.height}+{mon.x}+{mon.y}")
        ov.overrideredirect(True); ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.15); ov.configure(bg="#AA00FF")
        c = tk.Canvas(ov, bg="#AA00FF", highlightthickness=0, cursor="target")
        c.pack(fill="both", expand=True)
        c.create_text(mon.width//2, 50,
            text="\U0001f3af CLICK ANYWHERE TO CAPTURE COORDINATE  |  Esc to cancel",
            fill="#ffffff", font=("Consolas", 14, "bold"))
        def _click(e):
            ov.destroy(); on_picked(e.x_root, e.y_root)
        def _cancel(e):
            ov.destroy(); self.win.deiconify(); self.win.lift()
        c.bind("<Button-1>", _click); ov.bind("<Escape>", _cancel)
        ov.focus_force()

    def _draw_bbox(self):
        import tkinter as tk
        monitors = self._get_monitors()
        self.win.withdraw()
        overlays = []
        state = {"start": None, "rect": None, "canvas": None, "done": False}

        def _cleanup():
            if state["done"]: return
            state["done"] = True
            for o in overlays:
                try: o.destroy()
                except Exception: pass
            self.win.deiconify(); self.win.lift(); self.win.focus_force()

        def _press(e, cv, ox, oy):
            state["start"] = (e.x_root, e.y_root); state["canvas"] = cv
            if state["rect"]:
                try: cv.delete(state["rect"])
                except Exception: pass
            state["rect"] = None

        def _drag(e, cv, ox, oy):
            if not state["start"]: return
            sx, sy = state["start"]
            if state["rect"]:
                try: cv.delete(state["rect"])
                except Exception: pass
            state["rect"] = cv.create_rectangle(
                sx-ox, sy-oy, e.x_root-ox, e.y_root-oy,
                outline="#60a5fa", width=2, fill="#60a5fa", stipple="gray25")

        def _release(e):
            if not state["start"] or state["done"]: return
            sx, sy = state["start"]
            x1,y1 = min(sx,e.x_root), min(sy,e.y_root)
            x2,y2 = max(sx,e.x_root), max(sy,e.y_root)
            _cleanup()
            for k,v in [("x1",x1),("y1",y1),("x2",x2),("y2",y2)]:
                if k in self._param_vars: self._param_vars[k][0].set(str(int(v)))

        for mon in monitors:
            ov = tk.Toplevel(self.win)
            ov.geometry(f"{mon.width}x{mon.height}+{mon.x}+{mon.y}")
            ov.overrideredirect(True); ov.attributes("-topmost", True)
            ov.attributes("-alpha", 0.25); ov.configure(bg="#1a1a2e")
            c = tk.Canvas(ov, bg="#1a1a2e", highlightthickness=0, cursor="crosshair")
            c.pack(fill="both", expand=True)
            c.create_text(mon.width//2, 28,
                text="\u2702  Drag to define screenshot region  |  Esc to cancel",
                fill="#ffffff", font=("Consolas", 12, "bold"))
            ox, oy = mon.x, mon.y
            c.bind("<ButtonPress-1>",   lambda e,cv=c,ox=ox,oy=oy: _press(e,cv,ox,oy))
            c.bind("<B1-Motion>",       lambda e,cv=c,ox=ox,oy=oy: _drag(e,cv,ox,oy))
            c.bind("<ButtonRelease-1>", lambda e: _release(e))
            ov.bind("<Escape>",         lambda e: _cleanup())
            overlays.append(ov)

        if overlays: overlays[0].focus_force()

    def _on_type_change(self, _=None):
        entry = next((c for c in self._catalogue if c[0] == self._type_var.get()),
                     self._catalogue[0])
        entry = next((c for c in self._catalogue if c[0] == self._type_var.get()),
                     self._catalogue[0])
        self._desc_var.set(entry[4])
        if not self._is_edit:
            # Only auto-fill the name in Add mode — don't clobber a
            # user's existing step name while they're browsing types in Edit mode
            self._name_var.set(entry[0])
        try:
            import tkinter as tk
            # Switching type means a fresh param shape — no overlay
            self._rebuild_params(entry[3], tk)
        except Exception:
            pass

    def _on_add(self):
        import json as _j
        action_label = "Edit Step" if self._is_edit else "Add Step"
        name = self._name_var.get().strip()
        if not name:
            self._mb.showerror(action_label, "Step name cannot be empty.", parent=self.win)
            return
        existing = self.flow.get(name)
        if existing is not None and existing is not self._edit_step:
            self._mb.showerror(action_label,
                               "That name already exists. Choose a different name.",
                               parent=self.win)
            return

        # Resolve type/category/description
        if self._type_combo_active:
            entry = next((c for c in self._catalogue if c[0] == self._type_var.get()),
                         self._catalogue[0])
            entry = next((c for c in self._catalogue if c[0] == self._type_var.get()),
                         self._catalogue[0])
            _, type_str, cat_str, _, description = entry
            proc_type = _resolve_proc_type(type_str)   # P6.3: enum or dynamic key
            proc_type = _resolve_proc_type(type_str)   # P6.3: enum or dynamic key
            category  = ProcedureCategory(cat_str)
        else:
            # Non-catalogue auto-generated step being edited — type/category/description unchanged
            proc_type   = self._edit_step.proc_type
            category    = self._edit_step.category
            description = self._edit_step.description

        # Parse params
        params = {}
        for key, (var, wt) in self._param_vars.items():
            raw = var.get().strip()
            try:
                if   wt == "int":   params[key] = int(raw)
                elif wt == "float": params[key] = float(raw)
                elif wt == "json":  params[key] = _j.loads(raw)
                else:               params[key] = raw
            except (ValueError, _j.JSONDecodeError) as exc:
                self._mb.showerror(action_label,
                                   "Invalid value for " + repr(key) + ": " + str(exc),
                                   parent=self.win)
                return

        if self._is_edit:
            # Mutate the existing Procedure in place — preserves step_id,
            # enabled, order, depends_on, binding automatically
            self._edit_step.proc_type   = proc_type
            self._edit_step.category    = category
            self._edit_step.name        = name
            self._edit_step.params      = params
            self._edit_step.description = description
            self.result = self._edit_step
        else:
            self.result = Procedure(
                proc_type   = proc_type,
                category    = category,
                name        = name,
                enabled     = True,
                order       = 0,
                params      = params,
                description = description,
                depends_on  = [],
            )
        self.win.destroy()

    def _show_keys_info(self):
        """Displays a dedicated guide window listing standard PyAutoGUI key formats and validation rules."""
        import tkinter as tk
        guide = tk.Toplevel(self.win)
        guide.title("Hotkey Reference Guide")
        guide.configure(bg="#0f0f0f")
        guide.geometry("500x480")
        guide.resizable(False, False)
        guide.attributes("-topmost", True)
        guide.grab_set()

        tk.Label(guide, text="📖 Keyboard Key Format Guide", bg="#0f0f0f", fg="#60a5fa",
                 font=("Consolas", 11, "bold")).pack(anchor="w", padx=14, pady=10)

        txt = tk.Text(guide, bg="#111", fg="#ddd", font=("Consolas", 9), relief="flat", wrap="word")
        txt.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        info_text = (
            "PyAutoGUI Keyboard Key Reference Map\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Separate multiple keys with a '+' sign (e.g., ctrl+shift+r).\n"
            "Spaces around the '+' sign are automatically trimmed.\n\n"
            "Common Modifiers:\n"
            "  ctrl, shift, alt, win, command, option\n\n"
            "Navigation & Control Keys:\n"
            "  enter, tab, space, backspace, escape, delete, insert,\n"
            "  home, end, pageup, pagedown, up, down, left, right\n\n"
            "Function Keys:\n"
            "  f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12\n\n"
            "Numpad & System Locks:\n"
            "  num0, num1, num2, capslock, numlock, scrolllock\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Validation Examples\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✓ CORRECT USAGES:\n"
            "  • ctrl+alt+delete     (Valid multi-modifier chain)\n"
            "  • ctrl+shift+r        (Valid refresh shortcut)\n"
            "  • ctrl+plus           (Use 'plus' to trigger the '+' key safely)\n"
            "  • f5                  (Valid single-key trigger)\n"
            "  • enter               (Valid standard confirmation key)\n\n"
            "✗ INCORRECT USAGES:\n"
            "  • control+shift+r     (WRONG: PyAutoGUI uses 'ctrl', not 'control')\n"
            "  • ctrl+shift++        (WRONG: Use '+' strictly as an event connector)\n"
            "  • shft+alt+p          (WRONG: Use 'shift', not 'shft')\n"
            "  • ctrl+c+v            (WRONG: Cannot click two distinct letters simultaneously)\n"
        )

        txt.insert("1.0", info_text)
        txt.configure(state="disabled")

        tk.Button(guide, text="Close Guide", bg="#222", fg="#aaa", font=("Consolas", 9, "bold"),
                  relief="flat", padx=12, pady=5, cursor="hand2", command=guide.destroy).pack(pady=(0, 12))


def open_procedure_flow_dialog(master, flow, title="Execution Flow", monitor=None):
    """Opens the ProcedureFlowDialog window."""
    ProcedureFlowDialog(master, flow, title=title, monitor=monitor)


class ProcedureFlowDialog:
    """
    Flow editor with IO-grouped tree, toolbar, multi-select, search,
    Apply-to-All, Asset Manager, and Save-as-Template.

    Two modes:
      IO-grouped : flow.has_io_groups() == True  -> IO folders as tree parents
      Flat       : legacy flat step list
    """

    CATEGORY_COLORS = {
        ProcedureCategory.ACTION       : ("#2979FF", "⚡"),
        ProcedureCategory.VERIFICATION : ("#00C853", "🔍"),
        ProcedureCategory.UTILITY      : ("#FFD600", "🔧"),
    }

    def __init__(self, master, flow, title="Execution Flow", monitor=None):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            return

        self.flow     = flow
        self._tk      = tk
        self._monitor = monitor
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_tree())

        win = tk.Toplevel(master)
        win.title(f"⚙  {title}  —  Execution Flow")
        win.configure(bg="#0f0f0f")
        win.geometry("800x700")
        win.minsize(700, 580)
        win.resizable(True, True)
        win.attributes("-topmost", True)
        win.grab_set()
        self.win = win
        self._build(win, tk, ttk)
        self._refresh_tree()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self, win, tk, ttk):
        BG  = "#0f0f0f"
        BG2 = "#161616"
        bs  = dict(font=("Consolas", 9, "bold"), relief="flat", padx=8, pady=4, cursor="hand2")

        # Header
        hdr = tk.Frame(win, bg=BG)
        hdr.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(hdr, text="⚙  EXECUTION FLOW", bg=BG, fg="#fff",
                 font=("Consolas", 12, "bold")).pack(side="left")
        for cat, (color, icon) in self.CATEGORY_COLORS.items():
            lbl = cat.value.title() if hasattr(cat, "value") else str(cat).title()
            tk.Label(hdr, text=f"{icon} {lbl}", bg=BG, fg=color,
                     font=("Consolas", 8)).pack(side="right", padx=6)

        # Toolbar — two rows so the window never has to be widened to reach
        # Save & Close / Cancel. Row 1 = primary step actions + Save/Cancel
        # (right-anchored, always visible). Row 2 = library actions.
        tb = tk.Frame(win, bg=BG2, pady=5, padx=10)
        tb.pack(fill="x", padx=14, pady=(0, 4))

        tb1 = tk.Frame(tb, bg=BG2)
        tb1.pack(fill="x")
        tk.Button(tb1, text="+ Add",       bg="#1a3a1a", fg="#69ff9a", command=self._add_step,      **bs).pack(side="left", padx=2)
        tk.Button(tb1, text="✏ Edit",      bg="#1a2030", fg="#82b4ff", command=self._edit_step,     **bs).pack(side="left", padx=2)
        tk.Button(tb1, text="⧉ Duplicate", bg="#1a1f2e", fg="#a0a8c0", command=self._duplicate,     **bs).pack(side="left", padx=2)
        tk.Button(tb1, text="🗑 Delete",    bg="#2a1515", fg="#ff6b6b", command=self._delete,        **bs).pack(side="left", padx=2)
        tk.Frame(tb1, bg="#333", width=1).pack(side="left", fill="y", padx=6, pady=2)
        tk.Button(tb1, text="▲ Up",        bg="#222",    fg="#ccc",    command=self._move_up,       **bs).pack(side="left", padx=2)
        tk.Button(tb1, text="▼ Down",      bg="#222",    fg="#ccc",    command=self._move_down,     **bs).pack(side="left", padx=2)

        tb2 = tk.Frame(tb, bg=BG2)
        tb2.pack(fill="x", pady=(4, 0))
        tk.Button(tb2, text="📁 Assets",      bg="#2a1f0a", fg="#f9c74f", command=self._open_assets,   **bs).pack(side="left", padx=2)
        tk.Button(tb2, text="🎴 Checks",      bg="#1a2a30", fg="#90e0ef", command=self._open_check_gallery, **bs).pack(side="left", padx=2)
        tk.Button(tb2, text="💾 Save Template",bg="#1a2a2a", fg="#90e0ef", command=self._save_template, **bs).pack(side="left", padx=2)
        tk.Button(tb2, text="📂 Load Template",bg="#1a2030", fg="#82b4ff", command=self._load_template, **bs).pack(side="left", padx=2)
        # Search
        sf = tk.Frame(win, bg=BG)
        sf.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(sf, text="🔍", bg=BG, fg="#555", font=("Consolas", 11)).pack(side="left")
        tk.Entry(sf, textvariable=self._search_var, bg="#181818", fg="#eee",
                 font=("Consolas", 10), insertbackground="#eee",
                 relief="flat", bd=6).pack(side="left", fill="x", expand=True)
        tk.Button(sf, text="✕", bg=BG, fg="#555", relief="flat",
                  font=("Consolas", 9), cursor="hand2",
                  command=lambda: self._search_var.set("")).pack(side="left")

        # Tree
        tf = tk.Frame(win, bg=BG)
        tf.pack(fill="both", expand=True, padx=14)
        cols = ("name", "type", "value", "status")
        style = ttk.Style(win)
        style.theme_use("default")
        style.configure("Flow.Treeview", background="#111", foreground="#ccc",
                         fieldbackground="#111", rowheight=24, font=("Consolas", 10))
        style.configure("Flow.Treeview.Heading", background="#222", foreground="#89b4fa",
                         font=("Consolas", 9, "bold"))
        style.map("Flow.Treeview",
                  background=[("selected", "#2979FF")], foreground=[("selected", "#fff")])
        self.tree = ttk.Treeview(tf, columns=cols, show="tree headings",
                                  selectmode="extended", style="Flow.Treeview")
        vsb = tk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.heading("#0",       text="⊟",          anchor="center")
        self.tree.heading("name",     text="Step Name",  anchor="w")
        self.tree.heading("type",     text="Type",       anchor="w")
        self.tree.heading("value",    text="Value",      anchor="w")
        self.tree.heading("status",   text="State",      anchor="center")
        self.tree.column("#0",        width=32, stretch=False, anchor="center")
        self.tree.column("name",      width=220, stretch=True,  anchor="w")
        self.tree.column("type",      width=150, stretch=False, anchor="w")
        self.tree.column("value",     width=170, stretch=True,  anchor="w")
        self.tree.column("status",    width=54,  stretch=False, anchor="center")
        self.tree.heading("#0", command=self._toggle_collapse_all)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>",         self._on_right_click)
        self.tree.bind("<Button-1>",         self._on_tree_click)
        self.tree.bind("<Double-1>",         self._on_tree_double_click)

        # Footer bar (very bottom) — primary window actions, modern OK/Cancel
        # placement at bottom-right. Packed before the description bar so it
        # anchors to the absolute bottom of the window.
        footer = tk.Frame(win, bg=BG)
        footer.pack(fill="x", padx=14, pady=(0, 10), side="bottom")
        tk.Button(footer, text="Save & Close", bg="#2979FF", fg="#fff",
                  command=self._save_close, **bs).pack(side="right", padx=2)
        tk.Button(footer, text="Cancel", bg="#222", fg="#aaa",
                  command=win.destroy, **bs).pack(side="right", padx=2)

        # Description bar (bottom)
        desc_f = tk.Frame(win, bg=BG2, pady=6, padx=10)
        desc_f.pack(fill="x", padx=14, pady=(4, 6), side="bottom")
        tk.Label(desc_f, text="Description:", bg=BG2, fg="#555",
                 font=("Consolas", 8)).pack(anchor="w")
        self.lbl_desc = tk.Label(desc_f, text="Select a step or IO folder.",
                                  bg=BG2, fg="#777", font=("Consolas", 9),
                                  wraplength=720, anchor="w", justify="left")
        self.lbl_desc.pack(anchor="w")

        # Empty state
        self._empty_lbl = tk.Label(tf,
            text=("No steps yet.\nClick  + Add  to add a step,\n"
                  "or configure zones and IO list for auto-population."),
            bg="#111", fg="#444", font=("Consolas", 10), justify="center")

        # Right-click menu
        self._ctx = tk.Menu(win, tearoff=0, bg="#1e1e2e", fg="#cdd6f4",
                             activebackground="#2979FF", activeforeground="#fff",
                             font=("Consolas", 9))

    # ── tree ──────────────────────────────────────────────────────────────────

    def _refresh_tree(self):
        q         = self._search_var.get().strip().lower()
        sel_before = set(self.tree.selection())
        # Remember each folder's CURRENT open/closed state (keyed by stable iid)
        # so a refresh triggered by reorder/edit/enable/etc. preserves exactly
        # what the user had expanded — instead of forcing one global state.
        prev_open = {}
        for iid in self.tree.get_children(""):
            if iid.startswith("io::"):
                prev_open[iid] = bool(self.tree.item(iid, "open"))
        self.tree.delete(*self.tree.get_children())
        has_io      = self.flow.has_io_groups()
        has_content = has_io or bool(self.flow.procedures)

        if not has_content:
            self._empty_lbl.place(relx=0.5, rely=0.5, anchor="center")
            return
        self._empty_lbl.place_forget()

        # IO-grouped mode
        if has_io:
            for group in self.flow.io_groups:
                vis = [s for s in group.ordered_steps
                       if not q or q in s.name.lower()
                       or q in group.point_id.lower() or q in group.label.lower()]
                if q and not vis:
                    continue
                folder_iid = f"io::{group.io_id}"
                cnt = f"{len(group.steps)} steps"
                lbl = (f"📋  {group.point_id}  —  {group.label}"
                       if group.label else f"📋  {group.point_id}")
                # Restore this folder's prior open-state. New folders (not seen
                # before) fall back to the global collapse preference / expanded.
                is_open = prev_open.get(
                    folder_iid, not getattr(self, "_folders_collapsed", False))
                self.tree.insert("", "end", iid=folder_iid, text="",
                                  values=(lbl, "IO Group", "", cnt),
                                  tags=("io_group",),
                                  open=is_open)
                for idx, s in enumerate(vis, 1):
                    self._ins_step(folder_iid, s, idx)
        else:
            vis = [p for p in self.flow.procedures
                   if not q or q in p.name.lower()]
            for idx, proc in enumerate(vis, 1):
                self._ins_step("", proc, idx)

        # Tags
        self.tree.tag_configure("io_group", foreground="#89b4fa", background="#151525",
                                 font=("Consolas", 10, "bold"))
        for cat, (color, _) in self.CATEGORY_COLORS.items():
            self.tree.tag_configure(cat.value, foreground=color, background="#111",
                                     font=("Consolas", 10))
        self.tree.tag_configure("disabled", foreground="#444", background="#0d0d0d",
                                 font=("Consolas", 10, "italic"))
        self.tree.tag_configure("has_binding", foreground="#f9c74f", background="#111",
                                 font=("Consolas", 10))
        for iid in sel_before:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

    def _ins_step(self, parent, step, idx):
        icon = self.CATEGORY_COLORS.get(step.category, ("#888", "•"))[1]
        name_disp = f"{icon} {step.name}" + (" ★" if step.binding else "")
        iid = f"step::{step.step_id or step.name}::{parent}"
        tag = ("disabled",) if not step.enabled else               ("has_binding",) if step.binding else               (step.category.value,)
        self.tree.insert(parent, "end", iid=iid, text="",
                          values=(name_disp,
                                  step.proc_type.value.replace("_", " ").title(),
                                  self._step_value_summary(step),
                                  "✓" if step.enabled else "✗"),
                          tags=tag)

    @staticmethod
    def _step_value_summary(step) -> str:
        """Human-readable summary of a step's key parameter for the Value column."""
        p  = step.params or {}
        pt = step.proc_type.value
        try:
            if pt in ("click", "right_click"):
                return f"({p.get('x', 0)}, {p.get('y', 0)})"
            if pt == "type_text":
                txt = str(p.get("text", ""))
                return f'"{txt[:24]}\u2026"' if len(txt) > 24 else (f'"{txt}"' if txt else "\u2014")
            if pt == "hotkey":
                return str(p.get("keys", "")) or "\u2014"
            if pt == "delay":
                return f"{p.get('delay_sec', 0)} sec"
            if pt == "screenshot":
                x1, y1, x2, y2 = (p.get("x1", 0), p.get("y1", 0),
                                  p.get("x2", 0), p.get("y2", 0))
                if (x1, y1, x2, y2) == (0, 0, 0, 0):
                    return "full screen"
                return f"({x1},{y1})\u2192({x2},{y2})"
            if pt == "verify_custom" and step.binding:
                bt = step.binding.get("type", "")
                return f"{bt.lower()} check" if bt else "\u2014"
        except Exception:
            pass
        return "\u2014"

    # ── selection helpers ─────────────────────────────────────────────────────

    def _sel_iids(self):
        return list(self.tree.selection())

    def _find_step(self, iid):
        if not iid.startswith("step::"): return None
        parts = iid.split("::")
        key   = parts[1] if len(parts) > 1 else ""
        # parent reference itself contains "::" (e.g. "io::IO_0001"),
        # so it must be rejoined from all remaining parts, not parts[2] alone
        par   = "::".join(parts[2:]) if len(parts) > 2 else ""
        if par.startswith("io::"):
            g = self.flow.get_io_group(par[4:])
            if g:
                return next((s for s in g.steps
                             if (s.step_id and s.step_id == key) or s.name == key), None)
        # FIX: Look up flat/global procedures by both unique step_id and name
        return next((p for p in self.flow.procedures 
                     if (p.step_id and p.step_id == key) or p.name == key), None)

    def _find_group(self, step_iid):
        parts = step_iid.split("::")
        par   = "::".join(parts[2:]) if len(parts) > 2 else ""
        if par.startswith("io::"):
            return self.flow.get_io_group(par[4:])
        return None

    def _on_select(self, _=None):
        iids = self._sel_iids()
        if not iids: return
        iid = iids[-1]
        if iid.startswith("io::"):
            g = self.flow.get_io_group(iid[4:])
            if g:
                self.lbl_desc.config(
                    text=f"IO: {g.point_id}  —  {g.label}  "
                         f"({len(g.steps)} steps, {sum(1 for s in g.steps if s.enabled)} enabled)",
                    fg="#89b4fa")
        elif iid.startswith("step::"):
            s = self._find_step(iid)
            if s:
                bind = (f"  |  Binding: {s.binding.get('type','?')}"
                        f" asset={s.binding.get('asset_id','?')}" if s.binding else "")
                self.lbl_desc.config(
                    text=f"{s.description or 'No description.'}  |  "
                         f"{'ENABLED' if s.enabled else 'DISABLED'}  "
                         f"|  Depends on: {', '.join(s.depends_on) or 'none'}{bind}",
                    fg="#aaa" if s.enabled else "#555")

    # ── tree click handlers ────────────────────────────────────────────────────

    def _on_tree_click(self, event):
        """Single click: toggle enable/disable ONLY when the click lands squarely
        in the State column on a step row (mitigation against accidental toggles
        during ordinary row selection)."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)   # e.g. "#4"
        # status is the 4th data column -> "#4"
        if col != "#4":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or not iid.startswith("step::"):
            return
        s = self._find_step(iid)
        if not s:
            return
        s.enabled = not s.enabled
        self._refresh_tree()
        self.tree.selection_set(iid)
        self._toast("Enabled" if s.enabled else "Disabled",
                    event.x_root, event.y_root,
                    color="#69ff9a" if s.enabled else "#ff6b6b")

    def _on_tree_double_click(self, event):
        """Double click a step row -> open the Edit dialog (quick value tweaks)."""
        if self.tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            return
        iid = self.tree.identify_row(event.y)
        if not iid or not iid.startswith("step::"):
            return
        self.tree.selection_set(iid)
        self._edit_step()
        return "break"

    def _toast(self, text, x_root, y_root, color="#69ff9a", ms=1100):
        """Tiny auto-dismissing popup shown near the cursor."""
        tk = self._tk
        try:
            tip = tk.Toplevel(self.win)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            try: tip.attributes("-alpha", 0.95)
            except Exception: pass
            tk.Label(tip, text=text, bg="#1e1e2e", fg=color,
                     font=("Consolas", 9, "bold"), padx=10, pady=4,
                     relief="solid", bd=1).pack()
            tip.update_idletasks()
            tip.geometry(f"+{x_root + 14}+{y_root + 10}")
            tip.after(ms, tip.destroy)
        except Exception:
            pass

    # ── toolbar actions ───────────────────────────────────────────────────────

    def _toggle_collapse_all(self):
        """Collapse or expand every IO folder at once. Triggered by clicking the
        ⊟/⊞ glyph in the leftmost (#0) column heading."""
        folders = [iid for iid in self.tree.get_children("") if iid.startswith("io::")]
        if not folders:
            return
        any_open = any(self.tree.item(f, "open") for f in folders)
        new_open = not any_open
        for f in folders:
            self.tree.item(f, open=new_open)
        self._folders_collapsed = not new_open
        # Heading glyph reflects the action available on the NEXT click
        self.tree.heading("#0", text="⊟" if new_open else "⊞")

    def _move_up(self):
        iids = self._sel_iids()
        if not iids or not iids[0].startswith("step::"): return
        s = self._find_step(iids[0]); g = self._find_group(iids[0])
        if g:
            steps = g.ordered_steps
            idx = next((i for i, x in enumerate(steps) if x is s), None)
            if idx is not None and idx > 0:
                steps[idx].order, steps[idx-1].order = steps[idx-1].order, steps[idx].order
        elif s: self.flow.move_up(s.name)
        self._refresh_tree()

    def _move_down(self):
        iids = self._sel_iids()
        if not iids or not iids[0].startswith("step::"): return
        s = self._find_step(iids[0]); g = self._find_group(iids[0])
        if g:
            steps = g.ordered_steps
            idx = next((i for i, x in enumerate(steps) if x is s), None)
            if idx is not None and idx < len(steps)-1:
                steps[idx].order, steps[idx+1].order = steps[idx+1].order, steps[idx].order
        elif s: self.flow.move_down(s.name)
        self._refresh_tree()

    def _enable(self):
        for iid in self._sel_iids():
            s = self._find_step(iid)
            if s: s.enabled = True
            elif iid.startswith("io::"):
                g = self.flow.get_io_group(iid[4:])
                if g:
                    for st in g.steps: st.enabled = True
        self._refresh_tree()

    def _disable(self):
        for iid in self._sel_iids():
            s = self._find_step(iid)
            if s: s.enabled = False
            elif iid.startswith("io::"):
                g = self.flow.get_io_group(iid[4:])
                if g:
                    for st in g.steps: st.enabled = False
        self._refresh_tree()

    def _duplicate(self):
        import copy
        iids = self._sel_iids()
        if not iids: return
        s = self._find_step(iids[0]); g = self._find_group(iids[0])
        if not s: return
        c = copy.deepcopy(s)
        existing = {x.name for x in (g.steps if g else self.flow.procedures)}
        base = s.name; i = 2
        while f"{base} ({i})" in existing: i += 1
        c.name    = f"{base} ({i})"
        c.order   = max((x.order for x in (g.steps if g else self.flow.procedures)), default=0) + 10
        c.step_id = _next_step_id()
        if g: g.add_step(c)
        else: self.flow.add(c)
        self._refresh_tree()

    def _delete(self):
        import tkinter.messagebox as _mb
        iids = self._sel_iids()
        if not iids: return
        if not _mb.askyesno("Delete", f"Delete {len(iids)} item(s)? Cannot be undone.",
                             parent=self.win): return

        # For a single step delete, remember which row to select next so that
        # repeated Delete clicks flow naturally without re-selecting each time.
        next_target = None
        if len(iids) == 1 and iids[0].startswith("step::"):
            sole = iids[0]
            parent = self.tree.parent(sole)
            siblings = list(self.tree.get_children(parent))
            pos = siblings.index(sole) if sole in siblings else -1
            if pos != -1:
                if pos + 1 < len(siblings):
                    next_target = siblings[pos + 1]      # next step
                elif pos - 1 >= 0:
                    next_target = siblings[pos - 1]      # was last -> previous
                else:
                    next_target = parent or None         # only step -> its folder

        for iid in iids:
            if iid.startswith("io::"):
                self.flow.remove_io_group(iid[4:])
            elif iid.startswith("step::"):
                s = self._find_step(iid); g = self._find_group(iid)
                if s:
                    if g: g.remove_step(s.name)
                    else: self.flow.remove(s.name)
        self._refresh_tree()

        # Restore selection to the remembered neighbour (iids are stable: they
        # encode step_id + parent, so the surviving sibling keeps the same iid)
        if next_target and self.tree.exists(next_target):
            self.tree.selection_set(next_target)
            self.tree.focus(next_target)
            self.tree.see(next_target)

    def _add_step(self):
        iids = self._sel_iids()
        group = None
        if iids:
            f = iids[0]
            if f.startswith("io::"):
                group = self.flow.get_io_group(f[4:])
            elif f.startswith("step::"):
                group = self._find_group(f)
        mon = self._monitor
        try:
            import __main__
            if mon is None:
                mon = getattr(getattr(__main__, "app", None), "active_mon", None)
        except Exception: pass
        target = group if group else self.flow
        dlg = AddStepDialog(self.win, target, monitor=mon)
        self.win.wait_window(dlg.win)
        if dlg.result:
            dlg.result.step_id = _next_step_id()
            if group: group.add_step(dlg.result)
            else: self.flow.add(dlg.result)
            self._refresh_tree()

    def _edit_step(self):
        iids = self._sel_iids()
        if not iids: return
        s = self._find_step(iids[0])
        if not s: return
        if s.proc_type == ProcedureType.VERIFY_CUSTOM:
            dlg = VerifyCustomWizard(self.win, s)
            self.win.wait_window(dlg.win)
            self._refresh_tree()
        else:
            g = self._find_group(iids[0])
            target = g if g else self.flow
            dlg = AddStepDialog(self.win, target, monitor=self._monitor, edit_step=s)
            self.win.wait_window(dlg.win)
            if dlg.result:
                self._refresh_tree()

    def _apply_to_all(self):
        """Copy the selected step(s) into every other IO folder. Supports
        multi-select: each selected step is applied to all folders that don't
        already have a step with that name."""
        import copy, tkinter.messagebox as _mb
        iids = [i for i in self._sel_iids() if i.startswith("step::")]
        if not iids:
            _mb.showinfo("Apply to All", "Select one or more steps first.", parent=self.win); return
        if not self.flow.has_io_groups():
            return
        # Resolve selected steps along with their source folder
        selected = []
        for iid in iids:
            st = self._find_step(iid)
            grp = self._find_group(iid)
            if st:
                selected.append((st, grp))
        if not selected:
            return

        applied_steps = 0
        for s, src_group in selected:
            for g in self.flow.io_groups:
                if g is src_group:
                    continue
                if any(x.name == s.name for x in g.steps):
                    continue
                c = copy.deepcopy(s)
                c.step_id = _next_step_id()
                c.order   = max((x.order for x in g.steps), default=0) + 10
                g.add_step(c)
                applied_steps += 1
        self._refresh_tree()
        _mb.showinfo("Done",
                     f"Applied {len(selected)} step(s) across IO folders "
                     f"({applied_steps} insertion(s)).", parent=self.win)

    def _delete_from_all(self):
        """Remove the selected step(s) (matched by name) from EVERY IO folder —
        the inverse of Apply to All IOs. Supports multi-select: every distinct
        step name in the selection is removed across all folders."""
        import tkinter.messagebox as _mb
        iids = [i for i in self._sel_iids() if i.startswith("step::")]
        if not iids:
            _mb.showinfo("Delete from All", "Select one or more steps first.", parent=self.win); return
        if not self.flow.has_io_groups():
            return
        # Collect the distinct names of all selected steps
        target_names = []
        for iid in iids:
            st = self._find_step(iid)
            if st and st.name not in target_names:
                target_names.append(st.name)
        if not target_names:
            return
        name_set = set(target_names)
        # Folders that contain at least one of the targeted names
        affected = [g for g in self.flow.io_groups
                    if any(x.name in name_set for x in g.steps)]
        names_disp = ", ".join(f'"{n}"' for n in target_names)
        if not _mb.askyesno(
            "Delete from All IOs",
            f'Remove {len(target_names)} step type(s) — {names_disp} — '
            f'from all {len(affected)} IO folder(s) that contain them?'
            f'\n\nThis cannot be undone.',
            parent=self.win):
            return
        count = 0
        for g in affected:
            before = len(g.steps)
            g.steps = [x for x in g.steps if x.name not in name_set]
            if len(g.steps) < before:
                count += 1
        self._refresh_tree()
        _mb.showinfo("Done",
                     f'Removed {len(target_names)} step type(s) from {count} IO folder(s).',
                     parent=self.win)

    def _save_template(self):
        if not _ASSETS_OK:
            import tkinter.messagebox as _mb
            _mb.showwarning("Assets", "iscs_assets not available.", parent=self.win); return
        import tkinter.simpledialog as sd, tkinter.messagebox as _mb
        name = sd.askstring("Save Template", "Template name:", parent=self.win)
        if not name or not name.strip(): return
        iids = self._sel_iids()
        group = self.flow.get_io_group(iids[0][4:]) if iids and iids[0].startswith("io::") else None
        steps = [s.to_dict() for s in group.ordered_steps] if group else [p.to_dict() for p in self.flow.procedures]
        tpl = AssetManager.instance().create_flow_template(name.strip(), steps)
        _mb.showinfo("Saved", f"Template \"{tpl.name}\" saved as {tpl.id}.", parent=self.win)

    def _load_template(self):
        """Append a saved template's steps into the selected IO folder(s), or
        into the flat flow if there are no IO groups / nothing selected.
        Multi-select = the template loads into every selected folder."""
        if not _ASSETS_OK:
            import tkinter.messagebox as _mb
            _mb.showwarning("Assets", "iscs_assets not available.", parent=self.win); return
        import tkinter.messagebox as _mb
        mgr = AssetManager.instance()
        templates = mgr.list_flow_templates()
        if not templates:
            _mb.showinfo("Load Template",
                         "No saved templates yet.\n\nUse 💾 Save Template first to create one.",
                         parent=self.win)
            return

        picker = _TemplatePickerDialog(self.win, templates)
        self.win.wait_window(picker.win)
        if not picker.result:
            return
        tpl = mgr.get_flow_template(picker.result)
        if not tpl or not tpl.steps:
            return

        # Resolve targets: selected IO folders (multi), else flat flow
        target_groups = self._resolve_selected_groups()

        def _append_steps(container_steps, add_fn):
            existing = {s.name for s in container_steps}
            base_order = max((s.order for s in container_steps), default=0)
            for i, sd_ in enumerate(tpl.steps, 1):
                step = Procedure.from_dict(dict(sd_))
                if step is None:
                    continue
                # auto-rename on collision
                nm = step.name; k = 2
                while nm in existing:
                    nm = f"{step.name} ({k})"; k += 1
                step.name    = nm
                step.step_id = _next_step_id()
                step.order   = base_order + i * 10
                existing.add(nm)
                add_fn(step)

        loaded_into = 0
        if self.flow.has_io_groups() and target_groups:
            for g in target_groups:
                _append_steps(g.steps, g.add_step)
                loaded_into += 1
        else:
            _append_steps(self.flow.procedures, self.flow.add)
            loaded_into = 1

        self._refresh_tree()
        where = (f"{loaded_into} IO folder(s)" if self.flow.has_io_groups()
                 else "the flow")
        _mb.showinfo("Load Template",
                     f"Loaded \"{tpl.name}\" ({len(tpl.steps)} steps) into {where}.",
                     parent=self.win)

    def _resolve_selected_groups(self):
        """Unique list of IOGroups implied by the current tree selection."""
        groups, seen = [], set()
        for iid in self._sel_iids():
            g = None
            if iid.startswith("io::"):
                g = self.flow.get_io_group(iid[4:])
            elif iid.startswith("step::"):
                g = self._find_group(iid)
            if g and g.io_id not in seen:
                seen.add(g.io_id); groups.append(g)
        return groups

    def _open_assets(self):
        AssetManagerDialog(self.win)

    def _open_check_gallery(self):
        CheckGalleryDialog(self.win, self)

    def _save_step_as_check_card(self):
        iids = self._sel_iids()
        if not iids:
            return
        step = self._find_step(iids[0])
        if not step or step.proc_type != ProcedureType.VERIFY_CUSTOM or not step.binding:
            return
        if not _ASSETS_OK:
            import tkinter.messagebox as _mb
            _mb.showwarning("Save as Check Card", "iscs_assets not available.", parent=self.win)
            return
        import tkinter.simpledialog as sd
        default = step.name
        name = sd.askstring("Save as Check Card", "Card name:",
                            initialvalue=default, parent=self.win)
        if not name or not name.strip():
            return
        AssetManager.instance().create_flow_template(name.strip(), [step.to_dict()])
        import tkinter.messagebox as _mb
        _mb.showinfo("Saved", f'"{name.strip()}" added to the Check Gallery.', parent=self.win)

    def _save_close(self):
        self.win.destroy()

    # ── right-click menu ──────────────────────────────────────────────────────

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        m = self._ctx; m.delete(0, "end")
        if iid.startswith("step::"):
            m.add_command(label="✏  Edit / Bind Asset", command=self._edit_step)
            m.add_command(label="⧉  Duplicate",          command=self._duplicate)
            m.add_command(label="↕  Apply to All IOs",   command=self._apply_to_all)
            step_for_menu = self._find_step(iid)
            if (step_for_menu is not None
                    and step_for_menu.proc_type == ProcedureType.VERIFY_CUSTOM
                    and step_for_menu.binding):
                m.add_command(label="🎴  Save as Check Card",
                               command=self._save_step_as_check_card)
            m.add_separator()
            m.add_command(label="✓  Enable",             command=self._enable)
            m.add_command(label="✗  Disable",            command=self._disable)
            m.add_separator()
            m.add_command(label="🗑  Delete Step",        command=self._delete)
            m.add_command(label="🗑  Delete from All IOs", command=self._delete_from_all)
        elif iid.startswith("io::"):
            m.add_command(label="+ Add Step Here",       command=self._add_step)
            m.add_separator()
            m.add_command(label="✓  Enable All",         command=self._enable)
            m.add_command(label="✗  Disable All",        command=self._disable)
            m.add_separator()
            m.add_command(label="🗑  Delete IO Folder",   command=self._delete)
        else:
            m.add_command(label="+ Add Step",            command=self._add_step)
        try: m.tk_popup(event.x_root, event.y_root)
        finally: m.grab_release()


# ─────────────────────────────────────────────────────────────────────────────
#  VERIFY-CUSTOM WIZARD — 4-step guided setup for asset-bound verify steps
# ─────────────────────────────────────────────────────────────────────────────

class VerifyCustomWizard:
    """
    4-step wizard for configuring a VERIFY_CUSTOM step's asset binding.

      Step 1 — What kind of check?   (Text / Image / Both)
      Step 2 — Where on screen?      (draw a region, or pick a saved one)
      Step 3 — What should be there? (expected text / reference picture)
      Step 4 — Settings              (name, sensitivity, on-fail)

    On Save, creates/reuses Text/Image/Region assets in AssetManager as
    needed and mutates `step` in place (name, description, binding).
    self.result is the step if saved, None if cancelled.
    """

    TITLES = {
        1: "What kind of check?",
        2: "Where on screen?",
        3: "What should be there?",
        4: "Settings",
    }

    CHECK_TYPES = [
        ("TEXT",   "📝  Text",
         "Reads text from the region with OCR and checks it matches."),
        ("IMAGE",  "🖼  Image",
         "Compares the region against a saved reference picture."),
        ("HYBRID", "🔀  Both",
         "Checks both the text and a reference picture in the region."),
    ]

    def __init__(self, master, step):
        try:
            import tkinter as tk
            from tkinter import ttk, messagebox as mb
        except ImportError:
            self.result = None
            self.win = type("W", (), {"destroy": lambda s: None})()
            return

        self.step   = step
        self.result = None
        self._tk, self._ttk, self._mb = tk, ttk, mb
        self._wiz_step = 1

        # ── wizard state ─────────────────────────────────────────────────────
        self._check_type    = "TEXT"
        self._region_coords  = None
        self._region_monitor = 0
        self._region_id      = None
        self._region_shot    = None   # PIL.Image or None
        self._expected_text  = ""
        self._threshold      = 0.85
        self._on_fail        = "fail"
        self._name           = step.name or "Verify Custom"

        # Pre-fill from an existing binding (editing)
        if step.binding and _ASSETS_OK:
            b = step.binding
            self._check_type = b.get("type", "TEXT")
            self._threshold  = float(b.get("threshold", 0.85))
            self._on_fail    = b.get("on_fail", "fail")
            mgr = AssetManager.instance()
            region = mgr.get_region(b.get("region_id", ""))
            if region:
                self._region_coords  = region.coords
                self._region_monitor = region.monitor_index
                self._region_id      = region.id
                if _PIL_OK:
                    try:
                        self._region_shot = ImageGrab.grab(
                            bbox=region.coords, all_screens=True)
                    except Exception:
                        self._region_shot = None
            if self._check_type in ("TEXT", "HYBRID"):
                ta = mgr.get_text_asset(b.get("asset_id", ""))
                if ta:
                    self._expected_text = ta.value

        win = tk.Toplevel(master)
        win.title("Verify Custom — Setup")
        win.configure(bg="#0f0f0f")
        win.geometry("580x540")
        win.minsize(540, 480)
        win.resizable(True, True)
        win.attributes("-topmost", True)
        win.grab_set()
        self.win = win

        self._build_shell()
        self._render_step()

    # ── shell: header / content / nav ───────────────────────────────────────

    def _build_shell(self):
        tk = self._tk
        win = self.win

        self._header_var = tk.StringVar()
        tk.Label(win, textvariable=self._header_var, bg="#0f0f0f", fg="#69ff9a",
                 font=("Consolas", 13, "bold")).pack(anchor="w", padx=14, pady=(12, 2))

        self._step_var = tk.StringVar()
        tk.Label(win, textvariable=self._step_var, bg="#0f0f0f", fg="#555",
                 font=("Consolas", 9)).pack(anchor="w", padx=14, pady=(0, 8))

        self._content = tk.Frame(win, bg="#0f0f0f")
        self._content.pack(fill="both", expand=True, padx=14)

        self._error_var = tk.StringVar()
        tk.Label(win, textvariable=self._error_var, bg="#0f0f0f", fg="#ff6b6b",
                 font=("Consolas", 9), wraplength=540, anchor="w",
                 justify="left").pack(fill="x", padx=14, pady=(0, 4))

        nav = tk.Frame(win, bg="#0f0f0f")
        nav.pack(fill="x", padx=14, pady=12)
        bs = dict(font=("Consolas", 9, "bold"), relief="flat", padx=12, pady=6, cursor="hand2")
        self._btn_back = tk.Button(nav, text="◀ Back", bg="#222", fg="#aaa",
                                    command=self._go_back, **bs)
        self._btn_back.pack(side="left")
        tk.Button(nav, text="Cancel", bg="#222", fg="#aaa",
                  command=win.destroy, **bs).pack(side="left", padx=6)
        self._btn_next = tk.Button(nav, text="Next ▶", bg="#1a3a1a", fg="#69ff9a",
                                    command=self._go_next, **bs)
        self._btn_next.pack(side="right")

    def _clear_content(self):
        for w in self._content.winfo_children():
            w.destroy()
        self._error_var.set("")

    def _render_step(self):
        self._clear_content()
        self._header_var.set(self.TITLES[self._wiz_step])
        self._step_var.set(f"Step {self._wiz_step} of 4")
        self._btn_back.configure(state="disabled" if self._wiz_step == 1 else "normal")
        self._btn_next.configure(text="💾 Save" if self._wiz_step == 4 else "Next ▶")

        if   self._wiz_step == 1: self._render_step1()
        elif self._wiz_step == 2: self._render_step2()
        elif self._wiz_step == 3: self._render_step3()
        elif self._wiz_step == 4: self._render_step4()

    # ── Step 1 — what kind of check ─────────────────────────────────────────

    def _render_step1(self):
        tk = self._tk
        tk.Label(self._content,
                 text="Pick the kind of check this step should run.",
                 bg="#0f0f0f", fg="#aaa", font=("Consolas", 9),
                 wraplength=500, justify="left", anchor="w").pack(fill="x", pady=(0, 10))

        self._type_buttons = {}
        for key, label, desc in self.CHECK_TYPES:
            row = tk.Frame(self._content, bg="#161616")
            row.pack(fill="x", pady=4)
            btn = tk.Button(row, text=label, font=("Consolas", 11, "bold"),
                             relief="flat", padx=14, pady=10, cursor="hand2",
                             command=lambda k=key: self._select_type(k))
            btn.pack(side="left")
            tk.Label(row, text=desc, bg="#161616", fg="#777", font=("Consolas", 9),
                     wraplength=360, justify="left", anchor="w").pack(
                     side="left", padx=10, fill="x", expand=True)
            self._type_buttons[key] = btn
        self._refresh_type_buttons()

    def _refresh_type_buttons(self):
        for key, btn in self._type_buttons.items():
            if key == self._check_type:
                btn.configure(bg="#1a3a1a", fg="#69ff9a")
            else:
                btn.configure(bg="#222", fg="#ccc")

    def _select_type(self, key):
        self._check_type = key
        self._refresh_type_buttons()

    # ── Step 2 — where ───────────────────────────────────────────────────────

    def _render_step2(self):
        tk, ttk = self._tk, self._ttk
        tk.Label(self._content,
                 text="Draw a box around the part of the screen this step should look at.",
                 bg="#0f0f0f", fg="#aaa", font=("Consolas", 9),
                 wraplength=500, justify="left", anchor="w").pack(fill="x", pady=(0, 10))

        self._region_picker = RegionPickerFrame(self._content, tk, ttk,
                                                  on_change=self._on_region_change)
        self._region_picker.frame.pack(fill="x")
        if self._region_coords:
            self._region_picker.set_region(
                self._region_coords, self._region_monitor,
                region_id=self._region_id, capture=(self._region_shot is None))
            if self._region_shot is not None:
                self._region_picker.screenshot = self._region_shot
                self._region_picker._refresh_display()

    def _on_region_change(self, picker):
        self._region_coords  = picker.coords
        self._region_monitor = picker.monitor_index
        self._region_id      = picker.region_id
        self._region_shot    = picker.screenshot
        self._error_var.set("")

    # ── Step 3 — what should be there ───────────────────────────────────────

    def _render_step3(self):
        tk = self._tk
        if self._check_type in ("TEXT", "HYBRID"):
            tk.Label(self._content, text="Expected text in this region:",
                     bg="#0f0f0f", fg="#aaa", font=("Consolas", 9),
                     anchor="w").pack(fill="x")
            self._text_var = tk.StringVar(value=self._expected_text)
            tk.Entry(self._content, textvariable=self._text_var, **_ENT_STYLE).pack(
                     fill="x", pady=(2, 6))

            self._ocr_var = tk.StringVar(value="")
            bs = dict(font=("Consolas", 9, "bold"), relief="flat", padx=10, pady=4, cursor="hand2")
            tk.Button(self._content, text="🔍 Read region now", bg="#1a2030", fg="#82b4ff",
                      command=self._run_ocr_preview, **bs).pack(anchor="w")
            tk.Label(self._content, textvariable=self._ocr_var, bg="#161616", fg="#777",
                     font=("Consolas", 9), wraplength=520, justify="left", anchor="w",
                     padx=8, pady=4).pack(fill="x", pady=(4, 10))

        if self._check_type in ("IMAGE", "HYBRID"):
            tk.Label(self._content, text="Reference picture — this is what will be matched:",
                     bg="#0f0f0f", fg="#aaa", font=("Consolas", 9),
                     anchor="w").pack(fill="x", pady=(6 if self._check_type == "HYBRID" else 0, 4))

            self._big_thumb_label = tk.Label(self._content, bg="#0a0a0a", fg="#444",
                                              font=("Consolas", 9))
            self._big_thumb_label.pack(fill="x", pady=(0, 6))
            self._refresh_big_thumb()

            if not _PIL_OK:
                tk.Label(self._content,
                         text="Pillow isn't installed, so a reference picture can't be "
                              "captured on this machine. Choose Text instead, or install Pillow.",
                         bg="#161616", fg="#ff6b6b", font=("Consolas", 9),
                         wraplength=520, justify="left", anchor="w",
                         padx=8, pady=6).pack(fill="x")

    def _refresh_big_thumb(self):
        if self._region_shot is not None and _PILTK_OK:
            img = self._region_shot.copy()
            img.thumbnail((520, 160))
            self._big_thumb_img = ImageTk.PhotoImage(img)
            self._big_thumb_label.configure(image=self._big_thumb_img, text="",
                                             width=0, height=0)
        else:
            self._big_thumb_img = None
            self._big_thumb_label.configure(image="", text="(no preview captured)",
                                             width=60, height=6)

    def _run_ocr_preview(self):
        if self._region_shot is None:
            self._ocr_var.set("No region captured yet.")
            return
        try:
            if iscs_OCR is not None and hasattr(iscs_OCR, "run"):
                text = iscs_OCR.run(self._region_shot, layout="sparse").strip()
            else:
                import pytesseract
                text = pytesseract.image_to_string(
                    self._region_shot, config="--oem 3 --psm 11").strip()
            self._ocr_var.set(f"Currently reads: {text!r}" if text
                               else "Currently reads: (nothing detected)")
        except Exception as e:
            self._ocr_var.set(f"OCR unavailable: {e}")

    # ── Step 4 — settings ────────────────────────────────────────────────────

    def _render_step4(self):
        tk, ttk = self._tk, self._ttk

        tk.Label(self._content, text="Check name:", bg="#0f0f0f", fg="#aaa",
                 font=("Consolas", 9), anchor="w").pack(fill="x")
        self._name_var = tk.StringVar(value=self._name)
        tk.Entry(self._content, textvariable=self._name_var, **_ENT_STYLE).pack(
                 fill="x", pady=(2, 10))

        if self._check_type in ("IMAGE", "HYBRID"):
            tk.Label(self._content, text="Match sensitivity (0.0–1.0, higher = stricter):",
                     bg="#0f0f0f", fg="#aaa", font=("Consolas", 9), anchor="w").pack(fill="x")
            self._thresh_var = tk.StringVar(value=str(self._threshold))
            tk.Entry(self._content, textvariable=self._thresh_var, width=8, **_ENT_STYLE).pack(
                     anchor="w", pady=(2, 10))

        tk.Label(self._content, text="If this check fails:", bg="#0f0f0f", fg="#aaa",
                 font=("Consolas", 9), anchor="w").pack(fill="x")
        self._fail_var = tk.StringVar(value=self._on_fail)
        ttk.Combobox(self._content, textvariable=self._fail_var,
                     values=["fail", "skip", "warn"], state="readonly",
                     width=10, font=("Consolas", 10)).pack(anchor="w", pady=(2, 0))
        tk.Label(self._content,
                 text="fail = mark the point FAILED   •   skip = ignore this check   "
                      "•   warn = note it but don't fail the point",
                 bg="#161616", fg="#555", font=("Consolas", 8),
                 wraplength=520, justify="left", anchor="w", padx=8, pady=4).pack(fill="x", pady=(4, 0))

    # ── navigation ────────────────────────────────────────────────────────────

    def _go_back(self):
        if self._wiz_step == 1:
            return
        self._wiz_step -= 1
        self._render_step()

    def _go_next(self):
        if not self._validate_current():
            return
        self._capture_current()
        if self._wiz_step == 4:
            self._save()
            return
        self._wiz_step += 1
        self._render_step()

    def _validate_current(self):
        if self._wiz_step == 2:
            if not self._region_coords:
                self._error_var.set("Draw a region on screen, or pick a saved one, before continuing.")
                return False
        elif self._wiz_step == 3:
            if self._check_type in ("TEXT", "HYBRID") and not self._text_var.get().strip():
                self._error_var.set("Type the text you expect to see in this region.")
                return False
            if self._check_type in ("IMAGE", "HYBRID") and self._region_shot is None:
                self._error_var.set("No reference picture captured — go back and re-draw the region.")
                return False
        elif self._wiz_step == 4:
            if not self._name_var.get().strip():
                self._error_var.set("Give this check a name.")
                return False
            if self._check_type in ("IMAGE", "HYBRID"):
                try:
                    t = float(self._thresh_var.get())
                    if not (0.0 <= t <= 1.0):
                        raise ValueError
                except ValueError:
                    self._error_var.set("Match sensitivity must be a number between 0.0 and 1.0.")
                    return False
        return True

    def _capture_current(self):
        if self._wiz_step == 3:
            if self._check_type in ("TEXT", "HYBRID"):
                self._expected_text = self._text_var.get().strip()
        elif self._wiz_step == 4:
            self._name = self._name_var.get().strip()
            if self._check_type in ("IMAGE", "HYBRID"):
                self._threshold = float(self._thresh_var.get())
            self._on_fail = self._fail_var.get()

    # ── save ──────────────────────────────────────────────────────────────────

    def _save(self):
        if not _ASSETS_OK:
            self._mb.showwarning("Verify Custom",
                                 "iscs_assets module not available — cannot save.",
                                 parent=self.win)
            return

        mgr  = AssetManager.instance()
        name = self._name

        # Region — reuse if from saved library (or unchanged from prior binding), else create new
        if self._region_id:
            region_id = self._region_id
        else:
            region_id = mgr.create_region(f"{name} - region", self._region_coords,
                                           self._region_monitor).id

        asset_id       = ""
        image_asset_id = ""

        if self._check_type in ("TEXT", "HYBRID"):
            text_name = f"{name} - text" if self._check_type == "HYBRID" else name
            asset_id  = mgr.create_text_asset(text_name, self._expected_text).id

        if self._check_type in ("IMAGE", "HYBRID"):
            import io as _io
            buf = _io.BytesIO()
            self._region_shot.convert("RGB").save(buf, format="PNG")
            img_name  = f"{name} - image" if self._check_type == "HYBRID" else name
            img_asset = mgr.create_image_asset_from_bytes(img_name, buf.getvalue()).id
            if self._check_type == "IMAGE":
                asset_id = img_asset
            else:
                image_asset_id = img_asset

        binding = {
            "type":           self._check_type,
            "asset_id":       asset_id,
            "image_asset_id": image_asset_id,
            "region_id":      region_id,
            "threshold":      self._threshold,
            "on_fail":        self._on_fail,
        }

        desc_bits = []
        if self._check_type in ("TEXT", "HYBRID"):
            desc_bits.append(f"text ≈ {self._expected_text!r}")
        if self._check_type in ("IMAGE", "HYBRID"):
            desc_bits.append("matches the reference image")
        description = "Checks that " + " and ".join(desc_bits) + " in the selected region."

        self.step.name        = name
        self.step.binding     = binding
        self.step.description = description
        self.result = self.step
        self.win.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  BINDING EDITOR DIALOG  (legacy — superseded by VerifyCustomWizard above)
# ─────────────────────────────────────────────────────────────────────────────

class BindingEditorDialog:
    """Edit or create a StepBinding on a VERIFY_CUSTOM step."""

    def __init__(self, master, step):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            self.win = type("W", (), {"destroy": lambda s: None})(); return

        self._step = step
        win = tk.Toplevel(master)
        win.title(f"Bind Asset — {step.name}")
        win.configure(bg="#0f0f0f")
        win.geometry("520x420")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.grab_set()
        self.win = win
        self._build(win, tk, ttk)

    def _build(self, win, tk, ttk):
        BG  = "#0f0f0f"
        LBL = dict(bg=BG, fg="#aaa", font=("Consolas", 9), anchor="w")
        ENT = dict(bg="#181818", fg="#eee", font=("Consolas", 10),
                   insertbackground="#eee", relief="flat", bd=6)
        bs  = dict(font=("Consolas", 9, "bold"), relief="flat", padx=8, pady=4, cursor="hand2")

        tk.Label(win, text="Bind Asset to Step", bg=BG, fg="#f9c74f",
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 6))

        tk.Label(win, text="Binding type:", **LBL).pack(fill="x", padx=14)
        self._type_var = tk.StringVar(value="TEXT")
        rf = tk.Frame(win, bg=BG); rf.pack(fill="x", padx=28, pady=(0, 8))
        for bt in ("TEXT", "IMAGE", "HYBRID"):
            tk.Radiobutton(rf, text=bt, variable=self._type_var, value=bt,
                           bg=BG, fg="#ccc", selectcolor="#161616",
                           activebackground=BG, font=("Consolas", 10)).pack(side="left", padx=8)

        tk.Frame(win, bg="#2a2a2a", height=1).pack(fill="x", padx=14, pady=4)

        for label, attr, kind in [
            ("Text Asset ID (TEXT/HYBRID):",  "_asset_var",     "text"),
            ("Image Asset ID (IMAGE/HYBRID):", "_img_asset_var", "image"),
            ("Region ID:",                     "_region_var",    "region"),
        ]:
            tk.Label(win, text=label, **LBL).pack(fill="x", padx=14)
            var = tk.StringVar(); setattr(self, attr, var)
            row = tk.Frame(win, bg=BG); row.pack(fill="x", padx=14, pady=(0, 5))
            tk.Entry(row, textvariable=var, **ENT).pack(side="left", fill="x", expand=True)
            tk.Button(row, text="Browse", bg="#1a2030", fg="#82b4ff",
                      command=lambda k=kind, v=var: self._browse(k, v),
                      **bs).pack(side="left", padx=4)

        row2 = tk.Frame(win, bg=BG); row2.pack(fill="x", padx=14, pady=(4, 8))
        tk.Label(row2, text="Threshold:", **LBL).pack(side="left")
        self._thresh_var = tk.StringVar(value="0.85")
        tk.Entry(row2, textvariable=self._thresh_var, width=6, **ENT).pack(side="left", padx=(4, 16))
        tk.Label(row2, text="On fail:", **LBL).pack(side="left")
        self._fail_var = tk.StringVar(value="fail")
        ttk.Combobox(row2, textvariable=self._fail_var,
                     values=["fail", "skip", "warn"], width=8, state="readonly",
                     font=("Consolas", 10)).pack(side="left", padx=4)

        if self._step.binding:
            b = self._step.binding
            self._type_var.set(b.get("type", "TEXT"))
            self._asset_var.set(b.get("asset_id", ""))
            self._img_asset_var.set(b.get("image_asset_id", ""))
            self._region_var.set(b.get("region_id", ""))
            self._thresh_var.set(str(b.get("threshold", 0.85)))
            self._fail_var.set(b.get("on_fail", "fail"))

        bf = tk.Frame(win, bg=BG); bf.pack(fill="x", padx=14, pady=(0, 12))
        tk.Button(bf, text="Save Binding", bg="#2979FF", fg="#fff",
                  command=self._save, **bs).pack(side="left", padx=2)
        tk.Button(bf, text="Clear Binding", bg="#2a1515", fg="#ff6b6b",
                  command=self._clear, **bs).pack(side="left", padx=2)
        tk.Button(bf, text="Cancel", bg="#222", fg="#aaa",
                  command=self.win.destroy, **bs).pack(side="right", padx=2)

    def _browse(self, kind, var):
        if not _ASSETS_OK: return
        dlg = _AssetPickerDialog(self.win, kind)
        self.win.wait_window(dlg.win)
        if dlg.result: var.set(dlg.result)

    def _save(self):
        try: threshold = float(self._thresh_var.get())
        except ValueError: threshold = 0.85
        self._step.binding = {
            "type":           self._type_var.get(),
            "asset_id":       self._asset_var.get().strip(),
            "image_asset_id": self._img_asset_var.get().strip(),
            "region_id":      self._region_var.get().strip(),
            "threshold":      threshold,
            "on_fail":        self._fail_var.get(),
        }
        self.win.destroy()

    def _clear(self):
        self._step.binding = None
        self.win.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  ASSET MANAGER DIALOG
# ─────────────────────────────────────────────────────────────────────────────

class AssetManagerDialog:
    """Full asset/region/template manager. Stays open alongside flow editor."""

    def __init__(self, master):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            return
        if not _ASSETS_OK:
            import tkinter.messagebox as _mb
            _mb.showwarning("Assets", "iscs_assets.py not found beside baru.py.", parent=master)
            return

        self._mgr = AssetManager.instance()
        win = tk.Toplevel(master)
        win.title("📁  Asset Manager")
        win.configure(bg="#0f0f0f")
        win.geometry("700x560")
        win.minsize(600, 480)
        win.resizable(True, True)
        win.attributes("-topmost", True)
        self.win = win
        self._tab_var    = tk.StringVar(value="TEXT")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh())
        self._build(win, tk, ttk)
        self._refresh()

    def _build(self, win, tk, ttk):
        BG  = "#0f0f0f"
        BG2 = "#161616"
        bs  = dict(font=("Consolas", 9, "bold"), relief="flat", padx=8, pady=4, cursor="hand2")

        hdr = tk.Frame(win, bg=BG); hdr.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(hdr, text="📁  ASSET MANAGER", bg=BG, fg="#f9c74f",
                 font=("Consolas", 12, "bold")).pack(side="left")

        tb = tk.Frame(win, bg=BG2, pady=5, padx=10); tb.pack(fill="x", padx=14, pady=(0, 4))
        tk.Button(tb, text="+ Add",    bg="#1a3a1a", fg="#69ff9a", command=self._add,    **bs).pack(side="left", padx=2)
        tk.Button(tb, text="✏ Edit",   bg="#1a2030", fg="#82b4ff", command=self._edit,   **bs).pack(side="left", padx=2)
        tk.Button(tb, text="🗑 Delete", bg="#2a1515", fg="#ff6b6b", command=self._delete, **bs).pack(side="left", padx=2)
        tk.Button(tb, text="⟳",        bg="#222",    fg="#aaa",    command=self._refresh,**bs).pack(side="right", padx=2)

        tabs_f = tk.Frame(win, bg=BG); tabs_f.pack(fill="x", padx=14, pady=(0, 4))
        for t in ("TEXT", "IMAGE", "REGIONS", "TEMPLATES"):
            tk.Button(tabs_f, text=t, bg=BG2, fg="#89b4fa",
                      font=("Consolas", 9, "bold"), relief="flat",
                      padx=10, pady=3, cursor="hand2",
                      command=lambda x=t: (self._tab_var.set(x), self._search_var.set(""), self._refresh())
                      ).pack(side="left", padx=2)

        sf = tk.Frame(win, bg=BG); sf.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(sf, text="🔍", bg=BG, fg="#555", font=("Consolas", 11)).pack(side="left")
        tk.Entry(sf, textvariable=self._search_var, bg="#181818", fg="#eee",
                 font=("Consolas", 10), insertbackground="#eee",
                 relief="flat", bd=6).pack(side="left", fill="x", expand=True)

        lf = tk.Frame(win, bg=BG); lf.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        cols = ("id", "name", "preview")
        style = ttk.Style(win)
        style.configure("Asset.Treeview", background="#111", foreground="#ccc",
                         fieldbackground="#111", rowheight=24, font=("Consolas", 10))
        style.configure("Asset.Treeview.Heading", background="#222", foreground="#89b4fa",
                         font=("Consolas", 9, "bold"))
        style.map("Asset.Treeview",
                  background=[("selected", "#f9c74f")], foreground=[("selected", "#0f0f0f")])
        self.lb = ttk.Treeview(lf, columns=cols, show="headings",
                                selectmode="browse", style="Asset.Treeview")
        vsb = tk.Scrollbar(lf, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); self.lb.pack(fill="both", expand=True)
        self.lb.heading("id",      text="ID",      anchor="w")
        self.lb.heading("name",    text="Name",    anchor="w")
        self.lb.heading("preview", text="Preview", anchor="w")
        self.lb.column("id",       width=90,  stretch=False)
        self.lb.column("name",     width=180, stretch=False)
        self.lb.column("preview",  width=380, stretch=True)
        self.lb.bind("<Double-1>", lambda _: self._edit())

    def _refresh(self):
        self.lb.delete(*self.lb.get_children())
        q   = self._search_var.get().strip()
        tab = self._tab_var.get()
        res = self._mgr.search(q)
        if tab == "TEXT":
            for t in res["text_assets"]:
                self.lb.insert("", "end", iid=t.id, values=(t.id, t.name, f'"{t.value}"'))
        elif tab == "IMAGE":
            for i in res["image_assets"]:
                self.lb.insert("", "end", iid=i.id,
                               values=(i.id, i.name, f"{i.filename} ({i.width}×{i.height})"))
        elif tab == "REGIONS":
            for r in res["regions"]:
                self.lb.insert("", "end", iid=r.id,
                               values=(r.id, r.name, f"({r.x1},{r.y1})→({r.x2},{r.y2}) mon:{r.monitor_index}"))
        elif tab == "TEMPLATES":
            for ft in res["flow_templates"]:
                self.lb.insert("", "end", iid=ft.id,
                               values=(ft.id, ft.name, f"{len(ft.steps)} steps"))

    def _sel(self): sel = self.lb.selection(); return sel[0] if sel else None

    def _add(self):
        tab = self._tab_var.get()
        if tab == "TEXT":      self._add_text()
        elif tab == "IMAGE":   self._add_image()
        elif tab == "REGIONS": self._add_region()
        else:
            import tkinter.messagebox as _mb
            _mb.showinfo("Templates", "Save templates from the Flow Editor via 💾 Template.", parent=self.win)

    def _add_text(self):
        import tkinter.simpledialog as sd
        n = sd.askstring("New Text Asset", "Name:", parent=self.win)
        if not n: return
        v = sd.askstring("New Text Asset", "Expected OCR text:", parent=self.win)
        if v is None: return
        t = self._mgr.create_text_asset(n.strip(), v)
        self._refresh()
        if self.lb.exists(t.id): self.lb.selection_set(t.id)

    def _add_image(self):
        from tkinter import filedialog
        import tkinter.simpledialog as sd, tkinter.messagebox as _mb
        p = filedialog.askopenfilename(parent=self.win, title="Select image",
            filetypes=[("Images","*.png *.jpg *.jpeg *.bmp"),("All","*.*")])
        if not p: return
        n = sd.askstring("New Image Asset", "Name:", parent=self.win)
        if not n: return
        try:
            ia = self._mgr.create_image_asset(n.strip(), p)
            self._refresh()
            if self.lb.exists(ia.id): self.lb.selection_set(ia.id)
        except Exception as e: _mb.showerror("Error", str(e), parent=self.win)

    def _add_region(self):
        import tkinter.simpledialog as sd, tkinter.messagebox as _mb
        n = sd.askstring("New Region", "Name:", parent=self.win)
        if not n: return
        c = sd.askstring("New Region", "Coords (x1,y1,x2,y2):", parent=self.win)
        if not c: return
        try:
            x1,y1,x2,y2 = [int(v.strip()) for v in c.split(",")]
        except Exception: _mb.showerror("Error", "Use format: x1,y1,x2,y2", parent=self.win); return
        r = self._mgr.create_region(n.strip(), (x1,y1,x2,y2))
        self._refresh()
        if self.lb.exists(r.id): self.lb.selection_set(r.id)

    def _edit(self):
        aid = self._sel()
        if not aid: return
        import tkinter.simpledialog as sd
        tab = self._tab_var.get()
        if tab == "TEXT":
            t = self._mgr.get_text_asset(aid)
            if not t: return
            n = sd.askstring("Edit", "Name:", initialvalue=t.name, parent=self.win)
            if n is None: return
            v = sd.askstring("Edit", "Value:", initialvalue=t.value, parent=self.win)
            if v is None: return
            self._mgr.update_text_asset(aid, name=n, value=v)
        elif tab == "IMAGE":
            ia = self._mgr.get_image_asset(aid)
            if not ia: return
            n = sd.askstring("Edit", "Name:", initialvalue=ia.name, parent=self.win)
            if n is None: return
            self._mgr.update_image_asset(aid, name=n)
        elif tab == "REGIONS":
            r = self._mgr.get_region(aid)
            if not r: return
            n = sd.askstring("Edit", "Name:", initialvalue=r.name, parent=self.win)
            if n is None: return
            c = sd.askstring("Edit", "Coords (x1,y1,x2,y2):",
                              initialvalue=f"{r.x1},{r.y1},{r.x2},{r.y2}", parent=self.win)
            if not c: return
            try:
                x1,y1,x2,y2 = [int(v.strip()) for v in c.split(",")]
                self._mgr.update_region(aid, name=n, coords=(x1,y1,x2,y2))
            except Exception: pass
        self._refresh()

    def _delete(self):
        aid = self._sel()
        if not aid: return
        import tkinter.messagebox as _mb
        if not _mb.askyesno("Delete", f"Delete {aid}? Cannot be undone.", parent=self.win): return
        tab = self._tab_var.get()
        if tab == "TEXT":       self._mgr.delete_text_asset(aid)
        elif tab == "IMAGE":    self._mgr.delete_image_asset(aid)
        elif tab == "REGIONS":  self._mgr.delete_region(aid)
        elif tab == "TEMPLATES":self._mgr.delete_flow_template(aid)
        self._refresh()


# ─────────────────────────────────────────────────────────────────────────────
#  CHECK GALLERY — visual library of reusable asset-bound checks
# ─────────────────────────────────────────────────────────────────────────────

class CheckGalleryDialog:
    """
    Visual gallery of saved 'check cards' — single-step VERIFY_CUSTOM
    FlowTemplates created via 'Save as Check Card'. Each card shows a
    thumbnail (reference image) and/or expected-text chip plus its name.

    Pick a card, multi-select IO folders back in the Flow Editor's tree
    (Ctrl/Shift-click as usual), then click 'Apply to Selected IOs' to
    drop a configured copy of that check into each selected folder.
    """

    CARD_W  = 200
    CARD_H  = 150
    THUMB_W = 184
    THUMB_H = 80

    def __init__(self, master, flow_dialog):
        try:
            import tkinter as tk
            from tkinter import ttk, messagebox as mb
        except ImportError:
            return
        if not _ASSETS_OK:
            from tkinter import messagebox as mb
            mb.showwarning("Check Gallery", "iscs_assets.py not found beside baru.py.",
                           parent=master)
            return

        self.flow_dialog = flow_dialog
        self._tk, self._ttk, self._mb = tk, ttk, mb
        self._mgr = AssetManager.instance()
        self._selected_id = None
        self._card_widgets = {}   # template_id -> frame
        self._thumb_refs   = []   # keep PhotoImage references alive

        win = tk.Toplevel(master)
        win.title("🎴  Check Gallery")
        win.configure(bg="#0f0f0f")
        win.geometry("680x520")
        win.minsize(480, 360)
        win.resizable(True, True)
        win.attributes("-topmost", True)
        self.win = win

        self._build()
        self._refresh_cards()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self):
        tk = self._tk
        BG, BG2 = "#0f0f0f", "#161616"
        bs = dict(font=("Consolas", 9, "bold"), relief="flat", padx=10, pady=5, cursor="hand2")

        hdr = tk.Frame(self.win, bg=BG)
        hdr.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(hdr, text="🎴  CHECK GALLERY", bg=BG, fg="#90e0ef",
                 font=("Consolas", 12, "bold")).pack(side="left")

        tb = tk.Frame(self.win, bg=BG2, pady=5, padx=10)
        tb.pack(fill="x", padx=14, pady=(0, 4))
        tk.Button(tb, text="✓ Apply to Selected IOs", bg="#1a3a1a", fg="#69ff9a",
                  command=self._apply_to_selected_ios, **bs).pack(side="left", padx=2)
        tk.Button(tb, text="🗑 Delete", bg="#2a1515", fg="#ff6b6b",
                  command=self._delete_card, **bs).pack(side="left", padx=2)
        tk.Button(tb, text="⟳", bg="#222", fg="#aaa",
                  command=self._refresh_cards, **bs).pack(side="right", padx=2)

        hint = tk.Label(self.win,
            text="Tip: multi-select IO folders in the Flow Editor (Ctrl/Shift-click), "
                 "then pick a card here and click Apply.",
            bg=BG, fg="#555", font=("Consolas", 8), wraplength=640,
            justify="left", anchor="w")
        hint.pack(fill="x", padx=14, pady=(0, 6))

        # Scrollable card grid
        outer = tk.Frame(self.win, bg=BG)
        outer.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._grid = tk.Frame(self._canvas, bg=BG)
        self._grid_id = self._canvas.create_window((0, 0), window=self._grid, anchor="nw")
        self._grid.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._grid_id, width=event.width)

    # ── card data ────────────────────────────────────────────────────────────

    def _check_cards(self):
        """Returns FlowTemplates that represent exactly one VERIFY_CUSTOM step."""
        out = []
        for tpl in self._mgr.list_flow_templates():
            if len(tpl.steps) == 1 and tpl.steps[0].get("proc_type") == "verify_custom"                and tpl.steps[0].get("binding"):
                out.append(tpl)
        return out

    def _refresh_cards(self):
        tk = self._tk
        for w in self._grid.winfo_children():
            w.destroy()
        self._card_widgets = {}
        self._thumb_refs   = []

        cards = self._check_cards()
        if not cards:
            empty_lbl = self._tk.Label(self._grid,
                text="No check cards yet.\n\n"
                     "Configure a Verify Custom step (Edit → the wizard), then right-click "
                     "it in the Flow Editor and choose '🎴 Save as Check Card'.",
                bg="#0f0f0f", fg="#444", font=("Consolas", 10), justify="center")
            empty_lbl.pack(pady=40)
            return

        cols = 3
        for i, tpl in enumerate(cards):
            card = self._make_card(self._grid, tpl)
            card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="n")
            self._card_widgets[tpl.id] = card
        for c in range(cols):
            self._grid.grid_columnconfigure(c, weight=1)

        if self._selected_id and self._selected_id in self._card_widgets:
            self._highlight(self._selected_id)

    def _make_card(self, parent, tpl):
        tk = self._tk
        step    = tpl.steps[0]
        binding = step.get("binding", {})
        btype   = binding.get("type", "TEXT")

        card = tk.Frame(parent, bg="#161616", width=self.CARD_W, height=self.CARD_H,
                         highlightthickness=2, highlightbackground="#222", cursor="hand2")
        card.pack_propagate(False)
        card.grid_propagate(False)

        thumb_holder = tk.Label(card, bg="#0a0a0a")
        thumb_holder.pack(fill="x", padx=6, pady=(6, 4))

        if btype in ("IMAGE", "HYBRID"):
            img_id = binding.get("image_asset_id") if btype == "HYBRID" else binding.get("asset_id")
            self._set_card_thumb(thumb_holder, img_id)
        else:
            thumb_holder.configure(height=2)

        if btype in ("TEXT", "HYBRID"):
            ta = self._mgr.get_text_asset(binding.get("asset_id", ""))
            chip_text = f'"{ta.value}"' if ta else "(text)"
            tk.Label(card, text=chip_text, bg="#1a2030", fg="#82b4ff",
                     font=("Consolas", 9), wraplength=self.CARD_W - 20,
                     padx=6, pady=3).pack(fill="x", padx=6, pady=(0, 4))

        type_icon = {"TEXT": "📝", "IMAGE": "🖼", "HYBRID": "🔀"}.get(btype, "?")
        tk.Label(card, text=f"{type_icon} {tpl.name}", bg="#161616", fg="#eee",
                 font=("Consolas", 9, "bold"), wraplength=self.CARD_W - 16,
                 justify="left", anchor="w").pack(fill="x", padx=6, pady=(0, 6))

        for w in (card, thumb_holder):
            w.bind("<Button-1>", lambda e, tid=tpl.id: self._select_card(tid))
        for child in card.winfo_children():
            child.bind("<Button-1>", lambda e, tid=tpl.id: self._select_card(tid))

        return card

    def _set_card_thumb(self, label, image_asset_id):
        if not image_asset_id or not _PILTK_OK:
            label.configure(text="(no preview)", fg="#444", font=("Consolas", 8), height=4)
            return
        path = self._mgr.get_image_path(image_asset_id)
        if not path or not path.exists():
            label.configure(text="(image missing)", fg="#444", font=("Consolas", 8), height=4)
            return
        try:
            img = Image.open(path)
            img.thumbnail((self.THUMB_W, self.THUMB_H))
            photo = ImageTk.PhotoImage(img)
            self._thumb_refs.append(photo)
            label.configure(image=photo, text="", height=self.THUMB_H)
        except Exception:
            label.configure(text="(preview error)", fg="#444", font=("Consolas", 8), height=4)

    # ── selection ────────────────────────────────────────────────────────────

    def _select_card(self, tpl_id):
        self._selected_id = tpl_id
        self._highlight(tpl_id)

    def _highlight(self, tpl_id):
        for tid, card in self._card_widgets.items():
            card.configure(highlightbackground="#69ff9a" if tid == tpl_id else "#222")

    # ── actions ───────────────────────────────────────────────────────────────

    def _resolve_target_groups(self):
        """Resolve the flow editor's current tree selection to a unique list of IOGroups."""
        fd = self.flow_dialog
        groups, seen = [], set()
        for iid in fd._sel_iids():
            g = None
            if iid.startswith("io::"):
                g = fd.flow.get_io_group(iid[4:])
            elif iid.startswith("step::"):
                g = fd._find_group(iid)
            if g and g.io_id not in seen:
                seen.add(g.io_id)
                groups.append(g)
        return groups

    def _apply_to_selected_ios(self):
        if not self._selected_id:
            self._mb.showinfo("Check Gallery", "Select a card first.", parent=self.win)
            return
        tpl = self._mgr.get_flow_template(self._selected_id)
        if not tpl:
            return
        groups = self._resolve_target_groups()
        if not groups:
            self._mb.showinfo("Check Gallery",
                "Select one or more IO folders in the Flow Editor first "
                "(Ctrl/Shift-click), then click Apply.", parent=self.win)
            return

        applied, skipped = 0, 0
        for g in groups:
            new_step = Procedure.from_dict(dict(tpl.steps[0]))
            if new_step is None:
                continue
            if any(s.name == new_step.name for s in g.steps):
                skipped += 1
                continue
            new_step.step_id = _next_step_id()
            new_step.order   = max((s.order for s in g.steps), default=0) + 10
            g.add_step(new_step)
            applied += 1

        self.flow_dialog._refresh_tree()
        msg = f"Added \"{tpl.name}\" to {applied} IO folder(s)."
        if skipped:
            msg += f"\n{skipped} already had a step with this name — skipped."
        self._mb.showinfo("Check Gallery", msg, parent=self.win)

    def _delete_card(self):
        if not self._selected_id:
            self._mb.showinfo("Check Gallery", "Select a card first.", parent=self.win)
            return
        tpl = self._mgr.get_flow_template(self._selected_id)
        name = tpl.name if tpl else self._selected_id
        if not self._mb.askyesno("Delete Check Card",
                f'Delete "{name}"?\n\nThis only removes it from the gallery — '
                f"steps already placed in flows are unaffected.", parent=self.win):
            return
        self._mgr.delete_flow_template(self._selected_id)
        self._selected_id = None
        self._refresh_cards()


# ─────────────────────────────────────────────────────────────────────────────
#  TEMPLATE PICKER (plain list dialog for Load Template)
# ─────────────────────────────────────────────────────────────────────────────

class _TemplatePickerDialog:
    """Simple list picker for saved flow templates. Returns the chosen
    template id in self.result, or None if cancelled."""

    def __init__(self, master, templates):
        self.result = None
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            self.win = type("W", (), {"destroy": lambda s: None})()
            return

        win = tk.Toplevel(master)
        win.title("📂  Load Template")
        win.configure(bg="#0f0f0f")
        win.geometry("440x380")
        win.resizable(True, True)
        win.attributes("-topmost", True)
        win.grab_set()
        self.win = win

        tk.Label(win, text="Pick a template to load into the selected IO folder(s):",
                 bg="#0f0f0f", fg="#aaa", font=("Consolas", 9),
                 wraplength=400, justify="left", anchor="w").pack(
                 fill="x", padx=12, pady=(12, 6))

        lf = tk.Frame(win, bg="#0f0f0f")
        lf.pack(fill="both", expand=True, padx=12)
        style = ttk.Style(win)
        style.configure("Tpl.Treeview", background="#111", foreground="#ccc",
                         fieldbackground="#111", rowheight=24, font=("Consolas", 10))
        style.map("Tpl.Treeview",
                  background=[("selected", "#2979FF")], foreground=[("selected", "#fff")])
        tree = ttk.Treeview(lf, columns=("name", "steps"), show="headings",
                            selectmode="browse", style="Tpl.Treeview")
        tree.heading("name", text="Template", anchor="w")
        tree.heading("steps", text="Steps", anchor="center")
        tree.column("name", width=300, stretch=True, anchor="w")
        tree.column("steps", width=70, stretch=False, anchor="center")
        vsb = tk.Scrollbar(lf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        for tpl in templates:
            tree.insert("", "end", iid=tpl.id,
                        values=(tpl.name, len(tpl.steps)))

        def _confirm(*_):
            sel = tree.selection()
            if sel:
                self.result = sel[0]
                win.destroy()

        tree.bind("<Double-1>", _confirm)

        bf = tk.Frame(win, bg="#0f0f0f")
        bf.pack(fill="x", padx=12, pady=10)
        bs = dict(font=("Consolas", 9, "bold"), relief="flat", padx=10, pady=5, cursor="hand2")
        tk.Button(bf, text="Load", bg="#1a3a1a", fg="#69ff9a",
                  command=_confirm, **bs).pack(side="left", padx=2)
        tk.Button(bf, text="Cancel", bg="#222", fg="#aaa",
                  command=win.destroy, **bs).pack(side="left", padx=2)


# ─────────────────────────────────────────────────────────────────────────────
#  ASSET PICKER (inline mini-dialog for BindingEditorDialog)
# ─────────────────────────────────────────────────────────────────────────────

class _AssetPickerDialog:
    def __init__(self, master, kind):
        self.result = None
        if not _ASSETS_OK: return
        try: import tkinter as tk; from tkinter import ttk
        except ImportError: return
        mgr = AssetManager.instance()
        win = tk.Toplevel(master)
        win.title(f"Pick {kind.title()}")
        win.configure(bg="#0f0f0f")
        win.geometry("420x320")
        win.resizable(True, True)
        win.attributes("-topmost", True)
        win.grab_set()
        self.win = win

        sv = tk.StringVar()
        tk.Entry(win, textvariable=sv, bg="#181818", fg="#eee",
                 font=("Consolas", 10), insertbackground="#eee",
                 relief="flat", bd=6).pack(fill="x", padx=12, pady=8)

        lf = tk.Frame(win, bg="#0f0f0f"); lf.pack(fill="both", expand=True, padx=12)
        style = ttk.Style(win)
        style.configure("Pick.Treeview", background="#111", foreground="#ccc",
                         fieldbackground="#111", rowheight=22, font=("Consolas", 10))
        style.map("Pick.Treeview",
                  background=[("selected","#f9c74f")], foreground=[("selected","#0f0f0f")])
        tree = ttk.Treeview(lf, columns=("id","name","preview"), show="headings",
                             selectmode="browse", style="Pick.Treeview")
        tree.heading("id", text="ID", anchor="w")
        tree.heading("name", text="Name", anchor="w")
        tree.heading("preview", text="Preview", anchor="w")
        tree.column("id",width=80,stretch=False); tree.column("name",width=130,stretch=False)
        tree.column("preview",width=180,stretch=True)
        vsb = tk.Scrollbar(lf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); tree.pack(fill="both", expand=True)

        def refresh(*_):
            tree.delete(*tree.get_children())
            q = sv.get().strip(); res = mgr.search(q)
            if kind == "text":
                for t in res["text_assets"]:
                    tree.insert("","end",iid=t.id,values=(t.id,t.name,f'"{t.value}"'))
            elif kind == "image":
                for i in res["image_assets"]:
                    tree.insert("","end",iid=i.id,values=(i.id,i.name,i.filename))
            elif kind == "region":
                for r in res["regions"]:
                    tree.insert("","end",iid=r.id,
                                values=(r.id,r.name,f"({r.x1},{r.y1})→({r.x2},{r.y2})"))

        sv.trace_add("write", lambda *_: refresh()); refresh()

        def pick(*_):
            sel = tree.selection()
            if sel: self.result = sel[0]; win.destroy()

        tree.bind("<Double-1>", pick)
        bf = tk.Frame(win, bg="#0f0f0f"); bf.pack(fill="x", padx=12, pady=8)
        bs = dict(font=("Consolas","9","bold"), relief="flat", padx=8, pady=4, cursor="hand2")
        tk.Button(bf, text="Select", bg="#2979FF", fg="#fff", command=pick, **bs).pack(side="left")
        tk.Button(bf, text="Cancel", bg="#222", fg="#aaa", command=win.destroy, **bs).pack(side="left", padx=4)



# ═════════════════════════════════════════════════════════════════════════════
#  INTEGRATION HELPERS  (drop-in replacements for baru.py methods)
# ═════════════════════════════════════════════════════════════════════════════

def build_runner_from_scenario(sc, verifier, handler, config, on_log,
                                stop_event, pause_event) -> ProcedureRunner:
    """
    Convenience factory.  Builds or reuses the ProcedureFlow attached to `sc`,
    then returns a ready-to-use ProcedureRunner.

    Attaches flow to sc.procedure_flow so it persists across loop iterations
    and can be inspected/edited via the dialog.
    """
    card_cfg = getattr(sc, "card_cfg", {})
    nav      = card_cfg.get("navigation", {})

    # Build zones_dict (same logic as SuiteRunner._run_scenario)
    zones_dict: dict = {}
    for page_zones in getattr(sc, "zones_per_page", {}).values():
        for zt, z in page_zones.items():
            if zt not in zones_dict:
                zones_dict[zt] = z
    for z in getattr(sc, "zones", []):
        if z.zone_type not in zones_dict:
            zones_dict[z.zone_type] = z

    # Ensure the verifier is aware of the stop signal for its internal loops
    if hasattr(verifier, "stop_event"):
        verifier.stop_event = stop_event

    # Reuse existing flow or auto-register defaults
    if not getattr(sc, "procedure_flow", None):
        sc.procedure_flow = auto_register_procedures(sc, zones_dict, nav)

    runner = ProcedureRunner(
        flow       = sc.procedure_flow,
        verifier   = verifier,
        handler    = handler,
        config     = config,
        on_log     = on_log,
        stop_event = stop_event,
        pause_event= pause_event,
    )
    return runner