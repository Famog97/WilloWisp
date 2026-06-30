"""
Event bus — lifecycle pub/sub (FR-28).

Lets subsystems (reporting, metrics, recorder, a future dashboard/AI) react to
run lifecycle events without the engine depending on them. Delivery is isolated:
a failing subscriber is logged and skipped, never aborting the run (NFR-11).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, DefaultDict, List, Type
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Base class for lifecycle events. Subclass for concrete events, e.g.

        @dataclass
        class StepCompleted(Event):
            step_key: str
            status: str
    """


Handler = Callable[[Event], None]


class EventBus:
    """Minimal synchronous pub/sub keyed by event type.

    Subscribing to a base type also receives subclasses (covariant delivery),
    so a subscriber can listen to `Event` to observe everything.
    """

    def __init__(self) -> None:
        self._subs: DefaultDict[Type[Event], List[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Type[Event], handler: Handler) -> Callable[[], None]:
        """Register a handler; returns an unsubscribe callable."""
        self._subs[event_type].append(handler)

        def _unsubscribe() -> None:
            try:
                self._subs[event_type].remove(handler)
            except ValueError:
                pass

        return _unsubscribe

    def publish(self, event: Event) -> int:
        """Deliver to all handlers whose subscribed type is the event's type or a
        supertype of it. Returns the number of handlers invoked successfully.
        A handler raising is logged and skipped (isolated delivery)."""
        delivered = 0
        for event_type, handlers in list(self._subs.items()):
            if isinstance(event, event_type):
                for handler in list(handlers):
                    try:
                        handler(event)
                        delivered += 1
                    except Exception:
                        logger.exception(
                            "EventBus subscriber %r failed handling %s",
                            handler, type(event).__name__,
                        )
        return delivered

    def clear(self) -> None:
        """Reset — primarily for test isolation."""
        self._subs.clear()


# ──────────────────────────────────────────────────────────────────────────────
#  Concrete lifecycle events (FR-28 minimum set)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SuiteStarted(Event):
    title: str = ""


@dataclass
class SuiteCompleted(Event):
    title: str = ""
    passed: int = 0
    failed: int = 0


@dataclass
class CardStarted(Event):
    card_name: str = ""
    loop: int = 0
    scenario_index: int = 0
    total_scenarios: int = 0


@dataclass
class CardCompleted(Event):
    card_name: str = ""
    loop: int = 0


@dataclass
class IOPointStarted(Event):
    point_id: str = ""
    index: int = 0
    total: int = 0


@dataclass
class IOPointCompleted(Event):
    point_id: str = ""
    status: str = ""          # "PASS" | "FAIL" | "SKIP" | "ERROR"


@dataclass
class StepStarted(Event):
    step_key: str = ""        # ProcedureType value, e.g. "verify_alarm_panel"
    step_name: str = ""


@dataclass
class StepCompleted(Event):
    step_key: str = ""
    step_name: str = ""
    status: str = ""          # "PASS" | "FAIL" | "SKIP" | "ERROR"
    duration_ms: float = 0.0


@dataclass
class VerificationPassed(Event):
    step_key: str = ""
    step_name: str = ""


@dataclass
class VerificationFailed(Event):
    step_key: str = ""
    step_name: str = ""
    message: str = ""


# Shared application-wide bus (mirrors the global capability `registry`).
# Subsystems subscribe here; the engine publishes here. Optional — code guards
# for its absence so nothing breaks if iscs_core is stripped out.
bus = EventBus()
