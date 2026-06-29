"""
core/domain/io_point_states.py

Pure interpretation of an IO point's value-state table (the v0..v7 columns from the IO
list) into a *test plan*: which value is the baseline (normal), which values to
trigger, the bit-width of the register field, and how to encode a value into that
field for a Modbus write.

No device, no UI, no assumptions like "alarm=1 / normal=0". The baseline is whatever
state the IO list marks severity-0 / non-alarm; the trigger values are everything else.
This is the model the run flow + Modbus write build on (data-driven per IO list).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# states is the parsed table: {value:int -> {"label","severity","state"}}
States = Dict[int, dict]


def _is_normal(s: dict) -> bool:
    """A state is 'normal' if it is severity 0 and not explicitly an alarm ('A')."""
    sev = s.get("severity", 0)
    try:
        sev = int(sev)
    except (TypeError, ValueError):
        sev = 0
    return sev == 0 and str(s.get("state", "N")).upper() != "A"


def baseline_value(states: States) -> Optional[int]:
    """The normal/reset value — found by scanning, NOT assumed to be 0.

    Prefers a severity-0 state flagged 'N'; else any severity-0 state; else the lowest
    value (a point with no normal state at all still needs a baseline to return to).
    """
    if not states:
        return None
    normals = [v for v, s in states.items() if _is_normal(s)]
    pref_n = [v for v in normals if str(states[v].get("state", "N")).upper() == "N"]
    if pref_n:
        return min(pref_n)
    if normals:
        return min(normals)
    return min(states.keys())


def trigger_values(states: States, baseline: Optional[int] = None) -> List[int]:
    """Values to write + verify (every defined value except the baseline), ascending."""
    if baseline is None:
        baseline = baseline_value(states)
    return sorted(v for v in states if v != baseline)


def field_width(addr_size: Any, states: States) -> int:
    """Bit-width of the register field.

    Parses DC_Addr_Size ('1 Bit' / 1 / '3 Bit' / 3). If it's missing or smaller than
    the highest defined value needs, infer from that value (e.g. values 0..3 -> 2 bits).
    """
    parsed = 0
    if addr_size is not None:
        m = re.search(r"(\d+)", str(addr_size))
        if m:
            parsed = int(m.group(1))
    need = 1
    if states:
        hi = max(states.keys())
        need = max(1, hi.bit_length())
    return max(parsed, need)


def apply_value(cur_reg: int, value: int, bit_offset: int, width: int) -> int:
    """Place `value` into the `width`-bit field at `bit_offset` of a 16-bit register
    word, leaving the other bits untouched. (width=1 reduces to set/clear one bit.)"""
    mask = ((1 << width) - 1) << bit_offset
    return ((cur_reg & ~mask) | ((value << bit_offset) & mask)) & 0xFFFF


def normalize_register(reg) -> int:
    """Convert an IO-list register to the datastore/PDU address.

    The 4xxxx Modbus holding-register convention is base-40000 (40000 -> 0, 40001 -> 1,
    40030 -> 30); raw small addresses (e.g. AMS's 30) are already PDU addresses and pass
    through unchanged. So both `40030` and a raw `30` resolve to datastore register 30.
    """
    try:
        r = int(reg)
    except (TypeError, ValueError):
        return 0
    return r - 40000 if r >= 40000 else r


def write_register(payload: dict) -> int:
    """The register ISCS actually reads/writes.

    Prefer ``iscs_modbus_address`` when the IO list provides it (that is where ISCS
    reads the point); otherwise fall back to ``reg`` (the source-system register, which
    for TWP/AMS-style lists already IS the ISCS address).
    """
    iscs = payload.get("iscs_modbus_address")
    if iscs:
        return int(iscs)
    return int(payload.get("reg", 0) or 0)
