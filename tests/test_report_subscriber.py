"""
Tests for B2 (P2.3 cutover) — report generation as an event subscriber.

ReportManager.on_suite_completed handles SuiteCompleted by calling generate_reports
(stubbed here so no files are written) and marks the event handled so the runner's
safety-net fallback knows not to double-generate. The live run confirms a real
Suite_Report.html + Excel still appear.
"""
import pytest

from iscs_reports import ReportManager
from iscs_core import EventBus, SuiteCompleted


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(ReportManager, "generate_reports",
                        lambda *a, **k: calls.append((a, k)))
    return calls


def _event(**kw):
    base = dict(title="T", results=[{"overall": "PASS"}], output_dir="out_dir",
                start_time="t0", end_time="t1")
    base.update(kw)
    return SuiteCompleted(**base)


def test_handler_calls_generate_reports_with_payload(captured):
    evt = _event()
    ReportManager.on_suite_completed(evt)
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[0] == [{"overall": "PASS"}]      # results
    assert args[1] == "out_dir"                  # output_dir
    assert kwargs.get("title") == "T"
    assert evt.report_generated is True          # marks handled (suppresses fallback)


def test_handler_noops_without_results(captured):
    evt = _event(results=[])
    ReportManager.on_suite_completed(evt)
    assert captured == []
    assert evt.report_generated is False         # NOT handled → runner fallback runs


def test_handler_noops_without_output_dir(captured):
    evt = _event(output_dir=None)
    ReportManager.on_suite_completed(evt)
    assert captured == []
    assert evt.report_generated is False


def test_handler_logs_success_via_event_on_log(captured):
    logs = []
    ReportManager.on_suite_completed(_event(on_log=logs.append))
    assert any("generated successfully" in m for m in logs)


def test_handler_claims_handled_and_logs_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(ReportManager, "generate_reports", boom)

    logs = []
    evt = _event(on_log=logs.append)
    ReportManager.on_suite_completed(evt)         # must not raise
    assert evt.report_generated is True           # claimed → no second attempt
    assert any("Failed to generate" in m for m in logs)


def test_subscribed_to_bus_generates_on_publish(captured):
    bus = EventBus()
    bus.subscribe(SuiteCompleted, ReportManager.on_suite_completed)
    evt = _event()
    delivered = bus.publish(evt)
    assert delivered == 1
    assert len(captured) == 1
    assert evt.report_generated is True
