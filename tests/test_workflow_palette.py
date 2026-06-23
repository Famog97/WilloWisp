"""
Tests for P4.1 — the Add-Step palette is built from _dynamic_catalogue(): the
curated _STEP_CATALOGUE plus registry capabilities that opt in (meta.addable=True)
and whose key is a valid ProcedureType. Pure logic — no Tkinter.
"""
import iscs_workflow as wf
from iscs_core import CapabilityRegistry, CapabilityMeta


class _FakeCap:
    def __init__(self, key, addable, name="X", category="action", params=None):
        self.key = key
        self.meta = CapabilityMeta(name=name, category=category,
                                   params_schema=params or {}, addable=addable)


def test_curated_palette_when_no_addable(monkeypatch):
    monkeypatch.setattr(wf, "core_registry", CapabilityRegistry())  # empty
    assert wf._dynamic_catalogue() == wf._STEP_CATALOGUE


def test_real_registry_does_not_change_palette(monkeypatch):
    # The shipped plugins/adapters don't set addable=True, so the live palette is
    # unchanged — existing UX preserved.
    keys = {c[1] for c in wf._dynamic_catalogue()}
    assert keys == {c[1] for c in wf._STEP_CATALOGUE}


def test_addable_enum_backed_capability_appears(monkeypatch):
    reg = CapabilityRegistry()
    reg.register(_FakeCap("verify_normalize", addable=True, name="Verify Normalize",
                          category="verification", params={"foo": 1}))
    monkeypatch.setattr(wf, "core_registry", reg)

    cat = wf._dynamic_catalogue()
    entry = next((c for c in cat if c[1] == "verify_normalize"), None)
    assert entry is not None
    assert entry[0] == "Verify Normalize"          # display name from meta
    assert entry[3] == {"foo": 1}                  # params_schema → field defaults


def test_non_enum_addable_now_included(monkeypatch):
    # P6.3: Procedure is no longer enum-bound, so an addable plugin with a
    # brand-new key now appears in the palette (and can be added/saved/run).
    reg = CapabilityRegistry()
    reg.register(_FakeCap("totally_new_key", addable=True))
    monkeypatch.setattr(wf, "core_registry", reg)
    assert any(c[1] == "totally_new_key" for c in wf._dynamic_catalogue())


def test_duplicate_of_curated_not_added(monkeypatch):
    reg = CapabilityRegistry()
    reg.register(_FakeCap("delay", addable=True, category="utility"))
    monkeypatch.setattr(wf, "core_registry", reg)
    cat = wf._dynamic_catalogue()
    assert sum(1 for c in cat if c[1] == "delay") == 1   # curated entry wins, no dupe
