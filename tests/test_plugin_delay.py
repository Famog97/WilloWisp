"""
Tests for B1 — the Delay capability ported into plugins/utilities/delay.py.

Proves the supersession path offline: discovering the plugin registers a real
DelayCapability under key "delay" (overriding the legacy adapter), and it executes
with the same behavior as the old _exec_delay (reads delay_sec, uses the runner's
interruptible sleep, returns PASS). The live run validates real timing.
"""
from types import SimpleNamespace
from pathlib import Path

from iscs_core import CapabilityRegistry, discover_directory, StepStatus

REPO_ROOT = Path(__file__).resolve().parent.parent
UTILITIES = REPO_ROOT / "plugins" / "utilities"


def _discover():
    reg = CapabilityRegistry()
    discover_directory(UTILITIES, into=reg)
    return reg


def test_delay_plugin_registers_under_delay_key():
    reg = _discover()
    assert reg.has("delay")
    assert type(reg.get("delay")).__name__ == "DelayCapability"
    assert reg.get("delay").meta.category == "utility"


def test_delay_uses_runner_interruptible_sleep():
    cap = _discover().get("delay")
    slept = []
    ctx = SimpleNamespace(
        runner=SimpleNamespace(_sleep=lambda s: slept.append(s)),
        proc=SimpleNamespace(params={"delay_sec": 2.5}),
        log=lambda m: None,
    )
    result = cap.execute(ctx)
    assert result.status is StepStatus.PASS
    assert slept == [2.5]           # delegated to the runner's interruptible sleep


def test_delay_defaults_to_one_second_and_tolerates_bad_param():
    cap = _discover().get("delay")
    for params in ({}, {"delay_sec": "oops"}):
        slept = []
        ctx = SimpleNamespace(
            runner=SimpleNamespace(_sleep=lambda s: slept.append(s)),
            proc=SimpleNamespace(params=params),
            log=lambda m: None,
        )
        cap.execute(ctx)
        assert slept == [1.0]       # default when missing or unparseable


def test_delay_falls_back_to_time_sleep_without_runner(monkeypatch):
    import time
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    cap = _discover().get("delay")
    ctx = SimpleNamespace(proc=SimpleNamespace(params={"delay_sec": 0.3}), log=lambda m: None)
    # no `runner` attribute → falls back to time.sleep
    result = cap.execute(ctx)
    assert result.status is StepStatus.PASS
    assert slept == [0.3]


def test_delay_overrides_legacy_adapter_in_same_registry():
    # Simulate the live order: legacy adapter present first, then plugin discovered.
    import iscs_workflow as wf
    reg = CapabilityRegistry()
    wf.register_legacy_capabilities(into=reg)          # 19 legacy adapters incl. "delay"
    assert type(reg.get("delay")).__name__ == "LegacyCapabilityAdapter"
    discover_directory(UTILITIES, into=reg)            # plugin overrides by key
    assert type(reg.get("delay")).__name__ == "DelayCapability"
