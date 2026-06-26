"""
Flow domain model — step taxonomy + (later) Procedure/IOGroup/ProcedureFlow.

Pure data, no UI/engine dependency. This M2.1 sub-step relocates the step enums
and the dynamic-proc-type decoupling (P6.3) verbatim from ``iscs_workflow``;
``iscs_workflow`` re-exports them as shims. The flow containers
(Procedure/IOGroup/ProcedureFlow) join here in the next M2.1 sub-step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


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
        if self.io_groups:
            d["io_groups"] = [g.to_dict() for g in self.io_groups]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProcedureFlow":
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
