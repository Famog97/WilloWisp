"""
Characterization tests for auto_register_procedures — the default-flow builder
that turns a scenario's zones + IO list + nav coords into a ProcedureFlow.

Locks in the zone/nav → step mapping (which Phase 4 will replace with capability
is_applicable() queries), so that refactor can be proven equivalent.
"""
from types import SimpleNamespace

from iscs_workflow import auto_register_procedures, ProcedureType


def _sc(points=None):
    return SimpleNamespace(iscs_points=points or [])


def _names(flow):
    return [p.name for p in flow.procedures]


# ──────────────────────────────────────────────────────────────────────────────
#  Empty / minimal configs
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_config_produces_empty_flow():
    flow = auto_register_procedures(_sc(), zones_dict={}, nav={})
    assert _names(flow) == []
    assert flow.io_groups == []


def test_points_only_yield_trigger_and_reset():
    flow = auto_register_procedures(_sc([{"point_id": "PT-1"}]), zones_dict={}, nav={})
    names = _names(flow)
    assert "Trigger Alarm" in names
    assert "Reset Alarm" in names
    # No zones → no verification steps.
    assert not any("Verify" in n for n in names)


def test_alarm_panel_zone_adds_panel_and_normalize_with_dependencies():
    flow = auto_register_procedures(
        _sc([{"point_id": "PT-1"}]),
        zones_dict={"alarm_panel": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}},
        nav={},
    )
    by_name = {p.name: p for p in flow.procedures}
    assert "Verify Alarm Panel" in by_name
    assert "Verify Normalize State" in by_name
    assert by_name["Verify Alarm Panel"].depends_on == ["Trigger Alarm"]
    assert by_name["Verify Normalize State"].depends_on == ["Reset Alarm"]


# ──────────────────────────────────────────────────────────────────────────────
#  Navigation gating — step added but DISABLED when nav coords are missing
# ──────────────────────────────────────────────────────────────────────────────

def test_alarm_list_without_nav_coords_is_disabled():
    flow = auto_register_procedures(
        _sc([{"point_id": "PT-1"}]),
        zones_dict={"alarm_list": {}},
        nav={},  # no alarm_list_btn coords
    )
    verify = next(p for p in flow.procedures if p.name == "Verify Alarm List")
    assert verify.enabled is False, "no nav coords → present but disabled"


def test_alarm_list_with_nav_coords_is_enabled():
    flow = auto_register_procedures(
        _sc([{"point_id": "PT-1"}]),
        zones_dict={"alarm_list": {}},
        nav={"alarm_list_btn": {"x": -652, "y": 111}},
    )
    nav_step = next(p for p in flow.procedures if p.name == "Navigate to Alarm List")
    verify   = next(p for p in flow.procedures if p.name == "Verify Alarm List")
    assert nav_step.enabled is True
    assert verify.enabled is True
    assert nav_step.params["al_x"] == -652 and nav_step.params["al_y"] == 111


# ──────────────────────────────────────────────────────────────────────────────
#  Ordering & IO group cloning
# ──────────────────────────────────────────────────────────────────────────────

def test_orders_increment_by_ten():
    flow = auto_register_procedures(
        _sc([{"point_id": "PT-1"}]),
        zones_dict={"alarm_panel": {}},
        nav={},
    )
    orders = [p.order for p in flow.procedures]
    assert orders == sorted(orders)
    assert all(o % 10 == 0 for o in orders)


def test_one_io_group_per_point_with_cloned_steps_and_unique_ids():
    points = [
        {"point_id": "PT-1", "equipment_description": "Door", "attribute_description": "Intrusion"},
        {"point_id": "PT-2", "equipment_description": "Gate", "attribute_description": "Tamper"},
    ]
    flow = auto_register_procedures(_sc(points), zones_dict={"alarm_panel": {}}, nav={})

    assert len(flow.io_groups) == 2
    g1 = flow.get_io_group_by_point("PT-1")
    assert g1.label == "Door: Intrusion"

    template_count = len(flow.procedures)
    assert len(g1.steps) == template_count, "each group clones the full template"

    # Every step across all groups gets a unique step_id (stable referencing).
    all_step_ids = [s.step_id for g in flow.io_groups for s in g.steps]
    assert all(sid for sid in all_step_ids), "no empty step_ids"
    assert len(all_step_ids) == len(set(all_step_ids)), "step_ids are unique"


def test_io_group_clones_are_independent_deep_copies():
    flow = auto_register_procedures(
        _sc([{"point_id": "PT-1"}, {"point_id": "PT-2"}]),
        zones_dict={"alarm_panel": {}},
        nav={},
    )
    g1 = flow.get_io_group_by_point("PT-1")
    g2 = flow.get_io_group_by_point("PT-2")
    # Mutating one group's step must not affect the other (deep copy, not shared ref).
    g1.steps[0].enabled = False
    assert g2.steps[0].enabled is True
