"""
Tests for iscs_core.events.EventBus — lifecycle pub/sub with isolated delivery.
"""
from dataclasses import dataclass

from iscs_core import Event, EventBus


@dataclass
class StepStarted(Event):
    step_key: str


@dataclass
class StepCompleted(Event):
    step_key: str
    status: str


def test_subscriber_receives_matching_event():
    bus = EventBus()
    seen = []
    bus.subscribe(StepCompleted, lambda e: seen.append(e.status))
    bus.publish(StepCompleted("click", "PASS"))
    assert seen == ["PASS"]


def test_subscriber_only_receives_its_type():
    bus = EventBus()
    seen = []
    bus.subscribe(StepCompleted, lambda e: seen.append(e))
    bus.publish(StepStarted("click"))      # different type
    assert seen == []


def test_base_type_subscription_receives_subclasses():
    bus = EventBus()
    count = []
    bus.subscribe(Event, lambda e: count.append(type(e).__name__))
    bus.publish(StepStarted("a"))
    bus.publish(StepCompleted("a", "FAIL"))
    assert count == ["StepStarted", "StepCompleted"]


def test_publish_returns_delivery_count():
    bus = EventBus()
    bus.subscribe(StepStarted, lambda e: None)
    bus.subscribe(StepStarted, lambda e: None)
    assert bus.publish(StepStarted("x")) == 2


def test_failing_subscriber_is_isolated():
    bus = EventBus()
    delivered = []

    def boom(e):
        raise RuntimeError("subscriber blew up")

    bus.subscribe(StepStarted, boom)
    bus.subscribe(StepStarted, lambda e: delivered.append(e.step_key))

    # publish must not raise, and the healthy subscriber still runs
    count = bus.publish(StepStarted("x"))
    assert delivered == ["x"]
    assert count == 1                       # only the healthy one counted


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    seen = []
    off = bus.subscribe(StepStarted, lambda e: seen.append(e.step_key))
    bus.publish(StepStarted("a"))
    off()
    bus.publish(StepStarted("b"))
    assert seen == ["a"]
