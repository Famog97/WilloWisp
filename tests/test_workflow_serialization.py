"""
Characterization tests for the ProcedureFlow serialization contract
(Procedure / IOGroup / ProcedureFlow to_dict/from_dict + to_json/from_json).

This is the BACKWARD-COMPATIBILITY contract: saved flows and templates must
round-trip without loss, and unknown step types from newer/older versions must
degrade gracefully (skip) rather than crash. Locking this in protects FR-22/23/27
before any registry migration touches step types.
"""
import json

from iscs_workflow import (
    Procedure, ProcedureType, ProcedureCategory, IOGroup, ProcedureFlow,
)


def _proc(name="Trigger Alarm", ptype=ProcedureType.TRIGGER_ALARM, order=10, **kw):
    return Procedure(
        proc_type=ptype,
        category=ProcedureCategory.ACTION if "ACTION" in dir(ProcedureCategory) else list(ProcedureCategory)[0],
        name=name,
        order=order,
        **kw,
    )


# ──────────────────────────────────────────────────────────────────────────────
#  Procedure round-trip
# ──────────────────────────────────────────────────────────────────────────────

def test_procedure_round_trip_preserves_fields():
    p = _proc(params={"delay_sec": 2}, depends_on=["A"], step_id="STP_0001",
              description="hello")
    p2 = Procedure.from_dict(p.to_dict())
    assert p2 is not None
    assert p2.proc_type == p.proc_type
    assert p2.name == p.name
    assert p2.order == p.order
    assert p2.params == {"delay_sec": 2}
    assert p2.depends_on == ["A"]
    assert p2.step_id == "STP_0001"
    assert p2.description == "hello"


def test_procedure_binding_omitted_when_none_present_when_set():
    p = _proc()
    assert "binding" not in p.to_dict()        # None → key omitted

    p.binding = {"type": "TEXT", "asset_id": "TXT_0001"}
    d = p.to_dict()
    assert d["binding"] == {"type": "TEXT", "asset_id": "TXT_0001"}
    assert Procedure.from_dict(d).binding == p.binding


def test_unknown_proc_type_kept_as_dynamic():
    # P6.3: an unknown key is KEPT as a dynamic type (a plugin may provide it),
    # not dropped — so it round-trips without data loss.
    p = Procedure.from_dict({"proc_type": "warp_drive", "category": "action",
                             "name": "Warp"})
    assert p is not None
    assert p.proc_type.value == "warp_drive"
    assert p.name == "Warp"
    assert p.to_dict()["proc_type"] == "warp_drive"   # round-trips


def test_missing_proc_type_returns_none():
    # A malformed entry with no type is still dropped.
    assert Procedure.from_dict({"category": "action", "name": "X"}) is None


def test_unknown_category_falls_back_to_utility():
    p = Procedure.from_dict({"proc_type": "delay", "category": "nonsense",
                             "name": "Wait"})
    assert p is not None
    assert p.category == ProcedureCategory.UTILITY


# ──────────────────────────────────────────────────────────────────────────────
#  IOGroup round-trip
# ──────────────────────────────────────────────────────────────────────────────

def test_iogroup_round_trip_and_ordering():
    g = IOGroup(io_id="IO_0001", point_id="PT-1", label="Door: Intrusion")
    g.steps = [_proc("B", order=20), _proc("A", order=10)]
    g2 = IOGroup.from_dict(g.to_dict())
    assert g2.io_id == "IO_0001"
    assert g2.point_id == "PT-1"
    # to_dict serializes in execution order → A (10) before B (20)
    assert [s.name for s in g2.steps] == ["A", "B"]


def test_iogroup_keeps_unknown_steps_as_dynamic():
    d = {
        "io_id": "IO_0001", "point_id": "PT-1", "label": "",
        "steps": [
            {"proc_type": "trigger_alarm", "category": "action", "name": "Trig", "order": 10},
            {"proc_type": "warp_drive",    "category": "action", "name": "Warp", "order": 20},
        ],
    }
    g = IOGroup.from_dict(d)
    # P6.3: the unknown step is kept (a plugin may provide "warp_drive"), not dropped.
    assert [s.name for s in g.steps] == ["Trig", "Warp"]
    assert g.steps[1].proc_type.value == "warp_drive"


# ──────────────────────────────────────────────────────────────────────────────
#  ProcedureFlow round-trip (JSON)
# ──────────────────────────────────────────────────────────────────────────────

def test_flow_json_round_trip():
    flow = ProcedureFlow(
        procedures=[_proc("Trigger Alarm", order=10), _proc("Reset Alarm",
                    ptype=ProcedureType.RESET_ALARM, order=20)],
        io_groups=[IOGroup(io_id="IO_0001", point_id="PT-1",
                           steps=[_proc("Verify", ptype=ProcedureType.VERIFY_ALARM_PANEL, order=10)])],
    )
    flow2 = ProcedureFlow.from_json(flow.to_json())
    assert [p.name for p in flow2.procedures] == ["Trigger Alarm", "Reset Alarm"]
    assert len(flow2.io_groups) == 1
    assert flow2.io_groups[0].point_id == "PT-1"


def test_flow_to_dict_omits_empty_io_groups():
    flow = ProcedureFlow(procedures=[_proc()])
    assert "io_groups" not in flow.to_dict()


def test_flow_with_unknown_top_level_step_does_not_crash():
    # A flow with a newer/plugin step type must load without crashing. Since P6.3
    # the unknown step is KEPT as a dynamic type (it round-trips and will execute
    # via the registry, or surface a clear ERROR if nothing handles it).
    d = {"procedures": [
        {"proc_type": "trigger_alarm", "category": "action", "name": "Trig", "order": 10},
        {"proc_type": "warp_drive",    "category": "action", "name": "Warp", "order": 20},
    ]}
    flow = ProcedureFlow.from_dict(d)
    assert [p.name for p in flow.procedures] == ["Trig", "Warp"]
