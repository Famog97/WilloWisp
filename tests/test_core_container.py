"""
Tests for iscs_core.container.Container — the DI resolver with lifetimes.
"""
import pytest

from iscs_core import Container, LifetimeError


def test_singleton_built_once_and_cached():
    c = Container()
    calls = []
    c.register("svc", lambda _: calls.append(1) or object(), lifetime="singleton")
    a = c.resolve("svc")
    b = c.resolve("svc")
    assert a is b
    assert len(calls) == 1


def test_transient_built_every_time():
    c = Container()
    c.register("svc", lambda _: object(), lifetime="transient")
    assert c.resolve("svc") is not c.resolve("svc")


def test_register_instance_returns_same_object():
    c = Container()
    sentinel = object()
    c.register_instance("cfg", sentinel)
    assert c.resolve("cfg") is sentinel


def test_factory_can_resolve_dependencies():
    c = Container()
    c.register("dep", lambda _: "DEP", lifetime="singleton")
    c.register("svc", lambda cc: f"svc<{cc.resolve('dep')}>", lifetime="singleton")
    assert c.resolve("svc") == "svc<DEP>"


def test_unknown_registration_raises():
    c = Container()
    with pytest.raises(LifetimeError):
        c.resolve("missing")


def test_unknown_lifetime_rejected():
    c = Container()
    with pytest.raises(LifetimeError):
        c.register("x", lambda _: 1, lifetime="forever")


def test_keys_can_be_types():
    class IProtocol: ...
    c = Container()
    c.register(IProtocol, lambda _: "modbus", lifetime="singleton")
    assert c.resolve(IProtocol) == "modbus"


# ── scoped lifetime ───────────────────────────────────────────────────────────

def test_scoped_requires_active_scope():
    c = Container()
    c.register("run", lambda _: object(), lifetime="scoped")
    with pytest.raises(LifetimeError):
        c.resolve("run")


def test_scoped_cached_within_scope_fresh_across_scopes():
    c = Container()
    c.register("run", lambda _: object(), lifetime="scoped")
    with c.scope() as s:
        a1 = s.resolve("run")
        a2 = s.resolve("run")
        assert a1 is a2                      # cached within the scope
    with c.scope() as s:
        b = s.resolve("run")
    assert b is not a1                       # fresh in a new scope
