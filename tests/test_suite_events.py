"""
Tests for P2.3 (additive) — SuiteRunner carries an event bus and emits lifecycle
events. The live run() thread can't be exercised offline (it does real capture +
protocol I/O), so these verify the wiring and the _emit helper directly: that the
bus is injectable, defaults to the shared core bus, and that emission is isolated.

Skipped if baru.py's optional desktop deps are unavailable (headless CI).
"""
import pytest

baru = pytest.importorskip("baru", reason="baru.py optional desktop deps unavailable")

from iscs_core import EventBus, SuiteStarted, SuiteCompleted, CardStarted


def _suite_runner(bus=None):
    noop = lambda *a, **k: None
    return baru.SuiteRunner(
        scenarios=[], monitors=[], protocols=None, config={},
        on_scenario_start=noop, on_progress=noop, on_paused=noop,
        on_pass_done=noop, on_suite_done=noop, on_log=noop,
        suite_title="T", event_bus=bus,
    )


def test_suite_runner_uses_injected_bus():
    bus = EventBus()
    assert _suite_runner(bus).event_bus is bus


def test_suite_runner_defaults_to_core_bus():
    from iscs_core import bus as core_bus
    assert _suite_runner().event_bus is core_bus


def test_emit_publishes_to_subscribers():
    bus = EventBus()
    seen = []
    bus.subscribe(SuiteStarted, seen.append)
    bus.subscribe(CardStarted, seen.append)
    runner = _suite_runner(bus)

    runner._emit(SuiteStarted(title="T"))
    runner._emit(CardStarted(card_name="Card A", loop=1, scenario_index=1, total_scenarios=2))

    assert [type(e).__name__ for e in seen] == ["SuiteStarted", "CardStarted"]
    assert seen[1].card_name == "Card A"


def test_emit_is_isolated_from_bad_subscriber():
    bus = EventBus()
    def boom(e):
        raise RuntimeError("boom")
    bus.subscribe(SuiteCompleted, boom)
    runner = _suite_runner(bus)
    # must not raise
    runner._emit(SuiteCompleted(title="T", passed=3, failed=1))


def test_emit_noop_when_event_is_none():
    # _CORE_EVENTS_OK False path passes None into _emit — must be a safe no-op.
    runner = _suite_runner(EventBus())
    runner._emit(None)        # should not raise
