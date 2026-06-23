"""
Tests for P6.3 — Procedure decoupled from the ProcedureType enum. Plugin step
keys not in the enum become a _DynamicProcType that quacks like an enum member,
so they round-trip and execute via the registry. Pure logic.
"""
import threading

import iscs_workflow as wf
from iscs_workflow import (
    ProcedureType, ProcedureCategory, ProcedureStatus, Procedure,
    _resolve_proc_type, _DynamicProcType,
)
from iscs_core import CapabilityRegistry, CapabilityMeta, StepResult, StepStatus


# ── resolution ────────────────────────────────────────────────────────────────

def test_resolve_known_key_returns_enum():
    assert _resolve_proc_type("delay") is ProcedureType.DELAY


def test_resolve_unknown_key_returns_dynamic():
    d = _resolve_proc_type("brand_new_key")
    assert isinstance(d, _DynamicProcType)
    assert d.value == "brand_new_key"
    assert d.name == "BRAND_NEW_KEY"


def test_resolve_passes_through_existing_types():
    assert _resolve_proc_type(ProcedureType.CLICK) is ProcedureType.CLICK
    dt = _DynamicProcType("x")
    assert _resolve_proc_type(dt) is dt


# ── enum-member duck typing ───────────────────────────────────────────────────

def test_dynamic_quacks_like_enum_member():
    d = _DynamicProcType("foo")
    assert d.value == "foo"                     # used by registry lookup + to_dict
    assert d != ProcedureType.DELAY             # not equal to a real enum member
    assert d == _DynamicProcType("foo")         # value equality
    assert {d: 1}[_DynamicProcType("foo")] == 1  # hashable by value


# ── serialization round-trip ──────────────────────────────────────────────────

def test_dynamic_proc_type_round_trips():
    p = Procedure(proc_type=_DynamicProcType("plugin_step"),
                  category=ProcedureCategory.ACTION, name="Custom")
    d = p.to_dict()
    assert d["proc_type"] == "plugin_step"
    p2 = Procedure.from_dict(d)
    assert p2.proc_type.value == "plugin_step"
    assert isinstance(p2.proc_type, _DynamicProcType)


# ── execution via the registry ────────────────────────────────────────────────

def _runner():
    return wf.ProcedureRunner(flow=None, verifier=None, handler=None, config={},
                              on_log=lambda m: None,
                              stop_event=threading.Event(), pause_event=threading.Event())


def test_dynamic_step_executes_via_registered_plugin(monkeypatch):
    ran = []

    class PluginCap:
        key = "my_plugin_step"
        meta = CapabilityMeta(name="My Plugin", category="action")
        def execute(self, ctx):
            ran.append(1)
            return StepResult(StepStatus.PASS, message="ok")

    reg = CapabilityRegistry()
    reg.register(PluginCap())
    monkeypatch.setattr(wf, "core_registry", reg)

    proc = Procedure(proc_type=_DynamicProcType("my_plugin_step"),
                     category=ProcedureCategory.ACTION, name="X")
    res = _runner()._execute_procedure(proc, ctx=object(), sampler_ok=False)
    assert ran == [1]
    assert res.status == ProcedureStatus.PASS


def test_dynamic_step_without_handler_errors_clearly(monkeypatch):
    monkeypatch.setattr(wf, "core_registry", CapabilityRegistry())  # empty
    proc = Procedure(proc_type=_DynamicProcType("nobody_handles_this"),
                     category=ProcedureCategory.ACTION, name="X")
    res = _runner()._execute_procedure(proc, ctx=object(), sampler_ok=False)
    assert res.status == ProcedureStatus.ERROR
    assert "No executor" in res.error_detail


# ── palette: arbitrary addable plugin keys now appear ─────────────────────────

def test_catalogue_includes_non_enum_addable(monkeypatch):
    class FakeCap:
        key = "brand_new_key"
        meta = CapabilityMeta(name="Brand New", category="action", addable=True)
    reg = CapabilityRegistry()
    reg.register(FakeCap())
    monkeypatch.setattr(wf, "core_registry", reg)
    cat = wf._dynamic_catalogue()
    assert any(c[1] == "brand_new_key" for c in cat)   # no enum-backed filter (P6.3)
