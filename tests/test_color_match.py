"""
color_match — classify the panel's ACTUAL colour against the severity palette.

The negative test that motivated this: the IO list marks a point severity 2 (-> expect
ORANGE), but the system shows value 1 (RED). Classification must report RED so the
verifier can fail the colour row, instead of echoing the expected ORANGE.
"""
from core.domain.color_match import (
    classify_alarm_color, classify_with_votes, nearest_color, is_background,
    palette_from_matrix,
)
from core.services.config import SEVERITY_MATRIX

PALETTE = palette_from_matrix(SEVERITY_MATRIX)   # [(RED,(255,0,0)), (ORANGE,..), ...]

RED, ORANGE, YELLOW, GREEN, GREY, WHITE = (
    (255, 0, 0), (255, 126, 0), (255, 255, 0), (32, 169, 72), (189, 189, 189), (255, 255, 255))


def _hist(*pairs):
    """Build a getcolors()-style histogram: _hist((count, rgb), ...)."""
    return list(pairs)


def test_palette_has_the_four_severity_colours():
    names = {n for n, _ in PALETTE}
    assert {"RED", "ORANGE", "YELLOW", "GREEN"} <= names


def test_background_filter_skips_grey_white_black():
    assert is_background(GREY) and is_background(WHITE) and is_background((0, 0, 0))
    assert not is_background(RED) and not is_background(ORANGE) and not is_background(GREEN)


def test_red_panel_classifies_red_not_orange():
    # the exact negative-test case: a red panel must NOT read as orange
    hist = _hist((5000, RED), (3000, GREY), (1200, WHITE))
    assert classify_alarm_color(hist, PALETTE) == "RED"


def test_each_severity_colour_classifies_to_itself():
    assert classify_alarm_color(_hist((100, RED)), PALETTE) == "RED"
    assert classify_alarm_color(_hist((100, ORANGE)), PALETTE) == "ORANGE"
    assert classify_alarm_color(_hist((100, YELLOW)), PALETTE) == "YELLOW"
    assert classify_alarm_color(_hist((100, GREEN)), PALETTE) == "GREEN"


def test_alarm_red_shade_still_reads_red():
    # a realistic "alarm red" (237,28,36) is nearer RED than ORANGE
    name, _ = nearest_color((237, 28, 36), PALETTE)
    assert name == "RED"
    assert classify_alarm_color(_hist((4000, (237, 28, 36)), (2000, GREY)), PALETTE) == "RED"


def test_bulk_red_outvotes_a_few_orange_edge_pixels():
    # anti-aliased edges can lean orange, but the bulk red must win
    hist = _hist((6000, RED), (120, ORANGE), (3000, GREY))
    assert classify_alarm_color(hist, PALETTE) == "RED"


def test_grey_only_panel_has_no_alarm_colour():
    assert classify_alarm_color(_hist((9000, GREY), (1000, WHITE)), PALETTE) is None


def test_votes_count_reflects_dominant_pixels():
    name, votes = classify_with_votes(_hist((5000, RED), (3000, GREY)), PALETTE)
    assert name == "RED" and votes == 5000
