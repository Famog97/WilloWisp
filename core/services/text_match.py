"""
OCR text matching (M2.4) — noise-tolerant comparison of expected text vs OCR output.

Pure string logic, no UI/screen/OCR-engine dependency. These are the comparisons
that decide whether an alarm's identifier / description / value / severity was
"seen" on screen — core to every verification's PASS/FAIL. Relocated verbatim from
``baru``; ``baru`` re-exports the functions as shims. ``TextMatcher`` is the
object form the verification split (M2.4 cont) binds to.
"""
from __future__ import annotations

import difflib
import re


def _ocr_canon(s: str) -> str:
    """Aggressively canonicalize text for OCR comparison: lowercase, unify
    common OCR confusions, and strip everything that isn't alphanumeric."""
    s = str(s).lower()
    # common OCR character confusions
    s = s.replace("|", "")        # pipe noise
    s = s.replace("o", "0")       # O/0
    s = s.replace("l", "1").replace("i", "1")  # l/I/1
    # drop all non-alphanumeric (hyphens, spaces, colons, etc.)
    return re.sub(r"[^a-z0-9]", "", s)


def _ocr_contains(expected: str, ocr_text: str) -> bool:
    """True if `expected` appears in `ocr_text`, tolerant of OCR noise.
    Tries, in order: exact substring, case/space-insensitive substring, and
    finally fully-canonicalized substring (separator- and confusion-insensitive)."""
    if not expected:
        return True
    exp_raw, ocr_raw = str(expected), str(ocr_text)
    # 1) exact
    if exp_raw in ocr_raw:
        return True
    # 2) case + whitespace normalized
    exp_n = " ".join(exp_raw.lower().split())
    ocr_n = " ".join(ocr_raw.lower().split())
    if exp_n and exp_n in ocr_n:
        return True
    # 3) fully canonical (handles dropped hyphens, pipes, O/0, l/1 confusion)
    exp_c, ocr_c = _ocr_canon(exp_raw), _ocr_canon(ocr_raw)
    if exp_c and exp_c in ocr_c:
        return True
    return False


def _ocr_fuzzy_contains(expected: str, ocr_text: str, threshold: float = 0.82) -> bool:
    """For longer phrases (e.g. descriptions): slide the expected phrase over the
    OCR text token-window and accept if best similarity >= threshold. Falls back
    to _ocr_contains first (cheap exact/canonical match)."""
    if _ocr_contains(expected, ocr_text):
        return True
    exp_n = " ".join(str(expected).lower().split())
    ocr_n = " ".join(str(ocr_text).lower().split())
    if not exp_n:
        return True
    if not ocr_n:
        return False
    # Whole-string ratio (cheap) — good when OCR text is roughly just the phrase
    if difflib.SequenceMatcher(None, exp_n, ocr_n).ratio() >= threshold:
        return True
    # Sliding window over OCR tokens sized to the expected phrase
    exp_tokens = exp_n.split()
    ocr_tokens = ocr_n.split()
    w = len(exp_tokens)
    if w == 0 or len(ocr_tokens) < 1:
        return False
    for i in range(0, max(1, len(ocr_tokens) - w + 1)):
        window = " ".join(ocr_tokens[i:i + w])
        if difflib.SequenceMatcher(None, exp_n, window).ratio() >= threshold:
            return True
    return False


class TextMatcher:
    """Object form of the noise-tolerant matchers (for injection into policies)."""

    @staticmethod
    def canon(s: str) -> str:
        return _ocr_canon(s)

    @staticmethod
    def contains(expected: str, ocr_text: str) -> bool:
        return _ocr_contains(expected, ocr_text)

    @staticmethod
    def fuzzy_contains(expected: str, ocr_text: str, threshold: float = 0.82) -> bool:
        return _ocr_fuzzy_contains(expected, ocr_text, threshold)
