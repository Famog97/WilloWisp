"""
Tests for P2.2 — ProcedureRunner emits lifecycle events on the EventBus.

Drives a single step through _execute_procedure (with a stub executor, no live
screen/device) and asserts the StepStarted / StepCompleted / Verification* events
fire. Also verifies emission is isolated (a bad subscriber can't break a run) and
that the runner defaults to the shared global bus.

M3.4: the legacy executors moved to adapters/driven/input/legacy_executors.py and
take the runner explicitly, so stubs are injected there (was runner._exec_*).
"""
import threading

import iscs_workflow as wf
from iscs_workflow import ProcedureType, ProcedureStatus, ProcedureCategory, Procedure
from adapters.driven.input import legacy_executors as le
from core.services import engine as _eng   # M3.4: dispatcher reads core_registry here
from iscs_core import (
    EventBus, CapabilityRegistry,
    StepStarted, StepCompleted, VerificationPassed, VerificationFailed,
)


def _runner(bus=None):
    return wf.ProcedureRunner(
        flow=None, verifier=None, handler=None, config={},
        on_log=lambda m: None,
        stop_event=threading.Event(), pause_event=threading.Event(),
        event_bus=bus,
    )


def _force_legacy(monkeypatch):
    # Empty registry → _execute_procedure falls back to the (stubbed) legacy executor.
    monkeypatch.setattr(_eng, "core_registry", CapabilityRegistry())


def _stub(monkeypatch, method_name, ret):
    """Install a stub legacy executor (signature: runner, proc, ctx, sampler_ok, log)."""
    monkeypatch.setattr(le, method_name, lambda runner, proc, ctx, so, log: ret)


def test_step_started_and_completed_emitted(monkeypatch):
    bus = EventBus()
    started, completed = [], []
    bus.subscribe(StepStarted, started.append)
    bus.subscribe(StepCompleted, completed.append)
    _force_legacy(monkeypatch)
    _stub(monkeypatch, "_exec_delay", (ProcedureStatus.PASS, [], ""))

    runner = _runner(bus)
    proc = Procedure(ProcedureType.DELAY, ProcedureCategory.UTILITY, "Wait")

    runner._execute_procedure(proc, ctx=object(), sampler_ok=False)

    assert len(started) == 1 and started[0].step_key == "delay"
    assert started[0].step_name == "Wait"
    assert len(completed) == 1
    assert completed[0].status == "PASS"
    assert completed[0].duration_ms >= 0.0


def test_verification_failed_event_emitted(monkeypatch):
    bus = EventBus()
    fails = []
    bus.subscribe(VerificationFailed, fails.append)
    _force_legacy(monkeypatch)
    _stub(monkeypatch, "_exec_verify_alarm_panel", (ProcedureStatus.FAIL, [], ""))

    runner = _runner(bus)
    proc = Procedure(ProcedureType.VERIFY_ALARM_PANEL, ProcedureCategory.VERIFICATION, "Verify Panel")

    runner._execute_procedure(proc, ctx=object(), sampler_ok=False)

    assert len(fails) == 1
    assert fails[0].step_key == "verify_alarm_panel"


def test_verification_passed_event_emitted(monkeypatch):
    bus = EventBus()
    passes = []
    bus.subscribe(VerificationPassed, passes.append)
    _force_legacy(monkeypatch)
    _stub(monkeypatch, "_exec_verify_alarm_panel", (ProcedureStatus.PASS, [], ""))

    runner = _runner(bus)
    proc = Procedure(ProcedureType.VERIFY_ALARM_PANEL, ProcedureCategory.VERIFICATION, "Verify Panel")

    runner._execute_procedure(proc, ctx=object(), sampler_ok=False)
    assert len(passes) == 1


def test_action_step_emits_no_verification_event(monkeypatch):
    bus = EventBus()
    vpass, vfail = [], []
    bus.subscribe(VerificationPassed, vpass.append)
    bus.subscribe(VerificationFailed, vfail.append)
    _force_legacy(monkeypatch)
    _stub(monkeypatch, "_exec_delay", (ProcedureStatus.PASS, [], ""))

    runner = _runner(bus)
    runner._execute_procedure(
        Procedure(ProcedureType.DELAY, ProcedureCategory.UTILITY, "Wait"),
        ctx=object(), sampler_ok=False,
    )
    assert vpass == [] and vfail == []


def test_bad_subscriber_does_not_break_run(monkeypatch):
    bus = EventBus()
    def boom(e):
        raise RuntimeError("subscriber blew up")
    bus.subscribe(StepStarted, boom)
    _force_legacy(monkeypatch)
    _stub(monkeypatch, "_exec_delay", (ProcedureStatus.PASS, [], "ok.png"))

    runner = _runner(bus)
    result = runner._execute_procedure(
        Procedure(ProcedureType.DELAY, ProcedureCategory.UTILITY, "Wait"),
        ctx=object(), sampler_ok=False,
    )
    # The step still completed normally despite the exploding subscriber.
    assert result.status == ProcedureStatus.PASS
    assert result.screenshot_path == "ok.png"


def test_runner_defaults_to_global_bus():
    from iscs_core import bus as global_bus
    assert _runner().event_bus is global_bus


def test_emission_disabled_when_bus_is_none(monkeypatch):
    _force_legacy(monkeypatch)
    _stub(monkeypatch, "_exec_delay", (ProcedureStatus.SKIP, [], ""))
    runner = _runner()
    runner.event_bus = None                       # disable emission
    # must not raise even though no bus is present
    result = runner._execute_procedure(
        Procedure(ProcedureType.DELAY, ProcedureCategory.UTILITY, "Wait"),
        ctx=object(), sampler_ok=False,
    )
    assert result.status == ProcedureStatus.SKIP
