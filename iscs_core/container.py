"""
Dependency-injection container (FR-26).

Centralizes construction and lifetime of collaborators (runner, protocol
handlers, verification backends, report sinks) so the engine depends on
abstractions and asks the container for implementations, instead of building
them inline (today: ProcedureRunner(...), ModbusProtocol(...), etc. scattered in
baru.py). Swapping a real implementation for a fake in tests becomes trivial.

Intentionally tiny — a dict of factories with three lifetimes. No magic
auto-wiring; explicit registration keeps it debuggable.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Hashable


class LifetimeError(ValueError):
    """Raised for an unknown lifetime or a missing registration."""


_LIFETIMES = ("singleton", "transient", "scoped")


class Container:
    """Resolve dependencies by key (a type or string).

    Lifetimes:
      - singleton : built once, cached for the container's life
      - transient : built fresh on every resolve
      - scoped    : built once per `scope()` block (e.g. per suite run)
    """

    def __init__(self) -> None:
        self._factories: Dict[Hashable, Callable[["Container"], Any]] = {}
        self._lifetimes: Dict[Hashable, str] = {}
        self._singletons: Dict[Hashable, Any] = {}
        self._scoped_cache: Dict[Hashable, Any] = {}
        self._in_scope = False

    def register(self, key: Hashable, factory: Callable[["Container"], Any],
                 *, lifetime: str = "singleton") -> None:
        if lifetime not in _LIFETIMES:
            raise LifetimeError(f"Unknown lifetime {lifetime!r}; expected one of {_LIFETIMES}.")
        self._factories[key] = factory
        self._lifetimes[key] = lifetime
        self._singletons.pop(key, None)        # re-registration resets any cache
        self._scoped_cache.pop(key, None)

    def register_instance(self, key: Hashable, instance: Any) -> None:
        """Register an already-built object as a singleton."""
        self._factories[key] = lambda c: instance
        self._lifetimes[key] = "singleton"
        self._singletons[key] = instance

    def resolve(self, key: Hashable) -> Any:
        if key not in self._factories:
            raise LifetimeError(f"No registration for {key!r}.")
        lifetime = self._lifetimes[key]

        if lifetime == "singleton":
            if key not in self._singletons:
                self._singletons[key] = self._factories[key](self)
            return self._singletons[key]

        if lifetime == "scoped":
            if not self._in_scope:
                raise LifetimeError(
                    f"{key!r} is 'scoped' and must be resolved inside a `with container.scope():`."
                )
            if key not in self._scoped_cache:
                self._scoped_cache[key] = self._factories[key](self)
            return self._scoped_cache[key]

        # transient
        return self._factories[key](self)

    def has(self, key: Hashable) -> bool:
        return key in self._factories

    def scope(self) -> "_Scope":
        return _Scope(self)


class _Scope:
    """Context manager establishing a scoped-lifetime cache."""

    def __init__(self, container: Container) -> None:
        self._c = container

    def __enter__(self) -> Container:
        self._c._in_scope = True
        self._c._scoped_cache.clear()
        return self._c

    def __exit__(self, *exc: Any) -> None:
        self._c._in_scope = False
        self._c._scoped_cache.clear()
