"""
Tests for P1.3 — ProcedureRunner._execute_procedure routing through the
capability registry, with fallback to the direct legacy executor.

Constructs a ProcedureRunner with dummy collaborators (no live screen/device) and
drives a single step, swapping the module-level registry to observe routing.
"""
import threading

import pytest

import iscs_workflow as wf
from iscs_workflow import ProcedureType, ProcedureStatus, ProcedureCategory, Procedure
from adapters.driven.input import legacy_executors as _legacy_exec
from core.services import engine as _eng   # M3.4: dispatcher reads core_registry here
from iscs_core import CapabilityRegistry, CapabilityMeta, StepResult, StepStatus


def _runner():
    return wf.ProcedureRunner(
        flow=None, verifier=None, handler=None, config={},
        on_log=lambda m: None,
        stop_event=threading.Event(), pause_event=threading.Event(),
    )


def _proc(ptype=ProcedureType.DELAY):
    return Procedure(proc_type=ptype, category=ProcedureCategory.UTILITY, name="Step")


# ──────────────────────────────────────────────────────────────────────────────
#  Registry path
# ──────────────────────────────────────────────────────────────────────────────

def test_execute_routes_through_registry(monkeypatch):
    seen = []

    class Spy:
        key = ProcedureType.DELAY.value
        meta = CapabilityMeta(name="Spy", category="utility")
        def execute(self, ctx):
            seen.append(ctx)
            return StepResult(StepStatus.FAIL, message="spy ran",
                              screenshot="s.png", data={"verify_results": [{"a": 1}]})

    reg = CapabilityRegistry()
    reg.register(Spy())
    monkeypatch.setattr(_eng, "core_registry", reg)

    runner = _runner()
    # If routing used the legacy method instead of the registry, this would fire:
    runner._exec_delay = lambda *a, **k: pytest.fail("legacy method called, not the registry")

    result = runner._execute_procedure(_proc(), ctx=object(), sampler_ok=False)

    assert len(seen) == 1, "capability.execute was invoked"
    # StepResult mapped back into the legacy ProcedureResult shape:
    assert result.status == ProcedureStatus.FAIL
    assert result.verify_results == [{"a": 1}]
    assert result.screenshot_path == "s.png"
    # The context handed to the capability carried the runner + proc.
    assert seen[0].runner is runner


def test_step_status_error_round_trips_to_procedure_status(monkeypatch):
    class ErrCap:
        key = ProcedureType.DELAY.value
        meta = CapabilityMeta(name="Err", category="utility")
        def execute(self, ctx):
            return StepResult(StepStatus.ERROR, message="boom")

    reg = CapabilityRegistry()
    reg.register(ErrCap())
    monkeypatch.setattr(_eng, "core_registry", reg)

    result = _runner()._execute_procedure(_proc(), ctx=object(), sampler_ok=False)
    assert result.status == ProcedureStatus.ERROR


# ──────────────────────────────────────────────────────────────────────────────
#  Fallback path
# ──────────────────────────────────────────────────────────────────────────────

def test_falls_back_to_legacy_when_key_unregistered(monkeypatch):
    monkeypatch.setattr(_eng, "core_registry", CapabilityRegistry())  # empty → no cap

    runner = _runner()
    called = []

    # M3.4: the legacy executors live in the input adapter and take the runner
    # explicitly; the dispatcher resolves them there, so stub it there.
    def fake_exec_delay(runner_arg, proc, ctx, sampler_ok, log):
        called.append((proc, sampler_ok))
        return ProcedureStatus.PASS, [], "legacy.png"

    monkeypatch.setattr(_legacy_exec, "_exec_delay", fake_exec_delay)

    result = runner._execute_procedure(_proc(), ctx=object(), sampler_ok=True)

    assert called and called[0][1] is True, "legacy executor was used as fallback"
    assert result.status == ProcedureStatus.PASS
    assert result.screenshot_path == "legacy.png"


def test_falls_back_when_registry_is_none(monkeypatch):
    monkeypatch.setattr(_eng, "core_registry", None)  # simulate iscs_core unavailable

    monkeypatch.setattr(_legacy_exec, "_exec_delay",
                        lambda *a, **k: (ProcedureStatus.SKIP, [], ""))
    result = _runner()._execute_procedure(_proc(), ctx=object(), sampler_ok=False)
    assert result.status == ProcedureStatus.SKIP


def test_unknown_proc_type_with_empty_registry_errors(monkeypatch):
    # No capability AND no legacy method → caught and surfaced as ERROR.
    monkeypatch.setattr(_eng, "core_registry", CapabilityRegistry())

    runner = _runner()
    bad = _proc()
    object.__setattr__(bad, "proc_type", _Unmapped())  # a proc_type not in the map
    result = runner._execute_procedure(bad, ctx=object(), sampler_ok=False)
    assert result.status == ProcedureStatus.ERROR
    assert "No executor" in result.error_detail


class _Unmapped:
    """A fake proc_type whose .value is absent from _LEGACY_METHOD_MAP."""
    value = "totally_unknown_step"
    name = "TOTALLY_UNKNOWN_STEP"
