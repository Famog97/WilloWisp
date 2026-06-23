"""
Tests for iscs_core.registry — the capability contract + registry that replaces
the hardcoded ProcedureType/dispatch coupling.
"""
import pytest

from iscs_core import (
    CapabilityRegistry, CapabilityMeta, StepResult, StepStatus,
    Capability, DuplicateCapabilityError, UnknownCapabilityError, register,
)


def make_cap(key="click", category="action"):
    class _Cap:
        def __init__(self):
            self.key = key
            self.meta = CapabilityMeta(name=key.title(), category=category)

        def execute(self, ctx):
            return StepResult(StepStatus.PASS, message=f"ran {self.key}")
    return _Cap()


@pytest.fixture
def reg():
    return CapabilityRegistry()


# ── contract ──────────────────────────────────────────────────────────────────

def test_capability_protocol_is_structural():
    assert isinstance(make_cap(), Capability)


def test_step_result_to_dict_is_json_friendly():
    r = StepResult(StepStatus.FAIL, message="nope", data={"score": 0.1})
    assert r.to_dict() == {"status": "FAIL", "message": "nope",
                           "screenshot": "", "data": {"score": 0.1}}


# ── registration / lookup ─────────────────────────────────────────────────────

def test_register_and_get(reg):
    cap = make_cap("verify_alarm_panel", "verification")
    reg.register(cap)
    assert reg.get("verify_alarm_panel") is cap
    assert reg.has("verify_alarm_panel")


def test_duplicate_registration_rejected(reg):
    reg.register(make_cap("click"))
    with pytest.raises(DuplicateCapabilityError):
        reg.register(make_cap("click"))


def test_duplicate_allowed_with_override(reg):
    reg.register(make_cap("click"))
    replacement = make_cap("click")
    reg.register(replacement, override=True)
    assert reg.get("click") is replacement


def test_unknown_key_raises_helpful_error(reg):
    reg.register(make_cap("click"))
    with pytest.raises(UnknownCapabilityError) as ei:
        reg.get("nope")
    assert "nope" in str(ei.value)
    assert "click" in str(ei.value)        # lists known keys as a hint


def test_register_requires_key_and_meta(reg):
    class NoKey:
        key = ""
        meta = CapabilityMeta(name="x", category="action")
        def execute(self, ctx): ...
    with pytest.raises(ValueError):
        reg.register(NoKey())

    class NoMeta:
        key = "x"
        meta = None
        def execute(self, ctx): ...
    with pytest.raises(ValueError):
        reg.register(NoMeta())


# ── listing / filtering / manifest ────────────────────────────────────────────

def test_list_filters_by_category_and_sorts(reg):
    reg.register(make_cap("type_text", "action"))
    reg.register(make_cap("click", "action"))
    reg.register(make_cap("verify_custom", "verification"))
    assert [c.key for c in reg.list("action")] == ["click", "type_text"]
    assert [c.key for c in reg.list()] == ["click", "type_text", "verify_custom"]


def test_manifest_summarizes_loaded_caps(reg):
    reg.register(make_cap("click", "action"))
    m = reg.manifest()
    assert m["click"]["category"] == "action"


# ── aliases (deprecation/rename) ──────────────────────────────────────────────

def test_alias_resolves_to_current_key(reg):
    cap = make_cap("verify_equipment_page", "verification")
    reg.register(cap)
    reg.alias("verify_equip_page", "verify_equipment_page")   # old → new
    assert reg.get("verify_equip_page") is cap
    assert reg.has("verify_equip_page")


def test_alias_cycle_does_not_hang(reg):
    reg.alias("a", "b")
    reg.alias("b", "a")
    with pytest.raises(UnknownCapabilityError):
        reg.get("a")


# ── decorator against an injected registry ────────────────────────────────────

def test_register_decorator_registers_instance(reg):
    @register(into=reg)
    class HotkeyAction:
        key = "hotkey"
        meta = CapabilityMeta(name="Hotkey", category="action")
        def execute(self, ctx):
            return StepResult(StepStatus.PASS)
    assert reg.has("hotkey")
    assert isinstance(reg.get("hotkey"), HotkeyAction)
