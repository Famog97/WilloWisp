"""
M3.6 — WilloWispCoreAPI facade (the single inbound gate, R-HEX-1).

Wires the facade with the real core services (a fresh capability registry with the
discovered plugins, a ConfigProvider, the EventBus, the report-templates module, and
the relocated default-flow builder) and exercises the catalogue / config / reporting
/ default-flow / event surfaces — all **headless** (no GUI toolkit loaded).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iscs_core import CapabilityRegistry, EventBus, discover_directory
from core.api import WilloWispCoreAPI
from core.services.config import ConfigProvider
from core.services.import_service import auto_register_procedures
import iscs_report_templates as templates

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def api(tmp_path):
    reg = CapabilityRegistry()
    for cat in ("actions", "verifications", "utilities"):
        discover_directory(ROOT / "plugins" / cat, into=reg)
    cfg = ConfigProvider(tmp_path / "config.json")   # fresh — built-in defaults
    return WilloWispCoreAPI(
        registry=reg, config_provider=cfg, event_bus=EventBus(),
        templates=templates, default_flow_builder=auto_register_procedures)


# ── catalogue ───────────────────────────────────────────────────────────────

def test_list_step_types(api):
    keys = {t["key"] for t in api.list_step_types()}
    assert {"trigger_alarm", "reset_alarm", "delay", "verify_alarm_panel"} <= keys
    assert all(isinstance(t["params_schema"], dict) for t in api.list_step_types())


def test_get_param_schema(api):
    assert isinstance(api.get_param_schema("delay"), dict)


def test_list_report_templates(api):
    keys = {t["key"] for t in api.list_report_templates()}
    assert {"legacy", "management", "json"} <= keys


# ── config ──────────────────────────────────────────────────────────────────

def test_config_get_update(api):
    assert "grid_spacing" in api.get_config()
    api.update_config({"grid_spacing": 99})
    assert api.get_config()["grid_spacing"] == 99


# ── default flow ─────────────────────────────────────────────────────────────

def test_build_default_flow(api):
    sc = SimpleNamespace(iscs_points=[{"point_id": "P1"}])
    flow = api.build_default_flow(sc, {"alarm_panel": {}}, {})
    names = [p.name for p in flow.procedures]
    assert "Trigger Alarm" in names and "Verify Alarm Panel" in names


# ── reporting ────────────────────────────────────────────────────────────────

def test_generate_report(api, tmp_path):
    raw = json.loads((ROOT / "tests" / "fixtures" / "normalize_input.json").read_text(encoding="utf-8"))
    out = api.generate_report("management", raw, tmp_path, title="Facade")
    assert Path(out).exists()


# ── events ───────────────────────────────────────────────────────────────────

def test_event_dispatcher_emit(api):
    seen = []
    api.set_event_dispatcher(SimpleNamespace(dispatch=lambda fn, *a, **k: seen.append(a)))
    api.emit(lambda x: None, 5)
    assert seen == [(5,)]


def test_subscribe_delivers(api):
    from iscs_core import SuiteCompleted
    got = []
    api.subscribe(SuiteCompleted, lambda e: got.append(e))
    api._bus.publish(SuiteCompleted(results=[], output_dir="", title="t",
                                    start_time=None, end_time=None))
    assert len(got) == 1


# ── run not wired ─────────────────────────────────────────────────────────────

def test_run_methods_require_wiring(api):
    with pytest.raises(RuntimeError):
        api.start_suite()
