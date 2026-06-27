"""
Tests for the Phase-1 capability bridge in iscs_workflow (P1.2):
LegacyCapabilityAdapter + register_legacy_capabilities + the single-source
_LEGACY_METHOD_MAP that also drives runtime dispatch.

Verifies the wrapping is complete and behavior-preserving WITHOUT needing a live
SCADA screen — the adapter is exercised against a fake runner.
"""
import pytest

import iscs_workflow as wf
from iscs_workflow import (
    ProcedureType, ProcedureStatus, _LEGACY_METHOD_MAP, _category_for,
    LegacyCapabilityAdapter, LegacyExecContext, register_legacy_capabilities,
)
from adapters.driven.input import legacy_executors as _legacy_exec
from iscs_core import CapabilityRegistry, StepStatus, StepResult


# ──────────────────────────────────────────────────────────────────────────────
#  Map completeness & dispatch integrity
# ──────────────────────────────────────────────────────────────────────────────

def test_map_covers_every_procedure_type():
    # Every ProcedureType must have exactly one executor mapping (no gaps).
    assert set(_LEGACY_METHOD_MAP) == set(ProcedureType)


def test_every_mapped_method_exists_in_adapter():
    # M3.4: executors moved to the input adapter; getattr(legacy_executors, method)
    # must resolve for both the LegacyCapabilityAdapter and the dispatcher fallback.
    for proc_type, method_name in _LEGACY_METHOD_MAP.items():
        assert hasattr(_legacy_exec, method_name), \
            f"{proc_type.value} → missing executor {method_name}"
        assert not hasattr(wf.ProcedureRunner, method_name), \
            f"{method_name} should no longer live on the engine"


@pytest.mark.parametrize("proc_type,expected", [
    (ProcedureType.TRIGGER_ALARM, "action"),
    (ProcedureType.NAVIGATE_EQUIP_PAGE, "action"),
    (ProcedureType.VERIFY_ALARM_PANEL, "verification"),
    (ProcedureType.VERIFY_NORMALIZE, "verification"),
    (ProcedureType.VERIFY_CUSTOM, "verification"),
    (ProcedureType.DELAY, "utility"),
    (ProcedureType.SCREENSHOT, "utility"),
])
def test_category_classification(proc_type, expected):
    assert _category_for(proc_type) == expected


# ──────────────────────────────────────────────────────────────────────────────
#  Registration
# ──────────────────────────────────────────────────────────────────────────────

def test_register_into_fresh_registry_registers_all_keys():
    reg = CapabilityRegistry()
    register_legacy_capabilities(into=reg)
    assert set(reg.keys()) == {pt.value for pt in ProcedureType}
    assert len(reg.keys()) == 19


def test_registration_is_idempotent():
    reg = CapabilityRegistry()
    register_legacy_capabilities(into=reg)
    # second call must not raise DuplicateCapabilityError
    register_legacy_capabilities(into=reg)
    assert len(reg.keys()) == 19


def test_import_auto_registered_into_global_registry():
    from iscs_core import registry as global_reg
    # importing iscs_workflow at module load registered the adapters
    assert global_reg.has("verify_alarm_panel")
    assert isinstance(global_reg.get("verify_alarm_panel"), LegacyCapabilityAdapter)


# ──────────────────────────────────────────────────────────────────────────────
#  Adapter execution — forwards to the executor, normalizes the return
# ──────────────────────────────────────────────────────────────────────────────

def test_adapter_forwards_and_maps_pass(monkeypatch):
    # M3.4: the adapter resolves the executor on the legacy_executors module and
    # passes the runner explicitly; stub it there.
    calls = []

    def _exec_stub(runner, proc, exec_ctx, sampler_ok, log):
        calls.append((runner, proc, exec_ctx, sampler_ok))
        log("ran stub")
        return ProcedureStatus.PASS, [{"step": "x"}], "shot.png"

    monkeypatch.setattr(_legacy_exec, "_exec_stub", _exec_stub, raising=False)
    adapter = LegacyCapabilityAdapter(ProcedureType.CLICK, "_exec_stub")
    ctx = LegacyExecContext(runner="RUNNER", proc="PROC", exec="EXEC", sampler_ok=True)

    result = adapter.execute(ctx)

    assert isinstance(result, StepResult)
    assert result.status is StepStatus.PASS
    assert result.screenshot == "shot.png"
    assert result.data["verify_results"] == [{"step": "x"}]
    assert calls == [("RUNNER", "PROC", "EXEC", True)]   # runner forwarded explicitly


def test_adapter_maps_lowercase_error_status_by_name(monkeypatch):
    # ProcedureStatus.ERROR == "error" but StepStatus.ERROR == "ERROR".
    monkeypatch.setattr(_legacy_exec, "_exec_stub",
                        lambda runner, proc, exec_ctx, sampler_ok, log: (ProcedureStatus.ERROR, [], ""),
                        raising=False)
    adapter = LegacyCapabilityAdapter(ProcedureType.DELAY, "_exec_stub")
    result = adapter.execute(LegacyExecContext(runner=None, proc=None, exec=None))
    assert result.status is StepStatus.ERROR


def test_adapter_metadata_has_key_and_category():
    adapter = LegacyCapabilityAdapter(ProcedureType.VERIFY_ALARM_PANEL, "_exec_x")
    assert adapter.key == "verify_alarm_panel"
    assert adapter.meta.category == "verification"
    assert adapter.meta.name  # non-empty label for the UI
