"""
Characterization tests for the OCR text-matching helpers in baru.py
(_ocr_canon / _ocr_contains / _ocr_fuzzy_contains).

These are the noise-tolerant comparisons that decide whether an alarm's
identifier / description / severity was "seen" on screen — core to every
verification's PASS/FAIL. Pure string logic, no Tesseract needed.

baru.py is imported directly (it imports cleanly without opening a Tk window).
If optional desktop deps are unavailable (e.g. headless CI), the module is
skipped rather than failing the suite.
"""
import pytest

baru = pytest.importorskip("baru", reason="baru.py optional desktop deps unavailable")

canon  = baru._ocr_canon
match  = baru._ocr_contains
fuzzy  = baru._ocr_fuzzy_contains


# ──────────────────────────────────────────────────────────────────────────────
#  _ocr_canon — canonicalization
# ──────────────────────────────────────────────────────────────────────────────

def test_canon_strips_separators_and_lowercases():
    assert canon("BUCS-AMS-0008") == "bucsams0008"


def test_canon_unifies_common_ocr_confusions():
    # o→0, l→1, i→1, pipes dropped
    assert canon("O") == "0"
    assert canon("l") == "1"
    assert canon("I") == "1"
    assert canon("a|b") == "ab"


# ──────────────────────────────────────────────────────────────────────────────
#  _ocr_contains — layered exact/normalized/canonical matching
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_expected_always_matches():
    assert match("", "anything") is True


def test_exact_substring():
    assert match("ALARM", "HIGH ALARM STATE") is True


def test_case_and_whitespace_insensitive():
    assert match("high alarm", "HIGH    ALARM") is True


def test_canonical_match_ignores_hyphens():
    assert match("BUCS-AMS-0008", "row: bucs ams 0008 detected") is True


def test_canonical_match_handles_o_zero_confusion():
    # OCR read "PT-O8" where the screen really shows "PT08"
    assert match("PT-O8", "value PT08 here") is True


def test_no_false_positive_on_unrelated_text():
    assert match("MISSING-POINT", "completely unrelated content") is False


# ──────────────────────────────────────────────────────────────────────────────
#  _ocr_fuzzy_contains — similarity fallback for longer phrases
# ──────────────────────────────────────────────────────────────────────────────

def test_fuzzy_passes_exact_phrase():
    assert fuzzy("Intrusion Alarm", "Status: Intrusion Alarm active") is True


def test_fuzzy_tolerates_minor_ocr_error():
    # doubled letter from OCR — exact/canonical miss, fuzzy catches it
    assert fuzzy("Intrusion Alarm", "Intrusion Alaarm") is True


def test_fuzzy_rejects_unrelated_phrase():
    assert fuzzy("Intrusion Alarm", "Fire Detector Panel Reset") is False


def test_fuzzy_threshold_is_respected():
    # Not a substring (so _ocr_contains misses), similarity ~0.90: clears the
    # default 0.82 threshold but is rejected when the bar is raised to 0.95.
    assert fuzzy("Intrusion Alarm", "Intrussion Alerm") is True
    assert fuzzy("Intrusion Alarm", "Intrussion Alerm", threshold=0.95) is False


def test_fuzzy_empty_ocr_text_is_false_for_nonempty_expected():
    assert fuzzy("Something", "") is False
