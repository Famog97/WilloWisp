"""
M0.4 — Run-path equivalence baseline (B2 oracle).

The legacy run path's offline-observable output is its persisted `suite_results.json`.
`run_baseline_suite_results.json` is a real captured legacy run (2 points). Its
normalized form is frozen here as the **equivalence oracle**: when the duplicate
run paths collapse into the canonical `SuiteScheduler` (M3.4), the new path — run
on the same scenario — must produce a `suite_results.json` whose normalized form
equals this baseline. Until then, this pins the legacy baseline so it cannot drift.
"""
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"
BASELINE_RAW = FIX / "run_baseline_suite_results.json"
BASELINE_NORM = FIX / "run_baseline_normalized.json"


def _normalize(raw):
    from iscs_reports import ReportManager
    return ReportManager.normalize_results(raw)


def test_legacy_run_baseline_normalizes_stably():
    raw = json.loads(BASELINE_RAW.read_text(encoding="utf-8"))
    current = _normalize(raw)

    if not BASELINE_NORM.exists():
        BASELINE_NORM.write_text(json.dumps(current, indent=2, ensure_ascii=False, default=str),
                                 encoding="utf-8")

    expected = json.loads(BASELINE_NORM.read_text(encoding="utf-8"))
    # Compare via canonical JSON so dict ordering / types don't cause false diffs.
    assert json.dumps(current, sort_keys=True, default=str) == \
           json.dumps(expected, sort_keys=True, default=str), (
        "Legacy run baseline drifted. The canonical SuiteScheduler path (M3.4) must "
        "reproduce this normalized output to satisfy B2.")
