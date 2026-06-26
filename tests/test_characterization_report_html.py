"""
M0.1 — Characterization golden for the legacy HTML report writer
(ReportManager._write_html_report, the 1,128-line god method).

Renders Suite_Report.html from the committed normalize fixture and snapshots it
with volatile parts masked (timestamps, durations, absolute paths). When M2.5
decomposes the writer into LegacyReportComposer + report widgets, this golden
proves the rendered HTML is unchanged.
"""
import json
import re
import datetime
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
RAW = json.loads((FIX / "normalize_input.json").read_text(encoding="utf-8"))
GOLDEN = FIX / "legacy_report_golden.html"

# Fixed run window so only true non-determinism needs masking.
START = datetime.datetime(2026, 1, 1, 9, 0, 0)
END = datetime.datetime(2026, 1, 1, 9, 5, 0)


def _mask(html: str, tmp: Path) -> str:
    """Remove run-to-run volatility so the golden is stable."""
    h = html.replace(str(tmp), "<OUTDIR>").replace(str(tmp).replace("\\", "/"), "<OUTDIR>")
    # date-times (YYYY-MM-DD HH:MM:SS / DD/MM/YYYY HH:MM:SS), bare times, durations
    h = re.sub(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", "<TS>", h)
    h = re.sub(r"\d{2}/\d{2}/\d{4}[ T]?\d{2}:\d{2}:\d{2}", "<TS>", h)
    h = re.sub(r"\b\d{2}:\d{2}:\d{2}\b", "<TIME>", h)
    return h


def test_legacy_report_html_matches_golden(tmp_path):
    from iscs_reports import ReportManager

    normalized = ReportManager.normalize_results(RAW)
    evidence = ReportManager._scan_evidence_files(tmp_path)
    ReportManager._write_html_report(normalized, tmp_path, START, END, "Char Run", evidence)

    out = tmp_path / "Suite_Report.html"
    assert out.exists(), "legacy writer did not produce Suite_Report.html"
    current = _mask(out.read_text(encoding="utf-8"), tmp_path)

    if not GOLDEN.exists():
        GOLDEN.write_text(current, encoding="utf-8")

    expected = GOLDEN.read_text(encoding="utf-8")
    assert current == expected, (
        "legacy Suite_Report.html drifted from the golden. If intentional, delete "
        f"{GOLDEN.name} and regenerate.")
