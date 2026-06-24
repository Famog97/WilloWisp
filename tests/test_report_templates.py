"""
Tests for Phase 5 — pluggable report templates (FR-30) rendered from results.

Uses the existing golden input fixture (4 raw items → 3 normalized records incl. a
rerun and a custom-asset failure) so templates are exercised on realistic data,
fully offline (NFR-13). The legacy Suite_Report.html is untouched and unrelated.
"""
import json
from pathlib import Path

import pytest

import iscs_report_templates as rt

FIXTURE = Path(__file__).parent / "fixtures" / "normalize_input.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_template_registry_lists_audiences():
    keys = {t["key"] for t in rt.list_templates()}
    assert {"management", "engineering", "audit", "json", "pdf"} <= keys


def test_engineering_renders_full_step_traces():
    html = rt.render_html("engineering", RAW, title="Eng Run")
    assert "Engineering Report" in html
    # full per-step detail present (a step name from the fixture)
    assert "Verify Alarm Panel" in html or "verify_alarm_panel" in html.lower()


def test_json_output_is_valid_and_structured():
    import json as _j
    out = _j.loads(rt.render_html("json", RAW, title="Data Run"))
    assert out["title"] == "Data Run"
    assert out["summary"]["total"] == 3
    assert "failures_by_category" in out["summary"]
    assert isinstance(out["points"], list) and len(out["points"]) == 3


def test_unknown_template_raises():
    with pytest.raises(KeyError):
        rt.render_html("nope", RAW)


def test_dict_input_gives_clear_error_not_attributeerror():
    # Regression: picking a generated Results.json ({"points": [...]}) instead of a
    # suite_results.json (a list) used to fail with a cryptic
    # "'str' object has no attribute 'get'" deep in normalize_results.
    bad = {"title": "T", "summary": {"total": 1}, "points": [{"id": "P1", "overall": "PASS"}]}
    with pytest.raises(ValueError) as ei:
        rt.render_html("management", bad)
    assert "suite_results.json" in str(ei.value)
    # also on the PDF/write path
    with pytest.raises(ValueError):
        rt.generate_template_report("pdf", bad, ".")


# ── management summary ────────────────────────────────────────────────────────

def test_management_renders_kpis_and_pass_rate():
    html = rt.render_html("management", RAW, title="Demo Run")
    assert "Management Summary" in html
    assert "Demo Run" in html
    assert "Pass rate" in html
    # 3 records: 0008/loop1 PASS, 0009/loop1 PASS (after rerun), 0008/loop2 FAIL
    assert "<div class=\"v\">3</div>" in html          # total points
    assert "Pass rate" in html


def test_management_shows_failure_category():
    html = rt.render_html("management", RAW)
    # the loop-2 point fails on a custom asset check
    assert "Custom Asset Mismatch" in html


# ── audit ─────────────────────────────────────────────────────────────────────

def test_audit_lists_every_attempt():
    html = rt.render_html("audit", RAW)
    assert "Audit Record" in html
    # the rerun point has two attempts (FAIL then PASS) → both rows present
    assert html.count("BUCS-AMS-ACU-OCC-0009") >= 2


# ── file generation + escaping ────────────────────────────────────────────────

def test_picker_core_generates_every_template(tmp_path):
    # Mirrors what the UI report picker's Generate button does: read a saved
    # suite_results.json and generate the chosen template to a file.
    import importlib.util
    have_fpdf = importlib.util.find_spec("fpdf") is not None
    src = tmp_path / "suite_results.json"
    src.write_text(json.dumps(RAW), encoding="utf-8")
    raw = json.loads(src.read_text(encoding="utf-8"))
    for key in [t["key"] for t in rt.list_templates()]:
        if key == "pdf" and not have_fpdf:
            continue   # PDF needs fpdf2; the picker surfaces a clear install message
        out = rt.generate_template_report(key, raw, src.parent, title="T")
        assert out.exists(), key


def test_pdf_generates_when_fpdf_available(tmp_path):
    pytest.importorskip("fpdf", reason="PDF export needs fpdf2 (pip install fpdf2)")
    out = rt.generate_template_report("pdf", RAW, tmp_path, title="PDF Run")
    assert out.exists() and out.suffix == ".pdf"
    assert out.read_bytes()[:4] == b"%PDF"


def test_pdf_render_html_rejected_as_binary():
    # render_html is for text templates; PDF must go through generate_template_report.
    with pytest.raises(ValueError):
        rt.render_html("pdf", RAW)


def test_generate_writes_file(tmp_path):
    path = rt.generate_template_report("management", RAW, tmp_path, title="T")
    assert path.exists()
    assert path.name == "Management_Summary.html"
    assert "<html" in path.read_text(encoding="utf-8").lower()


def test_html_is_escaped_against_injection():
    raw = [{"point_id": "<script>x</script>", "overall": "FAIL", "loop_num": 1,
            "scenario_name": "S", "steps": [
                {"step": "verify_alarm_panel", "status": "FAIL", "msg": "boom"}]}]
    html = rt.render_html("audit", raw)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
