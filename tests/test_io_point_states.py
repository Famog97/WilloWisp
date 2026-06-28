"""
Value-state model — proven against the REAL IO-list points (TWP / AMS / ES).

Each `states` dict mirrors what the parser extracts from the vN columns:
  {value: {"label", "severity", "state"}}.
"""
from core.domain.io_point_states import (
    baseline_value, trigger_values, field_width, apply_value, write_register,
)


# ── real examples ─────────────────────────────────────────────────────────────
AMS = {0: {"label": "NORMAL", "severity": 0, "state": "N"},
       1: {"label": "ALARM",  "severity": 1, "state": "A"}}                 # the "lucky" case

TWP_0_0 = {0: {"label": "NOT READY", "severity": 0, "state": "N"},
           1: {"label": "READY",     "severity": 0, "state": "N"}}          # both normal

TWP_0_2 = {0: {"label": "NORMAL",  "severity": 0, "state": "N"},
           1: {"label": "STALLED", "severity": 2, "state": "A"}}

# ES "Open / Close Status": 2-bit, and NORMAL is value 1 (CLOSE), not value 0.
ES_OPEN_CLOSE = {0: {"label": "INTERMEDIATE", "severity": 1, "state": "A"},
                 1: {"label": "CLOSE",        "severity": 0, "state": "N"},
                 2: {"label": "OPEN",         "severity": 1, "state": "A"},
                 3: {"label": "INCONSISTENT", "severity": 1, "state": "A"}}


def test_baseline_is_value_0_for_classic_points():
    assert baseline_value(AMS) == 0
    assert baseline_value(TWP_0_2) == 0
    assert baseline_value(TWP_0_0) == 0          # both normal -> lowest


def test_baseline_is_not_assumed_zero_for_es_open_close():
    # The old code assumed value 0 = normal; here value 0 is an ALARM.
    assert baseline_value(ES_OPEN_CLOSE) == 1     # CLOSE (sev 0 / N) is the real normal


def test_trigger_values_cover_every_non_baseline_state():
    assert trigger_values(AMS) == [1]
    assert trigger_values(TWP_0_0) == [1]
    assert trigger_values(ES_OPEN_CLOSE) == [0, 2, 3]   # all three alarms, baseline 1 excluded


def test_field_width_infers_multibit_from_values():
    assert field_width("1 Bit", AMS) == 1
    assert field_width(1, TWP_0_2) == 1
    assert field_width(None, ES_OPEN_CLOSE) == 2        # values 0..3 need 2 bits
    assert field_width("1 Bit", ES_OPEN_CLOSE) == 2     # inferred width wins over a too-small size


def test_apply_value_single_bit_matches_old_set_clear():
    # bit 0: value 1 sets it, value 0 clears it, other bits untouched
    assert apply_value(0b0000, 1, bit_offset=0, width=1) == 0b0001
    assert apply_value(0b1111, 0, bit_offset=0, width=1) == 0b1110
    assert apply_value(0b0000, 1, bit_offset=11, width=1) == (1 << 11)


def test_write_register_prefers_iscs_address():
    # ES: source register 40010 is ignored; ISCS reads its own address 40000.
    assert write_register({"reg": 40010, "iscs_modbus_address": 40000}) == 40000
    # TWP/AMS: no ISCS address column -> the parsed reg already IS the ISCS address.
    assert write_register({"reg": 40001}) == 40001
    assert write_register({"reg": 30}) == 30
    assert write_register({"reg": 0}) == 0


def test_apply_value_multibit_writes_whole_field():
    # 2-bit field at offset 0: write value 2 (binary 10) and value 3 (binary 11)
    assert apply_value(0b0000, 2, bit_offset=0, width=2) == 0b0010
    assert apply_value(0b0000, 3, bit_offset=0, width=2) == 0b0011
    # field is replaced, neighbouring bits preserved
    assert apply_value(0b1100, 1, bit_offset=0, width=2) == 0b1101
    assert apply_value(0b0011, 0, bit_offset=0, width=2) == 0b0000
