"""
sweep_trigger_values — the multi-alarm sweep, proven against the REAL IO points.

A classic 2-state point must still yield a single trigger (so its run is byte-for-byte
the old behaviour); a multi-state point must yield every non-baseline value so each
alarm state is triggered + verified, not just the highest.
"""
from core.services.expected_state import sweep_trigger_values, _get_state_indices


def _pt(states):
    return {"point_id": "PT", "states": states}


# value -> {label, severity, state}; mirrors what the parser extracts from v0..v7.
AMS = {0: {"label": "NORMAL", "severity": 0, "state": "N"},
       1: {"label": "ALARM",  "severity": 1, "state": "A"}}

TWP_0_0 = {0: {"label": "NOT READY", "severity": 0, "state": "N"},
           1: {"label": "READY",     "severity": 0, "state": "N"}}

ES_OPEN_CLOSE = {0: {"label": "INTERMEDIATE", "severity": 1, "state": "A"},
                 1: {"label": "CLOSE",        "severity": 0, "state": "N"},   # baseline
                 2: {"label": "OPEN",         "severity": 1, "state": "A"},
                 3: {"label": "INCONSISTENT", "severity": 1, "state": "A"}}


def test_two_state_point_sweeps_exactly_one_value():
    # AMS / TWP keep the old single-trigger run (no behaviour change).
    assert sweep_trigger_values(_pt(AMS)) == [1]
    assert sweep_trigger_values(_pt(TWP_0_0)) == [1]


def test_multi_state_point_sweeps_every_non_baseline_value():
    # ES baseline is v1 (CLOSE); all three alarms must be swept, ascending.
    assert sweep_trigger_values(_pt(ES_OPEN_CLOSE)) == [0, 2, 3]


def test_sweep_is_robust_to_json_string_keys():
    # After a suite save/load round-trip the keys come back as strings.
    es_str = {str(k): v for k, v in ES_OPEN_CLOSE.items()}
    assert sweep_trigger_values(_pt(es_str)) == [0, 2, 3]


def test_single_state_point_triggers_itself():
    one = {0: {"label": "ONLY", "severity": 1, "state": "A"}}
    assert sweep_trigger_values(_pt(one)) == [0]


def test_missing_states_falls_back_to_default_trigger():
    # No states at all -> _get_state_indices defaults to (1, 0); sweep is its trigger.
    trig, _ = _get_state_indices({"point_id": "X"})
    assert sweep_trigger_values({"point_id": "X"}) == [trig]


def test_sweep_excludes_the_baseline_it_resets_to():
    # The swept values must never include the reset/baseline value.
    _, reset_idx = _get_state_indices(_pt(ES_OPEN_CLOSE))
    assert reset_idx == 1
    assert reset_idx not in sweep_trigger_values(_pt(ES_OPEN_CLOSE))
