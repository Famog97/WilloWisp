"""
Tests for P3.2 — the remaining verification capabilities ported to plugins:
verify_alarm_list, verify_event_list, verify_equipment_page,
verify_alarm_panel_custom, verify_custom. Against fakes, no live screen.
"""
from types import SimpleNamespace
from pathlib import Path

import pytest

from iscs_core import CapabilityRegistry, discover_directory, StepStatus

VERIFICATIONS = Path(__file__).resolve().parent.parent / "plugins" / "verifications"


@pytest.fixture
def reg():
    r = CapabilityRegistry()
    discover_directory(VERIFICATIONS, into=r)
    return r


def _result(status, step="alarm_list/identifier", screenshot=""):
    return SimpleNamespace(status=status, step=step, screenshot=screenshot)


# ── discovery / supersession of all remaining keys ────────────────────────────

def test_all_verifications_register(reg):
    for key in ("verify_alarm_list", "verify_event_list", "verify_equipment_page",
                "verify_alarm_panel_custom", "verify_custom"):
        assert reg.has(key), key


def test_remaining_supersede_legacy_adapters():
    import iscs_workflow as wf
    r = CapabilityRegistry()
    wf.register_legacy_capabilities(into=r)
    discover_directory(VERIFICATIONS, into=r)
    assert type(r.get("verify_alarm_list")).__name__ == "VerifyAlarmListCapability"
    assert type(r.get("verify_event_list")).__name__ == "VerifyEventListCapability"
    assert type(r.get("verify_equipment_page")).__name__ == "VerifyEquipmentPageCapability"
    assert type(r.get("verify_custom")).__name__ == "VerifyCustomCapability"


# ── alarm_list / event_list ───────────────────────────────────────────────────

def test_alarm_list_calls_backend_and_retags(reg):
    seen = {}
    class Backend:
        def verify_list(self, list_type, expected, zone, sc_dir, **kw):
            seen["type"] = list_type
            return [_result("PASS", "alarm_list/identifier")]
    ec = SimpleNamespace(zones_dict={"alarm_list": object()}, expected_alarm={"x": 1},
                         sc_dir="d", point_idx=0)
    ctx = SimpleNamespace(exec=ec, runner=SimpleNamespace(verifier=Backend(), config={}),
                          log=lambda m: None)
    out = reg.get("verify_alarm_list").execute(ctx)
    assert seen["type"] == "alarm_list"
    assert out.status is StepStatus.PASS
    assert out.data["verify_results"][0].step == "alarm_list/trigger/identifier"


def test_list_skips_without_zone(reg):
    ec = SimpleNamespace(zones_dict={}, expected_alarm={}, sc_dir="d", point_idx=0)
    ctx = SimpleNamespace(exec=ec, runner=SimpleNamespace(verifier=object(), config={}),
                          log=lambda m: None)
    assert reg.get("verify_event_list").execute(ctx).status is StepStatus.SKIP


# ── equipment ─────────────────────────────────────────────────────────────────

def test_equipment_prefixes_steps(reg):
    class Backend:
        def verify_inspector(self, expected, zone, sc_dir, **kw):
            return [_result("FAIL", "detail")]
    ec = SimpleNamespace(zones_dict={"equipment_page": object()}, expected_alarm={"x": 1},
                         sc_dir="d", point_idx=0)
    ctx = SimpleNamespace(exec=ec, runner=SimpleNamespace(verifier=Backend(), config={}),
                          log=lambda m: None)
    out = reg.get("verify_equipment_page").execute(ctx)
    assert out.status is StepStatus.FAIL
    assert out.data["verify_results"][0].step == "equipment/detail"


# ── alarm_panel_custom ────────────────────────────────────────────────────────

def test_alarm_panel_custom_uses_step_params(reg):
    seen = {}
    class Backend:
        def verify_alarm_panel(self, expected, sc_dir, **kw):
            seen["expected"], seen["kw"] = expected, kw
            return [_result("PASS", "alarm_panel/identifier", "s.png")]
    ec = SimpleNamespace(expected_alarm={"identifier": "fallback"}, sc_dir="d", point_idx=0)
    proc = SimpleNamespace(params={"expected_identifier": "ABC", "file_suffix": "custom_x"})
    ctx = SimpleNamespace(exec=ec, proc=proc,
                          runner=SimpleNamespace(verifier=Backend()), log=lambda m: None)
    out = reg.get("verify_alarm_panel_custom").execute(ctx)
    assert seen["expected"] == {"identifier": "ABC"}        # from step params, not the point
    assert seen["kw"]["file_suffix"] == "custom_x"
    assert out.status is StepStatus.PASS and out.screenshot == "s.png"


# ── verify_custom (asset binding) ─────────────────────────────────────────────

def test_custom_skips_without_binding(reg):
    ctx = SimpleNamespace(proc=SimpleNamespace(binding=None), log=lambda m: None)
    assert reg.get("verify_custom").execute(ctx).status is StepStatus.SKIP


def test_custom_runs_binding(reg, monkeypatch):
    import iscs_assets
    monkeypatch.setattr(iscs_assets, "StepBinding",
                        SimpleNamespace(from_dict=lambda d: SimpleNamespace(
                            type="TEXT", asset_id="A", region_id="R", on_fail="fail")))
    class FakeExec:
        def execute(self, b):
            return {"status": "PASS", "message": "matched", "expected": "HI",
                    "actual": "HI", "score": 1.0}
    monkeypatch.setattr(iscs_assets, "BindingExecutor", FakeExec)

    ctx = SimpleNamespace(proc=SimpleNamespace(binding={"type": "TEXT"}, name="Chk"),
                          log=lambda m: None)
    out = reg.get("verify_custom").execute(ctx)
    assert out.status is StepStatus.PASS
    vr = out.data["verify_results"][0]
    assert vr.expected == "HI" and vr.step == "Chk"
