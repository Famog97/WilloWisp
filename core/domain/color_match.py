"""
core/domain/color_match.py

This file's responsibility is: classify the colour a panel is *actually* showing into
one of the known severity colours (RED / ORANGE / YELLOW / GREEN), so verification can
compare the real colour against the one the IO-list severity implies.

The colour is never stored in the IO list — it is derived from severity via the
severity matrix (sev 1->RED, 2->ORANGE, 3->YELLOW, 0->GREEN). To catch a wrong colour
(e.g. IO list says severity 2 -> expect ORANGE, but the system shows value 1 -> RED),
we must read the panel's actual colour and compare. This module is the actual-colour
reader's pure core: no PIL, no screen access. The caller passes the colour histogram
(``[(count, rgb), ...]`` from ``Image.getcolors()``) plus the severity palette.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

RGB = Tuple[int, int, int]


def _as_rgb(c) -> RGB:
    if isinstance(c, (tuple, list)):
        return (int(c[0]), int(c[1]), int(c[2]))
    return (int(c), int(c), int(c))


def is_background(rgb: RGB, sat_threshold: int = 40) -> bool:
    """A pixel is background/chrome, not an alarm colour, when it is near-grey.

    White, black and the blink-grey all have R≈G≈B, so their channel span is tiny;
    a real alarm colour (red/orange/yellow/green) has a large span. This filters out
    the panel background, white text and the blink "off" frame before classification.
    """
    r, g, b = rgb
    return (max(r, g, b) - min(r, g, b)) < sat_threshold


def _dist2(a: RGB, b: RGB) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def nearest_color(rgb: RGB, palette: List[Tuple[str, RGB]]) -> Tuple[Optional[str], float]:
    """(name, euclidean distance) of the nearest palette colour, or (None, inf)."""
    best_name, best_d2 = None, None
    for name, prgb in palette:
        d2 = _dist2(rgb, _as_rgb(prgb))
        if best_d2 is None or d2 < best_d2:
            best_name, best_d2 = name, d2
    if best_d2 is None:
        return None, float("inf")
    return best_name, best_d2 ** 0.5


def classify_with_votes(colors, palette, *, max_dist: float = 90.0,
                        sat_threshold: int = 40) -> Tuple[Optional[str], int]:
    """Dominant alarm colour by pixel vote, plus its vote count.

    Each saturated colour in the histogram votes (weighted by pixel count) for its
    nearest palette colour, provided it is within ``max_dist`` (muddy transition pixels
    beyond every palette colour don't vote). The bulk of the panel therefore decides,
    so a few orange-ish edge pixels can't flip a red panel to ORANGE.
    """
    votes: Dict[str, int] = {}
    for entry in colors or []:
        count, raw = entry
        rgb = _as_rgb(raw)
        if is_background(rgb, sat_threshold):
            continue
        name, dist = nearest_color(rgb, palette)
        if name is not None and dist <= max_dist:
            votes[name] = votes.get(name, 0) + int(count)
    if not votes:
        return None, 0
    win = max(votes, key=votes.get)
    return win, votes[win]


def classify_alarm_color(colors, palette, *, max_dist: float = 90.0,
                         sat_threshold: int = 40) -> Optional[str]:
    """The dominant alarm-colour name the panel is showing, or None if it shows none."""
    return classify_with_votes(colors, palette, max_dist=max_dist,
                               sat_threshold=sat_threshold)[0]


def dominant_saturated_rgb(colors, *, sat_threshold: int = 40) -> Optional[RGB]:
    """The single most common non-background colour in the histogram (the panel's real
    alarm colour), for diagnostics/evidence. None if the panel shows only grey/white."""
    best_rgb, best_count = None, -1
    for entry in colors or []:
        count, raw = entry
        rgb = _as_rgb(raw)
        if is_background(rgb, sat_threshold):
            continue
        if int(count) > best_count:
            best_rgb, best_count = rgb, int(count)
    return best_rgb


def palette_from_matrix(matrix) -> List[Tuple[str, RGB]]:
    """Severity matrix ``{sev: {color, name}}`` -> ``[(name, rgb)]`` for classification."""
    out: List[Tuple[str, RGB]] = []
    for entry in matrix.values():
        rgb = entry.get("color")
        name = entry.get("name", "")
        if rgb and name:
            out.append((name, _as_rgb(rgb)))
    return out
