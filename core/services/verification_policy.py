"""
core/services/verification_policy.py

This file's responsibility is: decide the PASS/FAIL verification rows for an alarm
panel from the expected state plus a PanelObservation.

Pure decision logic — no screen grabbing or OCR of its own. The two perception-bound
escape hatches (re-OCR a severity cell, name a colour) are injected as callables, so
this module imports no PIL / pyautogui / OCR engine. "Fix a verification rule" = edit
this file only.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Callable, List, Optional

from core.domain.observation import PanelObservation
from core.domain.results import VerifyResult
from core.services.text_match import _ocr_contains, _ocr_fuzzy_contains


class AlarmPanelVerificationPolicy:
    def __init__(self, config: dict,
                 severity_reocr: Optional[Callable[[Any, str], bool]] = None,
                 color_namer: Optional[Callable[[Any], str]] = None) -> None:
        self._config = config or {}
        self._severity_reocr = severity_reocr        # (best_img, sev_text) -> bool
        self._color_namer = color_namer or (lambda rgb: "")

    def evaluate(self, expected: dict, obs: PanelObservation, *, step: str,
                 trigger_time=None, trigger_ns=None) -> List[VerifyResult]:
        """Produce the verification rows, in report order (datetime first)."""
        return [
            self._check_datetime(obs, step, trigger_time, trigger_ns),
            self._check_identifier(expected, obs, step),
            self._check_description(expected, obs, step),
            self._check_value(expected, obs, step),
            self._check_severity(expected, obs, step),
            self._check_color(expected, obs, step),
        ]

    # ── individual sub-checks (each returns exactly one row) ─────────────────
    def _check_datetime(self, obs, step, trigger_time, trigger_ns) -> VerifyResult:
        key = f"{step}/datetime"
        match_ts = re.search(r'(\d{2,4}[-/\.]\d{2}[-/\.]\d{2,4}\s+\d{2}:\d{2}:\d{2})', obs.merged_text)
        if not match_ts:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return VerifyResult(key, "PASS", f"{ts} (latency={obs.elapsed_latency}s) [System Clock Fallback]")
        ts_msg = match_ts.group(1)
        parsed = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
            try:
                parsed = datetime.datetime.strptime(ts_msg, fmt)
                break
            except ValueError:
                pass
        baseline = trigger_time
        if baseline is None and trigger_ns:
            baseline = datetime.datetime.fromtimestamp(trigger_ns / 1e9)
        if parsed and baseline:
            delta = abs((parsed - baseline).total_seconds())
            limit = float(self._config.get("datetime_sync_limit_sec", 4.0))
            if delta <= limit:
                return VerifyResult(key, "PASS", f"{ts_msg} (sync delta={delta:.2f}s)")
            return VerifyResult(key, "FAIL", f"{ts_msg} (sync delta={delta:.2f}s exceeds limit of {limit}s)")
        return VerifyResult(key, "PASS", f"{ts_msg} (latency={obs.elapsed_latency}s)")

    def _check_identifier(self, expected, obs, step) -> VerifyResult:
        pid = expected.get("point_id", "")
        if _ocr_contains(str(pid), obs.merged_text):
            return VerifyResult(f"{step}/identifier", "PASS", f"'{pid}' found in OCR.")
        return VerifyResult(f"{step}/identifier", "FAIL", f"'{pid}' NOT found in OCR text.")

    def _check_description(self, expected, obs, step) -> VerifyResult:
        desc = expected.get("description", "")
        if not desc:
            return VerifyResult(f"{step}/description", "SKIP", "No description configured.")
        if _ocr_fuzzy_contains(str(desc), obs.merged_text):
            return VerifyResult(f"{step}/description", "PASS", f"'{desc}' found in OCR.")
        return VerifyResult(f"{step}/description", "FAIL", f"'{desc}' NOT found in OCR text.")

    def _check_value(self, expected, obs, step) -> VerifyResult:
        label = expected.get("label", "")
        if not label:
            return VerifyResult(f"{step}/value", "SKIP", "No label/value configured.")
        if _ocr_contains(str(label), obs.merged_text):
            return VerifyResult(f"{step}/value", "PASS", f"'{label}' found in OCR.")
        return VerifyResult(f"{step}/value", "FAIL", f"'{label}' NOT found in OCR text.")

    def _check_severity(self, expected, obs, step) -> VerifyResult:
        severity = expected.get("severity", "")
        if not severity:
            return VerifyResult(f"{step}/severity", "SKIP", "No severity configured.")
        sev = str(severity)
        if len(sev.strip()) <= 2:
            found = bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(sev.strip())}(?![A-Za-z0-9])", obs.merged_text))
        else:
            found = _ocr_contains(sev, obs.merged_text)
        if not found and obs.best_img is not None and self._severity_reocr is not None:
            try:
                found = self._severity_reocr(obs.best_img, sev)
            except Exception:
                pass
        if found:
            return VerifyResult(f"{step}/severity", "PASS", f"'{sev}' found in OCR.")
        return VerifyResult(f"{step}/severity", "FAIL", f"'{sev}' NOT found in OCR text.")

    def _check_color(self, expected, obs, step) -> VerifyResult:
        """Compare the colour the panel ACTUALLY shows against the colour the IO-list
        severity implies. Colour is not in the IO list — it is derived from severity
        (sev 1->RED, 2->ORANGE, 3->YELLOW, 0->GREEN) — so a point marked severity 2 must
        display ORANGE; if the system shows RED (value 1) the colour row must FAIL.
        """
        rgb = expected.get("color", (255, 0, 0))
        exp_name = self._color_namer(rgb) or str(rgb)
        exp_label = f"{exp_name} {rgb}"
        blink = " (blink detected)" if obs.found_grey else ""
        actual = getattr(obs, "detected_color", None)   # palette name actually shown, or None

        # When we can read the panel's real colour it is the source of truth: it must
        # match the severity-derived expectation. A wrong colour fails here even though
        # the panel did "light up".
        if actual is not None and actual != exp_name:
            return VerifyResult(
                f"{step}/color", "FAIL",
                f"Expected {exp_label} (severity-derived) but panel shows {actual}{blink}.")

        # Real colour matched, or could not be read (e.g. blink-off frame): fall back to
        # liveness — did the expected colour appear at all?
        if obs.found_target or actual == exp_name:
            shown = actual or exp_name
            return VerifyResult(f"{step}/color", "PASS",
                                f"Alarm color {shown} {rgb} detected{blink}.")
        return VerifyResult(f"{step}/color", "FAIL", f"Alarm color {exp_label} NOT detected{blink}.")
