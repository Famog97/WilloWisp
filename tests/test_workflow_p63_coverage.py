"""
Tests for P6.3 (safe finish) — the legacy `_exec_*` fallback is a provably
vestigial, loud safety net.

  - `registry_step_coverage()` reports every ProcedureType key as covered once the
    legacy adapters (and/or plugins) are registered, and reports gaps otherwise.
  - `_execute_procedure` logs a clear warning when it actually falls back to a
    legacy executor while the registry was present (a degraded state), and stays
    quiet on the normal registry path.
"""
import threading

import pytest

import iscs_workflow as wf
from iscs_workflow import ProcedureType, ProcedureStatus, ProcedureCategory, Procedure
from adapters.driven.input import legacy_executors as _legacy_exec
from core.services import engine as _eng   # M3.4: dispatcher/coverage read core_registry here
from iscs_core import CapabilityRegistry, CapabilityMeta, StepResult, StepStatus


def _runner(on_log=lambda m: None):
    return wf.ProcedureRunner(
        flow=None, verifier=None, handler=None, config={},
        on_log=on_log,
        stop_event=threading.Event(), pause_event=threading.Event(),
    )


def _proc(ptype=ProcedureType.DELAY):
    return Procedure(proc_type=ptype, category=ProcedureCategory.UTILITY, name="Step")


# ── coverage diagnostic ─────────────────────────────────────────────────────────

def test_coverage_all_covered_with_legacy_adapters():
    reg = CapabilityRegistry()
    wf.register_legacy_capabilities(into=reg)
    covered, missing = wf.registry_step_coverage(reg)
    assert missing == []
    # every enum value is accounted for
    assert set(covered) == {t.value for t in ProcedureType}


def test_coverage_reports_gaps_for_empty_registry():
    covered, missing = wf.registry_step_coverage(CapabilityRegistry())
    assert covered == []
    assert set(missing) == {t.value for t in ProcedureType}


def test_coverage_global_registry_is_complete():
    # The live global registry (legacy adapters auto-registered at import) must
    # cover every step type — proving the direct legacy fallback is vestigial.
    _, missing = wf.registry_step_coverage()
    assert missing == []


# ── loud fallback (NFR-9) ─────────────────────────────────────────────────────--

def test_fallback_logs_warning_when_registry_present_but_key_missing(monkeypatch):
    monkeypatch.setattr(_eng, "core_registry", CapabilityRegistry())  # present but empty
    monkeypatch.setattr(_legacy_exec, "_exec_delay", lambda *a, **k: (ProcedureStatus.PASS, [], ""))
    logs = []
    runner = _runner(on_log=lambda m: logs.append(m))

    runner._execute_procedure(_proc(), ctx=object(), sampler_ok=False)

    assert any("no registered capability" in m for m in logs), logs


def test_no_warning_on_normal_registry_path(monkeypatch):
    class Cap:
        key = ProcedureType.DELAY.value
        meta = CapabilityMeta(name="Cap", category="utility")
        def execute(self, ctx):
            return StepResult(StepStatus.PASS)

    reg = CapabilityRegistry()
    reg.register(Cap())
    monkeypatch.setattr(_eng, "core_registry", reg)
    logs = []
    runner = _runner(on_log=lambda m: logs.append(m))

    runner._execute_procedure(_proc(), ctx=object(), sampler_ok=False)

    assert not any("no registered capability" in m for m in logs), logs


def test_no_warning_when_registry_absent(monkeypatch):
    # iscs_core unavailable → expected pure-legacy mode, so no per-step warning.
    monkeypatch.setattr(_eng, "core_registry", None)
    monkeypatch.setattr(_legacy_exec, "_exec_delay", lambda *a, **k: (ProcedureStatus.PASS, [], ""))
    logs = []
    runner = _runner(on_log=lambda m: logs.append(m))

    runner._execute_procedure(_proc(), ctx=object(), sampler_ok=False)

    assert not any("no registered capability" in m for m in logs), logs
