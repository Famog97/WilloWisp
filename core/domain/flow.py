"""
Flow domain model — step taxonomy + (later) Procedure/IOGroup/ProcedureFlow.

Pure data, no UI/engine dependency. This M2.1 sub-step relocates the step enums
and the dynamic-proc-type decoupling (P6.3) verbatim from ``iscs_workflow``;
``iscs_workflow`` re-exports them as shims. The flow containers
(Procedure/IOGroup/ProcedureFlow) join here in the next M2.1 sub-step.
"""
from __future__ import annotations

from enum import Enum


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
