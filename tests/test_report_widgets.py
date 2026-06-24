"""
Tests for P5.1 — composable, self-describing report widgets (FR-30c / FR-30d).

The HTML templates (management / engineering / audit) are now an ordered list of
registered widgets; the engine just composes them. These tests lock in:
  - the widget registry contract (register / get / list, dup-check),
  - each built-in widget renders independently from a fixture (NFR-13),
  - a NEW widget composes into a template with no engine edit (FR-30d),
  - widget order is honoured (FR-30c reorder),
  - templates are pure widget config.

Uses the same golden input fixture as the template tests, fully offline.
"""
import json
from pathlib import Path

import pytest

import iscs_report_templates as rt

FIXTURE = Path(__file__).parent / "fixtures" / "normalize_input.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def widget_registry():
    """Snapshot/restore the global widget registry around a test."""
    saved = dict(rt._WIDGETS)
    try:
        yield rt._WIDGETS
    finally:
        rt._WIDGETS.clear()
        rt._WIDGETS.update(saved)


def _view(meta=None):
    records = rt._normalize(RAW)
    return rt.ResultView(records, rt._summary(records), meta or {"title": "T"})


# ── registry contract ─────────────────────────────────────────────────────────

def test_registry_lists_builtin_widgets_with_consumes():
    by_key = {w["key"]: w for w in rt.list_widgets()}
    assert {"header", "kpis", "failures_by_category", "failed_points",
            "summary_line", "audit_attempts", "step_traces"} <= set(by_key)
    # widgets are self-describing about the data they read
    assert by_key["kpis"]["consumes"] == ["summary"]
    assert "records" in by_key["step_traces"]["consumes"]


def test_get_unknown_widget_raises_clear_lookup_error():
    with pytest.raises(LookupError) as ei:
        rt.get_widget("nope")
    assert "nope" in str(ei.value)
    assert "header" in str(ei.value)  # lists known widgets


def test_register_requires_non_empty_key(widget_registry):
    class Bad(rt.ReportWidget):
        key = ""

    with pytest.raises(ValueError):
        rt.register_widget(Bad())


def test_duplicate_widget_rejected_unless_override(widget_registry):
    class Fake(rt.ReportWidget):
        key = "kpis"
        def render(self, view):
            return "<!-- fake kpis -->"

    with pytest.raises(ValueError):
        rt.register_widget(Fake())

    rt.register_widget(Fake(), override=True)
    assert rt.get_widget("kpis").render(_view()) == "<!-- fake kpis -->"


# ── each widget renders independently from a fixture (NFR-13) ───────────────────

@pytest.mark.parametrize("key", [
    "header", "kpis", "failures_by_category", "failed_points",
    "summary_line", "audit_attempts", "step_traces",
])
def test_each_builtin_widget_renders_a_fragment(key):
    frag = rt.get_widget(key).render(_view({"title": "T", "report_name": "R"}))
    assert isinstance(frag, str) and frag.strip()


# ── FR-30d: a NEW widget composes in with no engine edit ────────────────────────

def test_new_widget_composes_into_a_template(widget_registry):
    class BannerWidget(rt.ReportWidget):
        key = "banner"
        consumes = ("meta",)
        def render(self, view):
            return "<div class='banner'>CONFIDENTIAL</div>"

    rt.register_widget(BannerWidget())

    # Compose an ad-hoc template that includes the brand-new widget — the engine
    # (render_widgets) is unchanged; it just resolves keys from the registry.
    out = rt.render_widgets(["header", "banner", "kpis"],
                            rt._normalize(RAW), {"title": "T", "report_name": "Custom"})
    assert "CONFIDENTIAL" in out
    assert "Custom" in out          # header still rendered
    assert '<div class="v">3</div>' in out  # kpis still rendered


# ── FR-30c: widget order is honoured ────────────────────────────────────────────

def test_widget_order_is_respected():
    records = rt._normalize(RAW)
    meta = {"title": "T", "report_name": "R"}
    a = rt.render_widgets(["kpis", "summary_line"], records, meta)
    b = rt.render_widgets(["summary_line", "kpis"], records, meta)
    assert a.index('class="kpis"') < a.index("points ·")
    assert b.index("points ·") < b.index('class="kpis"')


# ── templates are pure widget config ────────────────────────────────────────────

def test_html_templates_are_defined_as_widget_lists():
    for key in ("management", "engineering", "audit"):
        entry = rt.TEMPLATES[key]
        assert "widgets" in entry and isinstance(entry["widgets"], list)
        # every referenced widget exists in the registry
        for wkey in entry["widgets"]:
            assert rt.get_widget(wkey) is not None
