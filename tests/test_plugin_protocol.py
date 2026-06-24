"""
Tests for the final Phase 3 port — trigger_alarm / reset_alarm action plugins.

The signal is sent via a fake protocol handler (nothing touches real Modbus) and
the FrameSampler is monkeypatched, so the trigger/sampler ordering and the
exec-context bookkeeping are verified fully offline.
"""
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from iscs_core import CapabilityRegistry, discover_directory, StepStatus

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = ROOT / "plugins" / "actions"


@pytest.fixture
def reg():
    r = CapabilityRegistry()
    discover_directory(ACTIONS, into=r)
    return r


class FakeHandler:
    def __init__(self):
        self.calls = []
    def trigger_alarm(self, pt): self.calls.append(("trigger", pt))
    def reset_alarm(self, pt): self.calls.append(("reset", pt))


def _ctx(pt="PT1", resolved_bbox=None, sampler_ok=False, config=None):
    handler = FakeHandler()
    ec = SimpleNamespace(pt=pt, resolved_bbox=resolved_bbox)
    runner = SimpleNamespace(handler=handler, config=config or {})
    ctx = SimpleNamespace(proc=SimpleNamespace(params={}), exec=ec, runner=runner,
                          sampler_ok=sampler_ok, log=lambda m: None)
    return ctx, ec, handler


# ── discovery / supersession ──────────────────────────────────────────────────

def test_protocol_actions_register(reg):
    assert reg.has("trigger_alarm") and reg.has("reset_alarm")


def test_protocol_actions_supersede_legacy():
    import iscs_workflow as wf
    r = CapabilityRegistry()
    wf.register_legacy_capabilities(into=r)
    discover_directory(ACTIONS, into=r)
    assert type(r.get("trigger_alarm")).__name__ == "TriggerAlarmAction"
    assert type(r.get("reset_alarm")).__name__ == "ResetAlarmAction"


# ── trigger ─────────────────────────────────────────────────────────────────--

def test_trigger_sends_signal_and_records_state(reg):
    ctx, ec, handler = _ctx()
    out = reg.get("trigger_alarm").execute(ctx)
    assert out.status is StepStatus.PASS
    assert handler.calls == [("trigger", "PT1")]
    assert ec.trigger_ok is True
    assert ec.trigger_time is not None and ec.trigger_ns > 0


def test_reset_sends_signal_and_records_state(reg):
    ctx, ec, handler = _ctx()
    out = reg.get("reset_alarm").execute(ctx)
    assert out.status is StepStatus.PASS
    assert handler.calls == [("reset", "PT1")]
    assert ec.reset_ok is True and ec.reset_ns > 0


def test_skip_when_no_point(reg):
    for key in ("trigger_alarm", "reset_alarm"):
        ctx, ec, handler = _ctx(pt=None)
        out = reg.get(key).execute(ctx)
        assert out.status is StepStatus.SKIP
        assert handler.calls == []          # no signal sent


# ── sampler ordering (trigger first, then sampler) ─────────────────────────────

def _inject_fake_sampler(monkeypatch, events):
    """Inject a fake iscs_Sampler_Anchor so the plugin's real
    `from iscs_Sampler_Anchor import FrameSampler` import succeeds offline."""
    class FakeSampler:
        def __init__(self, bbox, duration_sec, interval_ms):
            events.append("sampler_init")
        def start(self): events.append("sampler_start")
    monkeypatch.setitem(sys.modules, "iscs_Sampler_Anchor",
                        SimpleNamespace(FrameSampler=FakeSampler))


def test_sampler_starts_after_trigger(reg, monkeypatch):
    events = []
    _inject_fake_sampler(monkeypatch, events)

    handler = FakeHandler()
    handler.trigger_alarm = lambda pt: events.append("trigger")
    ec = SimpleNamespace(pt="PT1", resolved_bbox=(0, 0, 10, 10))
    runner = SimpleNamespace(handler=handler,
                             config={"detection_duration_sec": 1, "sampler_interval_ms": 50})
    ctx = SimpleNamespace(proc=SimpleNamespace(params={}), exec=ec, runner=runner,
                          sampler_ok=True, log=lambda m: None)

    reg.get("trigger_alarm").execute(ctx)
    assert events == ["trigger", "sampler_init", "sampler_start"]  # signal BEFORE sampler
    assert ec.sampler is not None


def test_sampler_skipped_without_resolved_bbox(reg, monkeypatch):
    events = []
    _inject_fake_sampler(monkeypatch, events)
    ctx, ec, handler = _ctx(resolved_bbox=None, sampler_ok=True)
    reg.get("trigger_alarm").execute(ctx)
    assert events == []                     # no bbox → no sampler
