"""
Tests for P6.1 — flow schema versioning (FR-27).

Covers the on-disk version tag, backward compatibility with pre-versioning saved
flows (no schema_version), rejection of future versions, and the chained
migration mechanism. Pure serialization logic — no runtime/execution path.
"""
import pytest

from iscs_workflow import (
    ProcedureFlow, Procedure, ProcedureType, ProcedureCategory,
    FLOW_SCHEMA_VERSION, _migrate_flow_dict,
)


def _proc(name="Trigger", order=10):
    return Procedure(ProcedureType.TRIGGER_ALARM, ProcedureCategory.ACTION, name, order=order)


# ──────────────────────────────────────────────────────────────────────────────
#  Version tag on serialize
# ──────────────────────────────────────────────────────────────────────────────

def test_to_dict_includes_current_schema_version():
    d = ProcedureFlow(procedures=[_proc()]).to_dict()
    assert d["schema_version"] == FLOW_SCHEMA_VERSION


def test_round_trip_preserves_flow_with_version():
    flow = ProcedureFlow(procedures=[_proc("A", 10), _proc("B", 20)])
    flow2 = ProcedureFlow.from_dict(flow.to_dict())
    assert [p.name for p in flow2.procedures] == ["A", "B"]


# ──────────────────────────────────────────────────────────────────────────────
#  Backward compatibility — legacy data has no schema_version
# ──────────────────────────────────────────────────────────────────────────────

def test_legacy_dict_without_version_still_loads():
    # Saved by a build that predates versioning — must load as the current shape.
    legacy = {"procedures": [
        {"proc_type": "trigger_alarm", "category": "action", "name": "Trig", "order": 10},
    ]}
    flow = ProcedureFlow.from_dict(legacy)
    assert [p.name for p in flow.procedures] == ["Trig"]


# ──────────────────────────────────────────────────────────────────────────────
#  Future version is rejected, not silently mangled
# ──────────────────────────────────────────────────────────────────────────────

def test_future_version_raises_clear_error():
    future = {"schema_version": FLOW_SCHEMA_VERSION + 5, "procedures": []}
    with pytest.raises(ValueError) as ei:
        ProcedureFlow.from_dict(future)
    assert "newer than supported" in str(ei.value)


# ──────────────────────────────────────────────────────────────────────────────
#  Migration chain mechanism (tested independently of the real version)
# ──────────────────────────────────────────────────────────────────────────────

def test_migration_chain_applies_in_sequence():
    # Simulate upgrading a v1 dict to a (hypothetical) v3 via two migrators.
    calls = []

    def v1_to_v2(d):
        calls.append("1→2")
        d = dict(d); d["added_in_v2"] = True; return d

    def v2_to_v3(d):
        calls.append("2→3")
        d = dict(d); d["added_in_v3"] = True; return d

    migrators = {1: v1_to_v2, 2: v2_to_v3}
    src = {"schema_version": 1, "procedures": []}
    out = _migrate_flow_dict(src, migrators=migrators, current=3)

    assert calls == ["1→2", "2→3"]
    assert out["added_in_v2"] and out["added_in_v3"]


def test_missing_migrator_raises_clear_error():
    src = {"schema_version": 1, "procedures": []}
    with pytest.raises(ValueError) as ei:
        _migrate_flow_dict(src, migrators={}, current=2)   # no 1→2 migrator
    assert "No migrator" in str(ei.value)


def test_already_current_needs_no_migration():
    src = {"schema_version": 2, "procedures": []}
    # current == 2, version == 2 → returned unchanged, no migrators consulted
    assert _migrate_flow_dict(src, migrators={}, current=2) is src
