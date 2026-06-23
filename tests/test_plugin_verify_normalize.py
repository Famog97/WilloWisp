"""
Tests for P3.2 — Verify Normalize State capability (ported from
_exec_verify_normalize). Validates the normalize-specific orchestration: correct
backend args (normalize sampler, no trigger_time, reset_ns) and the
alarm_panel/→normalize/ step re-tag. Against a fake backend, no live screen.
"""
from types import SimpleNamespace
from pathlib import Path

from iscs_core import CapabilityRegistry, discover_directory, StepStatus

VERIFICATIONS = Path(__file__).resolve().parent.parent / "plugins" / "verifications"


def _cap():
    reg = CapabilityRegistry()
    discover_directory(VERIFICATIONS, into=reg)
    return reg.get("verify_normalize")


def _ctx(backend, log=None):
    ec = SimpleNamespace(expected_norm={"identifier": "X"}, reset_idx=0, sc_dir="dir",
                         point_idx=3, norm_sampler="NS", reset_ns=999)
    return SimpleNamespace(exec=ec, runner=SimpleNamespace(verifier=backend),
                           log=log or (lambda m: None))


def test_discovers_and_supersedes_legacy():
    import iscs_workflow as wf
    reg = CapabilityRegistry()
    wf.register_legacy_capabilities(into=reg)
    assert type(reg.get("verify_normalize")).__name__ == "LegacyCapabilityAdapter"
    discover_directory(VERIFICATIONS, into=reg)
    assert type(reg.get("verify_normalize")).__name__ == "VerifyNormalizeCapability"


def test_calls_backend_with_normalize_args():
    seen = {}
    class Backend:
        def verify_alarm_panel(self, expected, sc_dir, **kw):
            seen["expected"], seen["kw"] = expected, kw
            return [SimpleNamespace(status="PASS", step="alarm_panel/datetime", screenshot="")]
    _cap().execute(_ctx(Backend()))
    assert seen["expected"] == {"identifier": "X"}          # expected_norm
    assert seen["kw"]["file_suffix"] == "alarm_panel_normalize"
    assert seen["kw"]["trigger_time"] is None
    assert seen["kw"]["sampler"] == "NS"                    # norm_sampler
    assert seen["kw"]["trigger_ns"] == 999                  # reset_ns
    assert seen["kw"]["point_idx"] == 3


def test_retags_step_names_to_normalize():
    res_obj = SimpleNamespace(status="PASS", step="alarm_panel/severity", screenshot="")
    class Backend:
        def verify_alarm_panel(self, *a, **k):
            return [res_obj]
    out = _cap().execute(_ctx(Backend()))
    assert res_obj.step == "normalize/severity"             # re-tagged in place
    assert out.status is StepStatus.PASS


def test_fail_when_any_check_fails():
    class Backend:
        def verify_alarm_panel(self, *a, **k):
            return [SimpleNamespace(status="PASS", step="alarm_panel/x", screenshot=""),
                    SimpleNamespace(status="FAIL", step="alarm_panel/y", screenshot="")]
    assert _cap().execute(_ctx(Backend())).status is StepStatus.FAIL


def test_skip_without_backend():
    cap = _cap()
    ctx = SimpleNamespace(exec=SimpleNamespace(expected_norm={"x": 1}),
                          runner=SimpleNamespace(verifier=None), log=lambda m: None)
    assert cap.execute(ctx).status is StepStatus.SKIP
