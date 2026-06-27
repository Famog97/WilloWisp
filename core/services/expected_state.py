"""
core/services/expected_state.py  (M3.4 — relocated from baru)

Pure derivation of the "expected verification state" from an IO-list point dict:
which state index is the trigger vs the reset (``_get_state_indices``) and the flat
expected-value dict the verifier checks against (``build_expected``). No UI / OS /
device dependencies — only the severity matrix (severity -> panel text + colour).
baru re-exports these as shims; the engine imports them from here directly.
"""
from __future__ import annotations

from core.services.config import SEVERITY_MATRIX


def _get_state_indices(pt):
    """
    Derive trigger and reset value indices purely from the point's states dict.
    No hardcoding — works for any IO list regardless of how many states exist.
    
    Convention from IO list:
      - Trigger state = highest value index (e.g. v1 = ALARM, OPEN, OUT OF SERVICE)
      - Reset state   = lowest  value index (e.g. v0 = NORMAL, CLOSE, IN SERVICE)
    
    Returns (trigger_idx, reset_idx) as integers.
    """
    states = pt.get("states", {})
    if not states:
        return 1, 0   # absolute last resort fallback only if states completely missing
    keys = sorted(int(k) for k in states.keys() if str(k).lstrip("-").isdigit())
    if len(keys) == 1:
        # Only one state defined — treat it as trigger, no reset check possible
        return keys[0], keys[0]
    return keys[-1], keys[0]   # highest = trigger, lowest = reset/normal


def _get_expected_for_value(point, triggered_value):
    states = point.get("states", {})
    # States keys may be int or string depending on whether loaded from DB,
    # parsed fresh from Excel, or round-tripped through JSON (suite save/load).
    # Normalise to string keys for lookup to handle all cases.
    states_str = {str(k): v for k, v in states.items()}
    key = str(triggered_value)
    if key in states_str:
        s = states_str[key]
    elif states_str:
        # Fallback: use highest value index (most likely the alarm state)
        s = states_str[max(states_str.keys(), key=lambda k: int(k) if k.isdigit() else 0)]
    else:
        s = {"label": "ALARM", "severity": point.get("severity", 1), "state": "A"}
    return {
        "label":    s.get("label", ""),
        "severity": s.get("severity", 0),
        "state":    s.get("state", "N"),
        "is_alarm": s.get("state", "N").upper() == "A",
    }

def build_expected(pt: dict, trigger_value: int = 1) -> dict:
    """
    Build a flat expected-state dict from an IO list point dict.
    Used by ISCS_Engine to tell ISCSVerifier what to look for after triggering.
    Keys returned:
        point_id, description, severity, label (=Value on panel), color,
        state, is_alarm, reset_label, reset_severity
    """
    base       = _get_expected_for_value(pt, trigger_value)
    reset_base = _get_expected_for_value(pt, 0)      # v0 = normal/reset state

    sev_str   = str(base.get("severity", pt.get("severity", 0)))
    sev_entry = SEVERITY_MATRIX.get(sev_str, {"text": sev_str, "color": (255, 0, 0)})

    eq   = pt.get("equipment_desc", "").strip()
    attr = pt.get("attribute_desc", "").strip()
    description = f"{eq} : {attr}" if eq and attr else (eq or attr)

    return {
        "point_id":       pt.get("point_id", ""),
        "description":    description,
        "severity":       sev_entry.get("text", sev_str),
        "label":          base.get("label", attr),        # v1_label — Value on panel when triggered
        "color":          sev_entry.get("color", (255, 0, 0)),
        "state":          base.get("state", "N"),
        "is_alarm":       base.get("is_alarm", True),
        "reset_label":    reset_base.get("label", "NORMAL"),
        "reset_severity": str(reset_base.get("severity", 0)),
    }
