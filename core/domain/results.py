"""
Result-domain value objects.

Currently hosts ``VerifyResult`` (one verification sub-check outcome). The flow
result types (``ProcedureResult``, ``ExecutionTrace``) join here in a later M2.1
sub-step. Domain value objects: no UI dependency. Relocated verbatim from ``baru``
(M2.1); ``baru`` re-exports it as a shim.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.domain.flow import ProcedureStatus, ProcedureType


class VerifyResult:
    """Holds the result of one verification step (alarm panel, list, inspector)."""

    def __init__(self, step: str, status: str, msg: str = "", screenshot: str = ""):
        self.step = step
        self.status = status
        self.msg = msg
        self.screenshot = screenshot

    def to_dict(self):
        return {"step": self.step, "status": self.status, "msg": self.msg,
                "screenshot": self.screenshot}


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
