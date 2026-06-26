"""
M0.1 — Characterization golden for auto_register_procedures.

Pins the COMPLETE default-flow structure (all zones + nav present) as a committed
golden, so the future DefaultFlowBuilder (rule-per-step, M3.3) can be proven to
reproduce it byte-for-byte. Complements the behavioral assertions in
test_workflow_autoregister.py.

Volatile ids (step_id/io_id, from module-global counters) are normalized out.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from iscs_workflow import auto_register_procedures

GOLDEN = Path(__file__).parent / "fixtures" / "autoregister_golden.json"


def _full_scenario():
    points = [{"point_id": "PT-1", "equipment_description": "Door",
               "attribute_description": "Intrusion"}]
    zones = {"alarm_panel": {}, "alarm_list": {}, "event_list": {}, "equipment_page": {}}
    nav = {
        "home_btn": {"x": 10, "y": 20},
        "alarm_list_btn": {"x": 30, "y": 40},
        "event_list_btn": {"x": 50, "y": 60},
        "rightclick_row1": {"x": 70, "y": 80},
        "rightclick_page_btn": {"x": 90, "y": 100},
    }
    return SimpleNamespace(iscs_points=points), zones, nav


def _normalized_structure(flow):
    """Deterministic view: the template procedures + per-group step names.
    Excludes volatile ids so the golden is stable across runs."""
    return {
        "template": [
            {"proc_type": p.proc_type.value, "name": p.name, "order": p.order,
             "enabled": p.enabled, "depends_on": list(p.depends_on),
             "params": p.params}
            for p in flow.procedures
        ],
        "io_groups": [
            {"point_id": g.point_id, "label": g.label,
             "step_names": [s.name for s in g.steps]}
            for g in flow.io_groups
        ],
    }


def test_auto_register_full_flow_matches_golden():
    sc, zones, nav = _full_scenario()
    current = _normalized_structure(auto_register_procedures(sc, zones, nav))

    if not GOLDEN.exists():
        GOLDEN.write_text(json.dumps(current, indent=2), encoding="utf-8")

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert current == expected, (
        "auto_register output drifted from the golden. If intentional, delete "
        f"{GOLDEN.name} and regenerate.")
