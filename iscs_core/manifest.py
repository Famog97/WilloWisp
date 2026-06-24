"""
Capability load manifest + optional-dependency probes (FR-18, FR-19 — retires R10).

Today optional-dependency handling is scattered per-module boilerplate
(`UPGRADES_AVAILABLE`, `RECORDER_AVAILABLE`, `PYAUTOGUI_AVAILABLE`, …) with
inconsistent diagnostics and no single place that says *what loaded, what didn't,
and why*. This module generalizes that into:

  - a **dependency-probe registry** (FR-18): a capability declares the logical
    resources it needs in ``CapabilityMeta.requires`` (e.g. ``["ocr"]``,
    ``["assets"]``); a probe answers whether each is available. Missing ones can
    be reported — and optionally the capability disabled — without crashing.

  - a **LoadManifest** (FR-19): one diagnostic snapshot of every capability /
    plugin / subsystem and its load state (``loaded`` / ``unavailable`` /
    ``failed``) with the reason, suitable for printing at startup.

Self-contained: depends only on ``CapabilityRegistry`` (for `evaluate_requirements`
and `record_registry`). Discovery feeds it load successes/failures.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# A probe answers "is this named resource available?" → (available, detail).
Probe = Callable[[], Tuple[bool, str]]


# ──────────────────────────────────────────────────────────────────────────────
#  Dependency probes (FR-18)
# ──────────────────────────────────────────────────────────────────────────────

_PROBES: Dict[str, Probe] = {}


def register_dependency(name: str, probe: Probe, *, override: bool = False) -> None:
    """Register a probe for a logical dependency name (FR-7 duplicate check)."""
    if not name:
        raise ValueError("dependency name must be a non-empty string")
    if name in _PROBES and not override:
        raise ValueError(f"Dependency probe {name!r} already registered "
                         f"(pass override=True to replace).")
    _PROBES[name] = probe


def importable(modname: str) -> Probe:
    """Build a probe that succeeds iff ``modname`` can be imported."""
    def _probe() -> Tuple[bool, str]:
        try:
            importlib.import_module(modname)
            return True, ""
        except Exception as e:   # ImportError or a deeper failure during import
            return False, f"requires module {modname!r} ({type(e).__name__}: {e})"
    return _probe


def dependency_status(name: str) -> Tuple[bool, str]:
    """Availability of one logical dependency. Unknown names are treated as
    available (engine-provided resources like ``verifier`` have no probe) but
    annotated as such."""
    probe = _PROBES.get(name)
    if probe is None:
        return True, "no probe (assumed available)"
    try:
        return probe()
    except Exception as e:       # a faulty probe must not crash the caller
        return False, f"probe error: {e}"


def missing_requirements(requires: Optional[List[str]]) -> List[Tuple[str, str]]:
    """Return ``(name, detail)`` for each required dependency that is unavailable."""
    out: List[Tuple[str, str]] = []
    for name in (requires or ()):
        ok, detail = dependency_status(name)
        if not ok:
            out.append((name, detail))
    return out


def list_dependencies() -> List[str]:
    return sorted(_PROBES)


# Default probes for the optional dependencies this app actually uses. Logical
# names map to the importable module that backs them. Engine-provided resources
# (e.g. "verifier") intentionally have no probe → assumed available.
for _name, _mod in {
    "ocr":        "iscs_OCR",
    "tesseract":  "pytesseract",
    "assets":     "iscs_assets",
    "pyautogui":  "pyautogui",
    "pil":        "PIL",
    "opencv":     "cv2",
    "cv2":        "cv2",
    "modbus":     "pymodbus",
    "pymodbus":   "pymodbus",
    "keyboard":   "keyboard",
    "pandas":     "pandas",
    "fpdf2":      "fpdf",
    "screeninfo": "screeninfo",
}.items():
    _PROBES[_name] = importable(_mod)


# ──────────────────────────────────────────────────────────────────────────────
#  Load manifest (FR-19)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CapabilityLoad:
    """One entry in the load manifest."""
    identifier: str               # capability key, plugin module, or subsystem name
    state: str                    # "loaded" | "unavailable" | "failed"
    category: str = ""
    reason: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"identifier": self.identifier, "state": self.state,
                "category": self.category, "reason": self.reason, "source": self.source}


class LoadManifest:
    """A single, queryable record of what loaded / what didn't / why (FR-19)."""

    def __init__(self) -> None:
        self._entries: Dict[str, CapabilityLoad] = {}   # one entry per identifier

    # -- recording -------------------------------------------------------------
    def record_loaded(self, key: str, category: str = "", source: str = "") -> None:
        self._entries[key] = CapabilityLoad(key, "loaded", category, "", source)

    def record_unavailable(self, key: str, reason: str,
                           category: str = "", source: str = "") -> None:
        self._entries[key] = CapabilityLoad(key, "unavailable", category, reason, source)

    def record_failed(self, identifier: str, reason: str, source: str = "") -> None:
        self._entries[identifier] = CapabilityLoad(identifier, "failed", "", reason, source)

    def record_registry(self, reg: Any) -> None:
        """Backfill: record every currently-registered capability as loaded unless
        it is already in the manifest (e.g. recorded with a source by discovery).
        Captures capabilities registered outside discovery, like legacy adapters."""
        for cap in reg.list():
            if cap.key not in self._entries:
                self.record_loaded(cap.key, category=getattr(cap.meta, "category", ""))

    # -- queries ---------------------------------------------------------------
    def _by_state(self, state: str) -> List[CapabilityLoad]:
        return sorted((e for e in self._entries.values() if e.state == state),
                      key=lambda e: e.identifier)

    def loaded(self) -> List[CapabilityLoad]:
        return self._by_state("loaded")

    def unavailable(self) -> List[CapabilityLoad]:
        return self._by_state("unavailable")

    def failed(self) -> List[CapabilityLoad]:
        return self._by_state("failed")

    def entries(self) -> List[CapabilityLoad]:
        return sorted(self._entries.values(), key=lambda e: (e.state, e.identifier))

    def as_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        return {"loaded": [e.to_dict() for e in self.loaded()],
                "unavailable": [e.to_dict() for e in self.unavailable()],
                "failed": [e.to_dict() for e in self.failed()]}

    def summary(self) -> str:
        """Human-readable one-block diagnostic for startup logging."""
        L, U, F = self.loaded(), self.unavailable(), self.failed()
        lines = [f"capability manifest: {len(L)} loaded, "
                 f"{len(U)} unavailable, {len(F)} failed"]
        for e in U:
            lines.append(f"  - unavailable: {e.identifier} — {e.reason}")
        for e in F:
            lines.append(f"  - failed: {e.identifier} — {e.reason}")
        return "\n".join(lines)


def evaluate_requirements(reg: Any, manifest: LoadManifest, *,
                          disable: bool = False) -> List[str]:
    """Check each registered capability's ``meta.requires`` against the probes;
    record any with unmet requirements as ``unavailable`` in the manifest (FR-18).

    With ``disable=True`` the capability is also unregistered so the system
    "disables just that capability and continues" — off by default so callers
    opt in explicitly (the live app keeps its legacy fallback path).

    Returns the keys found to have unmet requirements.
    """
    bad: List[str] = []
    for cap in reg.list():
        missing = missing_requirements(getattr(cap.meta, "requires", []))
        if missing:
            reason = "; ".join(f"{n} ({d})" for n, d in missing)
            manifest.record_unavailable(cap.key, reason,
                                        category=getattr(cap.meta, "category", ""))
            bad.append(cap.key)
            if disable:
                reg.unregister(cap.key)
    return bad
