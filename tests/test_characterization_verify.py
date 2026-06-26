"""
M0.1 — Characterization of ISCSVerifier.verify_alarm_panel (the 256-line god method).

Drives the no-sampler "burst" path offline by faking perception (screen grab, OCR,
colour test), and pins the PASS/FAIL sub-check rows the decision policy produces.
When M3.2 splits this into VerificationCoordinator + AlarmPanelVerificationPolicy,
these rows must be reproduced from the same inputs.
"""
from types import SimpleNamespace

import pytest

import baru


class _FakeImg:
    size = (120, 24)
    def crop(self, box): return self
    def convert(self, *a): return self
    def save(self, path): open(path, "wb").close()


class _FakeZone:
    x1, y1, x2, y2 = 0, 0, 120, 24
    monitor_index = 0


@pytest.fixture
def fast_config():
    return {"tesseract_lang": "eng", "detection_duration_sec": 0.2,
            "blink_burst_frames": 1, "blink_burst_sec": 0.01,
            "severity_matrix": baru.SEVERITY_MATRIX}


def _patch_perception(monkeypatch, ocr_text, colour_present):
    monkeypatch.setattr(baru, "PIL_AVAILABLE", True)
    monkeypatch.setattr(baru, "TESSERACT_AVAILABLE", True)
    monkeypatch.setattr(baru, "ImageGrab", SimpleNamespace(grab=lambda **k: _FakeImg()))
    monkeypatch.setattr(baru, "ocr_run", lambda *a, **k: ocr_text)


def _verifier(monkeypatch, colour_present):
    v = baru.ISCSVerifier({"alarm_panel": _FakeZone()}, {"severity_matrix": baru.SEVERITY_MATRIX})
    # decouple from real pixel inspection: the colour decision is an explicit input here
    monkeypatch.setattr(v, "_color_present", lambda *a, **k: colour_present)
    return v


def _expected():
    return {"point_id": "PT-1", "description": "Front Door", "label": "HIGH ALARM",
            "severity": "1", "color": (255, 0, 0)}


def _rows(results):
    return {r.step: r.status for r in results}


def test_verify_alarm_panel_all_pass(monkeypatch, tmp_path, fast_config):
    _patch_perception(monkeypatch, "PT-1 Front Door HIGH ALARM 1", colour_present=True)
    v = _verifier(monkeypatch, colour_present=True)
    v.config = fast_config
    rows = _rows(v.verify_alarm_panel(_expected(), tmp_path, point_idx=0))
    assert rows["alarm_panel/identifier"] == "PASS"
    assert rows["alarm_panel/value"] == "PASS"
    assert rows["alarm_panel/severity"] == "PASS"
    assert rows["alarm_panel/color"] == "PASS"
    assert rows["alarm_panel/description"] == "PASS"


def test_verify_alarm_panel_colour_miss_fails_color_row(monkeypatch, tmp_path, fast_config):
    _patch_perception(monkeypatch, "PT-1 Front Door HIGH ALARM 1", colour_present=False)
    v = _verifier(monkeypatch, colour_present=False)
    v.config = fast_config
    rows = _rows(v.verify_alarm_panel(_expected(), tmp_path, point_idx=0))
    assert rows["alarm_panel/color"] == "FAIL"
    assert rows["alarm_panel/identifier"] == "PASS"   # text still found


def test_verify_alarm_panel_missing_identifier_fails(monkeypatch, tmp_path, fast_config):
    _patch_perception(monkeypatch, "SOME OTHER TEXT", colour_present=True)
    v = _verifier(monkeypatch, colour_present=True)
    v.config = fast_config
    rows = _rows(v.verify_alarm_panel(_expected(), tmp_path, point_idx=0))
    assert rows["alarm_panel/identifier"] == "FAIL"
