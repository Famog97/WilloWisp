"""
Characterization tests for ReportManager.normalize_results — the core report
data contract (the future "ResultView" of the architecture design).

These lock in CURRENT behavior so the planned plugin/registry migration cannot
silently change how raw execution results are consolidated into report records.
They are pure-logic tests: no SCADA screen, Modbus device, or Tkinter loop.
"""
import pytest

from iscs_reports import ReportManager

normalize = ReportManager.normalize_results


# ──────────────────────────────────────────────────────────────────────────────
#  Basic shape / edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_input_returns_empty_list():
    assert normalize([]) == []


def test_item_without_point_id_is_skipped():
    # No point_id and no identifier → the record is dropped.
    assert normalize([{"overall": "PASS"}]) == []


def test_identifier_used_when_point_id_absent():
    out = normalize([{"identifier": "PT-1", "overall": "PASS"}])
    assert len(out) == 1
    assert out[0]["id"] == "PT-1"


# ──────────────────────────────────────────────────────────────────────────────
#  Workflow-engine ("steps") format
# ──────────────────────────────────────────────────────────────────────────────

def _workflow_item(**over):
    item = {
        "point_id": "BUCS-AMS-ACU-OCC-0008",
        "overall": "PASS",
        "loop_num": 1,
        "scenario_idx": 1,
        "scenario_name": "Scenario 1",
        "steps": [
            {"step": "verify_alarm_panel", "status": "PASS", "msg": "identifier found"},
            {"step": "verify_normalize",   "status": "PASS", "msg": "cleared"},
        ],
    }
    item.update(over)
    return item


def test_workflow_item_produces_single_record_with_steps():
    out = normalize([_workflow_item()])
    assert len(out) == 1
    rec = out[0]
    assert rec["id"] == "BUCS-AMS-ACU-OCC-0008"
    assert rec["overall"] == "PASS"
    assert rec["loop_num"] == 1
    assert rec["scenario_name"] == "Scenario 1"
    # Every record carries a per-attempt history (rerun preservation).
    assert len(rec["attempts"]) == 1
    assert rec["attempts"][0]["attempt"] == 0
    # Step names are humanized (underscores/slashes → spaces, title-cased).
    names = [s["name"] for s in rec["steps"]]
    assert "Verify Alarm Panel" in names


def test_explicit_step_status_is_preserved():
    item = _workflow_item(overall="FAIL")
    item["steps"][0]["status"] = "FAIL"
    item["steps"][0]["msg"] = "identifier not found"
    rec = normalize([item])[0]
    panel = next(s for s in rec["steps"] if s["name"] == "Verify Alarm Panel")
    assert panel["status"] == "FAIL"


# ──────────────────────────────────────────────────────────────────────────────
#  Rerun preservation — every attempt is kept, top-level reflects the latest
# ──────────────────────────────────────────────────────────────────────────────

def test_reruns_are_all_preserved_latest_wins():
    attempt0 = _workflow_item(overall="FAIL", rerun_attempt=0)
    attempt0["steps"][0]["status"] = "FAIL"
    attempt1 = _workflow_item(overall="PASS", rerun_attempt=1)

    out = normalize([attempt1, attempt0])  # deliberately unsorted
    assert len(out) == 1, "same (loop, scenario, point) must collapse to one record"
    rec = out[0]
    assert len(rec["attempts"]) == 2, "both attempts retained"
    assert [a["attempt"] for a in rec["attempts"]] == [0, 1], "sorted ascending by attempt"
    assert rec["overall"] == "PASS", "top-level reflects the latest (highest) attempt"
    assert rec["rerun_attempt"] == 1


def test_different_loops_stay_separate():
    a = _workflow_item(loop_num=1)
    b = _workflow_item(loop_num=2)
    out = normalize([a, b])
    assert len(out) == 2
    assert {r["loop_num"] for r in out} == {1, 2}


# ──────────────────────────────────────────────────────────────────────────────
#  Custom asset-bound checks (VERIFY_CUSTOM) flow through generically
# ──────────────────────────────────────────────────────────────────────────────

def test_custom_checks_appended_as_steps():
    item = _workflow_item(overall="FAIL")
    item["custom_checks"] = [{
        "name": "Verify HIGH ALARM label",
        "status": "FAIL",
        "message": "text not found",
        "expected": "HIGH ALARM",
        "actual": "HIGH ALRM",
        "asset_name": "TXT_HIGH",
        "asset_id": "TXT_0001",
    }]
    rec = normalize([item])[0]
    custom = [s for s in rec["steps"] if s.get("is_custom")]
    assert len(custom) == 1
    assert custom[0]["expected"] == "HIGH ALARM"
    assert custom[0]["actual"] == "HIGH ALRM"


def test_custom_fail_drives_failure_category():
    item = _workflow_item(overall="FAIL")
    item["custom_checks"] = [{"name": "x", "status": "FAIL", "message": "text not found"}]
    rec = normalize([item])[0]
    assert rec["failure_category"] == "Custom Asset Mismatch"


# ──────────────────────────────────────────────────────────────────────────────
#  Failure categorization heuristics
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg,expected_category", [
    ("color not detected",            "Color Miss"),
    ("detection timeout exceeded",    "Timeout"),
    ("datetime out of bounds",        "Datetime Out of Bounds"),
    ("identifier mismatch",           "OCR Mismatch"),
])
def test_failure_category_classification(msg, expected_category):
    item = _workflow_item(overall="FAIL")
    item["steps"] = [{"step": "verify_alarm_panel", "status": "FAIL", "msg": msg}]
    rec = normalize([item])[0]
    assert rec["failure_category"] == expected_category


def test_pass_record_has_no_failure_category():
    rec = normalize([_workflow_item(overall="PASS")])[0]
    assert rec["failure_category"] == "None"
