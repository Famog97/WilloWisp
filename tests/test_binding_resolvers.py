"""
Tests for the binding-resolver registry (FR-16, retires R9).

Asset binding types (TEXT / IMAGE / HYBRID and future kinds) are registered
``BindingResolver`` strategies; ``BindingExecutor`` dispatches by key instead of
an if/elif chain. The acceptance test is that a *new* binding kind can be added
and dispatched WITHOUT editing ``BindingExecutor``.

Hermetic: the ``resolver_registry`` fixture snapshots and restores the global
resolver dict so tests that register fakes don't leak into other tests.
"""
from types import SimpleNamespace

import pytest

import iscs_assets
from iscs_assets import (
    BindingType,
    StepBinding,
    BindingExecutor,
    BindingResolver,
    TextBindingResolver,
    ImageBindingResolver,
    HybridBindingResolver,
    register_binding_resolver,
    get_binding_resolver,
    list_binding_resolvers,
)


@pytest.fixture
def resolver_registry():
    """Snapshot/restore the global resolver registry around a test."""
    saved = dict(iscs_assets._BINDING_RESOLVERS)
    try:
        yield iscs_assets._BINDING_RESOLVERS
    finally:
        iscs_assets._BINDING_RESOLVERS.clear()
        iscs_assets._BINDING_RESOLVERS.update(saved)


# ── built-ins ────────────────────────────────────────────────────────────────

def test_builtin_resolvers_registered():
    assert list_binding_resolvers() == ["HYBRID", "IMAGE", "TEXT"]
    assert isinstance(get_binding_resolver(BindingType.TEXT), TextBindingResolver)
    assert isinstance(get_binding_resolver(BindingType.IMAGE), ImageBindingResolver)
    assert isinstance(get_binding_resolver(BindingType.HYBRID), HybridBindingResolver)


# ── registry contract ─────────────────────────────────────────────────────────

def test_get_unknown_kind_raises_clear_lookup_error():
    with pytest.raises(LookupError) as ei:
        get_binding_resolver("NOPE")
    msg = str(ei.value)
    assert "NOPE" in msg
    assert "TEXT" in msg  # lists the known kinds


def test_register_requires_non_empty_kind(resolver_registry):
    class Bad(BindingResolver):
        kind = ""

    with pytest.raises(ValueError):
        register_binding_resolver(Bad())


def test_duplicate_registration_rejected_unless_override(resolver_registry):
    class Fake(BindingResolver):
        kind = BindingType.TEXT

    with pytest.raises(ValueError):
        register_binding_resolver(Fake())          # TEXT already registered

    register_binding_resolver(Fake(), override=True)  # explicit replace OK
    assert isinstance(get_binding_resolver(BindingType.TEXT), Fake)


# ── dispatch: the FR-16 acceptance ─────────────────────────────────────────────

def _stub_executor(monkeypatch, resolved):
    """A BindingExecutor whose resolution + capture are stubbed out, so a test
    exercises only the resolver dispatch path."""
    region = SimpleNamespace(x1=0, y1=0, x2=1, y2=1, monitor_index=1)
    resolved = {"region": region, **resolved}

    mgr = SimpleNamespace(resolve_binding=lambda b: resolved)
    ex = BindingExecutor(asset_manager=mgr)
    return ex


def test_executor_dispatches_to_a_new_resolver_without_edit(resolver_registry, monkeypatch):
    """Drop in a brand-new binding kind; BindingExecutor routes to it unchanged."""
    class VisionResolver(BindingResolver):
        kind = "VISION"

        def resolve(self, img, resolved):
            return {"status": "PASS", "message": "vision ok",
                    "expected": "x", "actual": "x", "score": 0.99}

    register_binding_resolver(VisionResolver())

    ex = _stub_executor(monkeypatch, resolved={})
    binding = StepBinding(type="VISION", region_id="RGN_1")
    result = ex.execute(binding, screenshot_fn=lambda *a, **k: "IMG")

    assert result["status"] == "PASS"
    assert result["message"] == "vision ok"


def test_executor_unknown_binding_type_skips(resolver_registry, monkeypatch):
    ex = _stub_executor(monkeypatch, resolved={})
    binding = StepBinding(type="DOES_NOT_EXIST", region_id="RGN_1")
    result = ex.execute(binding, screenshot_fn=lambda *a, **k: "IMG")

    assert result["status"] == "SKIP"
    assert "DOES_NOT_EXIST" in result["message"]


# ── hybrid composition ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text_pass, image_pass, expected", [
    (True,  True,  "PASS"),
    (True,  False, "FAIL"),
    (False, True,  "FAIL"),
    (False, False, "FAIL"),
])
def test_hybrid_delegates_to_registered_text_and_image(
        resolver_registry, text_pass, image_pass, expected):
    """HYBRID composes whatever TEXT/IMAGE resolvers are registered — swapping
    either propagates, with no change to HybridBindingResolver."""
    class FakeText(BindingResolver):
        kind = BindingType.TEXT
        def resolve(self, img, resolved):
            return {"status": "PASS" if text_pass else "FAIL",
                    "expected": "t", "actual": "t", "score": 1.0 if text_pass else 0.0}

    class FakeImage(BindingResolver):
        kind = BindingType.IMAGE
        def resolve(self, img, resolved):
            return {"status": "PASS" if image_pass else "FAIL",
                    "expected": "i", "actual": "i", "score": 0.9 if image_pass else 0.1}

    register_binding_resolver(FakeText(), override=True)
    register_binding_resolver(FakeImage(), override=True)

    result = HybridBindingResolver().resolve("IMG", {"threshold": 0.85})

    assert result["status"] == expected
    # composes both sub-results
    assert "text_detail" in result and "image_detail" in result
