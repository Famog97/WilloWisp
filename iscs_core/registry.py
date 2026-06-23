"""
Capability contract + registry.

A *capability* is one pluggable unit of behavior (an action, verification, or
utility) addressed by a stable string key — the same keys already used as
ProcedureType enum values (e.g. "verify_alarm_panel"), so existing saved flows
map onto capabilities without data migration (FR-22).

The engine resolves a step's capability from the registry and calls execute(ctx),
with no per-type branching — this is what replaces the hardcoded dispatch dict
in iscs_workflow.ProcedureRunner (FR-2, FR-8).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, runtime_checkable


# ──────────────────────────────────────────────────────────────────────────────
#  Result + status
# ──────────────────────────────────────────────────────────────────────────────

class StepStatus(str, Enum):
    """Mirrors the existing status vocabulary used across the app/reports."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass
class StepResult:
    """Uniform return value for every capability (FR-8/FR-10).

    Deliberately small and JSON-friendly so it can flow into the normalized
    report model without the report layer knowing the capability's type.
    """
    status: StepStatus
    message: str = ""
    screenshot: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "message": self.message,
            "screenshot": self.screenshot,
            "data": self.data,
        }


# ──────────────────────────────────────────────────────────────────────────────
#  Metadata + contract
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CapabilityMeta:
    """Describes a capability for UI palettes (FR-20) and applicability (FR-21)."""
    name: str                               # human-readable label
    category: str                           # "action" | "verification" | "utility"
    params_schema: Dict[str, Any] = field(default_factory=dict)
    requires: List[str] = field(default_factory=list)   # e.g. ["ocr"], ["protocol"]
    description: str = ""
    addable: bool = False                   # show in the Add-Step palette (FR-20)


@runtime_checkable
class Capability(Protocol):
    """Structural contract every capability satisfies.

    Implementations expose `key` + `meta` and an `execute(ctx) -> StepResult`.
    `is_applicable` is optional; a default of "always applicable" is assumed by
    the registry helpers when absent.
    """
    key: str
    meta: CapabilityMeta

    def execute(self, ctx: Any) -> StepResult: ...


# ──────────────────────────────────────────────────────────────────────────────
#  Errors
# ──────────────────────────────────────────────────────────────────────────────

class DuplicateCapabilityError(Exception):
    """Raised when registering a key that already exists (without override)."""


class UnknownCapabilityError(KeyError):
    """Raised on lookup of a key that is neither registered nor aliased."""
    def __init__(self, key: str, known: Optional[List[str]] = None):
        self.key = key
        hint = f" Known keys: {sorted(known)}" if known else ""
        super().__init__(f"No capability registered for key {key!r}.{hint}")


# ──────────────────────────────────────────────────────────────────────────────
#  Registry
# ──────────────────────────────────────────────────────────────────────────────

class CapabilityRegistry:
    """Central catalog of capabilities, addressed by string key.

    Generalizes the registry pattern already proven by baru.ProtocolManager
    (register_protocol / get) to all capability categories.
    """

    def __init__(self) -> None:
        self._caps: Dict[str, Capability] = {}
        self._aliases: Dict[str, str] = {}

    # -- registration ----------------------------------------------------------
    def register(self, cap: Capability, *, override: bool = False) -> Capability:
        key = getattr(cap, "key", None)
        if not key:
            raise ValueError("Capability must define a non-empty 'key'.")
        if not isinstance(getattr(cap, "meta", None), CapabilityMeta):
            raise ValueError(f"Capability {key!r} must define a CapabilityMeta 'meta'.")
        if key in self._caps and not override:
            raise DuplicateCapabilityError(
                f"Capability key {key!r} already registered. Pass override=True to replace."
            )
        self._caps[key] = cap
        return cap

    def alias(self, old_key: str, new_key: str) -> None:
        """Map a deprecated/renamed key onto a current one (FR-23)."""
        self._aliases[old_key] = new_key

    # -- lookup ----------------------------------------------------------------
    def _resolve_key(self, key: str) -> str:
        seen = set()
        while key in self._aliases and key not in self._caps:
            if key in seen:
                break                      # guard against alias cycles
            seen.add(key)
            key = self._aliases[key]
        return key

    def get(self, key: str) -> Capability:
        resolved = self._resolve_key(key)
        try:
            return self._caps[resolved]
        except KeyError:
            raise UnknownCapabilityError(key, known=list(self._caps)) from None

    def has(self, key: str) -> bool:
        return self._resolve_key(key) in self._caps

    def list(self, category: Optional[str] = None) -> List[Capability]:
        caps = sorted(self._caps.values(), key=lambda c: c.key)
        if category is None:
            return caps
        return [c for c in caps if c.meta.category == category]

    def keys(self) -> List[str]:
        return sorted(self._caps)

    def manifest(self) -> Dict[str, Dict[str, Any]]:
        """Diagnostic snapshot of what's loaded (FR-19)."""
        return {
            c.key: {"name": c.meta.name, "category": c.meta.category,
                    "requires": list(c.meta.requires)}
            for c in self.list()
        }

    def unregister(self, key: str) -> bool:
        """Remove a capability by key. Returns True if it was present."""
        existed = key in self._caps
        self._caps.pop(key, None)
        return existed

    def clear(self) -> None:
        """Reset — primarily for test isolation."""
        self._caps.clear()
        self._aliases.clear()


# ──────────────────────────────────────────────────────────────────────────────
#  Module-level default registry + decorator
# ──────────────────────────────────────────────────────────────────────────────

registry = CapabilityRegistry()

# Ambient target used by @register when no explicit `into=` is given. Discovery
# sets this (via `using_registry`) so plugins discovered into a specific registry
# land there without each plugin module hard-coding a registry reference.
_active_registry: Optional[CapabilityRegistry] = None


@contextmanager
def using_registry(reg: CapabilityRegistry) -> Iterator[CapabilityRegistry]:
    """Within this block, bare ``@register()`` targets ``reg`` instead of the
    global registry. Used by the discovery functions for test isolation and for
    loading plugins into a scoped registry."""
    global _active_registry
    prev = _active_registry
    _active_registry = reg
    try:
        yield reg
    finally:
        _active_registry = prev


def register(*, into: Optional[CapabilityRegistry] = None,
             override: bool = False) -> Callable[[type], type]:
    """Class decorator: instantiate and register a capability at import time (FR-3).

        @register()
        class ClickAction:
            key = "click"
            meta = CapabilityMeta(name="Click", category="action")
            def execute(self, ctx): ...

    Target resolution: explicit ``into=`` > the ambient registry set by
    ``using_registry`` (during discovery) > the global ``registry``.
    """
    def _decorator(cls: type) -> type:
        target = into or _active_registry or registry
        target.register(cls(), override=override)
        return cls

    return _decorator
