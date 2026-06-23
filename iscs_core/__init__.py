"""
iscs_core — additive modernization core for WilloWisp.

This package holds the framework-level abstractions the migration is built on
(see ../ARCHITECTURE_DESIGN.md and ../MIGRATION_CHECKLIST.md). It is **purely
additive**: nothing in the existing app imports it yet, so adding it cannot
change current behavior. Legacy code is wired to it incrementally in later phases.

Public surface:
    registry  — Capability contract, CapabilityMeta, StepResult, CapabilityRegistry
    events    — Event base + EventBus (pub/sub, isolated delivery)
    container — Container (dependency-injection resolver with lifetimes)
"""
from .registry import (
    Capability,
    CapabilityMeta,
    CapabilityRegistry,
    StepResult,
    StepStatus,
    DuplicateCapabilityError,
    UnknownCapabilityError,
    registry,
    register,
    using_registry,
)
from .discovery import discover_directory, discover_package, discover_entry_points
from .backends import VerificationBackend
from .events import (
    Event, EventBus, bus,
    SuiteStarted, SuiteCompleted, CardStarted, CardCompleted,
    IOPointStarted, IOPointCompleted,
    StepStarted, StepCompleted, VerificationPassed, VerificationFailed,
)
from .container import Container, LifetimeError

__all__ = [
    "Capability", "CapabilityMeta", "CapabilityRegistry", "StepResult",
    "StepStatus", "DuplicateCapabilityError", "UnknownCapabilityError",
    "registry", "register", "using_registry",
    "discover_directory", "discover_package", "discover_entry_points",
    "VerificationBackend",
    "Event", "EventBus", "bus",
    "SuiteStarted", "SuiteCompleted", "CardStarted", "CardCompleted",
    "IOPointStarted", "IOPointCompleted",
    "StepStarted", "StepCompleted", "VerificationPassed", "VerificationFailed",
    "Container", "LifetimeError",
]
