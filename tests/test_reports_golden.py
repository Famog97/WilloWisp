"""
Golden-snapshot test for ReportManager.normalize_results.

Unlike the unit tests in test_reports_normalize.py (which assert specific
properties), this freezes the FULL normalized output for a realistic raw result
set — multiple points, multiple loops, a rerun (FAIL→PASS), and a custom
asset-bound check. Any change to the report data contract that alters the output
will fail this test, which is the regression backstop the migration relies on.

To intentionally update the snapshot after a deliberate behavior change:
    python -c "import json; from iscs_reports import ReportManager as R; \
    raw=json.load(open('tests/fixtures/normalize_input.json',encoding='utf-8')); \
    json.dump(R.normalize_results(raw), open('tests/fixtures/normalize_expected.json','w',encoding='utf-8'), \
    indent=2, ensure_ascii=False, sort_keys=True)"
"""
import json
from pathlib import Path

from iscs_reports import ReportManager

FIXTURES = Path(__file__).parent / "fixtures"


def _roundtrip(obj):
    # Normalize through JSON so tuple/dict ordering matches the stored snapshot.
    return json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def test_normalize_results_matches_golden_snapshot():
    raw = json.loads((FIXTURES / "normalize_input.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / "normalize_expected.json").read_text(encoding="utf-8"))

    actual = _roundtrip(ReportManager.normalize_results(raw))

    assert actual == expected, (
        "normalize_results output drifted from the golden snapshot. If this change "
        "is intentional, regenerate tests/fixtures/normalize_expected.json (see the "
        "module docstring)."
    )


def test_golden_snapshot_invariants_hold():
    # Spot-check the properties the snapshot encodes, so a careless snapshot
    # regen can't silently bless a regression.
    raw = json.loads((FIXTURES / "normalize_input.json").read_text(encoding="utf-8"))
    out = ReportManager.normalize_results(raw)

    by = {(r["id"], r["loop_num"]): r for r in out}
    assert len(out) == 3

    rerun = by[("BUCS-AMS-ACU-OCC-0009", 1)]
    assert rerun["overall"] == "PASS"
    assert len(rerun["attempts"]) == 2          # FAIL then PASS, both kept
    assert [a["overall"] for a in rerun["attempts"]] == ["FAIL", "PASS"]

    custom = by[("BUCS-AMS-ACU-OCC-0008", 2)]
    assert custom["failure_category"] == "Custom Asset Mismatch"
