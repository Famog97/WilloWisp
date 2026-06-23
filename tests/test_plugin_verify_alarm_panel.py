"""
Tests for P3.2 — the Verify Alarm Panel capability (orchestration decomposed out
of the engine; OCR work delegated to a VerificationBackend).

Exercised against a FAKE backend (no live screen): proves the orchestration
(skip rules, status interpretation, screenshot pick, result pass-through) matches
the legacy _exec_verify_alarm_panel, and that the plugin supersedes its adapter.
The live run validates real OCR/colour behavior is unchanged.
"""
from types import SimpleNamespace
from pathlib import Path

from iscs_core import CapabilityRegistry, discover_directory, StepStatus

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFICATIONS = REPO_ROOT / "plugins" / "verifications"


def _cap():
    reg = CapabilityRegistry()
    discover_directory(VERIFICATIONS, into=reg)
    return reg.get("verify_alarm_panel")


def _result(status, screenshot=""):
    return SimpleNamespace(status=status, screenshot=screenshot)


def _ctx(backend, expected_alarm={"identifier": "X"}, log=None):
    ec = SimpleNamespace(expected_alarm=expected_alarm, trigger_idx=1, sc_dir="dir",
                         point_idx=2, trigger_time=None, sampler=None, trigger_ns=None)
    return SimpleNamespace(exec=ec, runner=SimpleNamespace(verifier=backend),
                           log=log or (lambda m: None))


# ── discovery / supersession ──────────────────────────────────────────────────

def test_capability_discovers_under_key():
    cap = _cap()
    assert type(cap).__name__ == "VerifyAlarmPanelCapability"
    assert cap.meta.category == "verification"


def test_supersedes_legacy_adapter():
    import iscs_workflow as wf
    reg = CapabilityRegistry()
    wf.register_legacy_capabilities(into=reg)
    assert type(reg.get("verify_alarm_panel")).__name__ == "LegacyCapabilityAdapter"
    discover_directory(VERIFICATIONS, into=reg)
    assert type(reg.get("verify_alarm_panel")).__name__ == "VerifyAlarmPanelCapability"


# ── orchestration ─────────────────────────────────────────────────────────────

def test_pass_when_all_checks_pass():
    calls = {}
    class Backend:
        def verify_alarm_panel(self, expected, sc_dir, **kw):
            calls["expected"], calls["sc_dir"], calls["kw"] = expected, sc_dir, kw
            return [_result("PASS", "a.png"), _result("PASS")]
    res = _cap().execute(_ctx(Backend()))
    assert res.status is StepStatus.PASS
    assert res.screenshot == "a.png"
    assert len(res.data["verify_results"]) == 2
    # backend called with the trigger args (matches legacy _exec_verify_alarm_panel)
    assert calls["kw"]["file_suffix"] == "alarm_panel_trigger"
    assert calls["kw"]["point_idx"] == 2


def test_fail_when_any_check_fails():
    class Backend:
        def verify_alarm_panel(self, expected, sc_dir, **kw):
            return [_result("PASS"), _result("FAIL", "f.png")]
    res = _cap().execute(_ctx(Backend()))
    assert res.status is StepStatus.FAIL


def test_skip_without_expected_state():
    class Backend:
        def verify_alarm_panel(self, *a, **k):  # should not be called
            raise AssertionError("backend should not run when nothing expected")
    res = _cap().execute(_ctx(Backend(), expected_alarm={}))
    assert res.status is StepStatus.SKIP


def test_skip_without_backend():
    cap = _cap()
    ctx = SimpleNamespace(exec=SimpleNamespace(expected_alarm={"x": 1}),
                          runner=SimpleNamespace(verifier=None), log=lambda m: None)
    assert cap.execute(ctx).status is StepStatus.SKIP


def test_logs_progress_and_outcome():
    logs = []
    class Backend:
        def verify_alarm_panel(self, *a, **k):
            return [_result("PASS"), _result("PASS")]
    _cap().execute(_ctx(Backend(), log=logs.append))
    assert any("TRIGGER state" in m for m in logs)
    assert any("2/2 checks passed" in m for m in logs)
