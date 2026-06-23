"""
Tests for B3 (P2.3 cutover) — the per-card recorder driven by Card events.

Exercises SuiteRunner's recorder handler methods directly (no live capture):
CardStarted starts the recorder + sets _active_rec (so per-point overlay updates
still work) + marks the event handled; CardCompleted stops it. The handled flag is
what lets the run loop skip its inline fallback. The live run validates real MP4s.
"""
from types import SimpleNamespace

import pytest

baru = pytest.importorskip("baru", reason="baru.py optional desktop deps unavailable")

from iscs_core import CardStarted, CardCompleted


def _runner(on_rec_start=None, on_rec_stop=None):
    noop = lambda *a, **k: None
    return baru.SuiteRunner(
        scenarios=[], monitors=[], protocols=None, config={},
        on_scenario_start=noop, on_progress=noop, on_paused=noop,
        on_pass_done=noop, on_suite_done=noop, on_log=noop,
        on_rec_start=on_rec_start, on_rec_stop=on_rec_stop,
    )


def test_card_started_starts_recorder_and_sets_active_rec():
    started = []
    rec_sentinel = object()
    r = _runner(on_rec_start=lambda sc, d: started.append((sc, d)) or rec_sentinel)

    evt = CardStarted(card_name="C", loop=1, scenario="SC", evidence_dir="dir")
    r._on_event_card_started(evt)

    assert evt.recorder_handled is True
    assert started == [("SC", "dir")]
    assert r._active_rec is rec_sentinel        # per-point overlay updates can find it


def test_card_completed_stops_recorder_and_clears():
    stopped = []
    r = _runner(
        on_rec_start=lambda sc, d: "REC",
        on_rec_stop=lambda rec, name: stopped.append((rec, name)),
    )
    r._on_event_card_started(CardStarted(card_name="C", loop=1, scenario="SC", evidence_dir="dir"))

    cc = CardCompleted(card_name="C", loop=1)
    r._on_event_card_completed(cc)

    assert cc.recorder_handled is True
    assert stopped == [("REC", "C")]
    assert r._active_rec is None


def test_no_recorder_callbacks_means_unhandled_so_fallback_runs():
    r = _runner(on_rec_start=None)
    evt = CardStarted(card_name="C", loop=1, scenario="SC", evidence_dir="dir")
    r._on_event_card_started(evt)
    assert evt.recorder_handled is False        # → run loop's inline fallback handles it


def test_missing_scenario_or_dir_is_ignored():
    r = _runner(on_rec_start=lambda sc, d: "REC")
    evt = CardStarted(card_name="C", loop=1)     # no scenario/evidence_dir
    r._on_event_card_started(evt)
    assert evt.recorder_handled is False
    assert r._active_rec is None


def test_recorder_start_error_is_isolated():
    logs = []
    r = _runner(on_rec_start=lambda sc, d: (_ for _ in ()).throw(RuntimeError("cam fail")))
    r.on_log = logs.append
    evt = CardStarted(card_name="C", loop=1, scenario="SC", evidence_dir="dir")
    r._on_event_card_started(evt)               # must not raise
    assert evt.recorder_handled is True
    assert r._active_rec is None
    assert any("Recorder start error" in m for m in logs)
