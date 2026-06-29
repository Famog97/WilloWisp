"""
_check_color — the colour row must judge the panel's ACTUAL colour against the
severity-derived expectation, not merely look for the expected colour.

Regression for the observed bug: IO list severity 2 -> expect ORANGE, but the system
shows value 1 (RED). The row used to PASS and echo "ORANGE detected"; it must FAIL and
report that the panel actually shows RED.
"""
from core.services.verification_policy import AlarmPanelVerificationPolicy
from core.domain.observation import PanelObservation
from core.services.config import SEVERITY_MATRIX

RED, ORANGE = (255, 0, 0), (255, 126, 0)


def _namer(rgb):
    for e in SEVERITY_MATRIX.values():
        if e.get("color") == rgb:
            return e.get("name", "")
    return ""


def _policy():
    return AlarmPanelVerificationPolicy({}, color_namer=_namer)


def _check(expected_rgb, *, detected, found_target, found_grey=True):
    obs = PanelObservation(found_target=found_target, found_grey=found_grey,
                           detected_color=detected)
    return _policy()._check_color({"color": expected_rgb}, obs, "alarm_panel")


def test_pass_when_actual_colour_matches_expected():
    r = _check(RED, detected="RED", found_target=True)
    assert r.status == "PASS" and "RED" in r.msg


def test_fail_when_actual_colour_differs_from_expected():
    # severity 2 -> expect ORANGE; panel actually shows RED -> FAIL, naming both.
    r = _check(ORANGE, detected="RED", found_target=False)
    assert r.status == "FAIL"
    assert "ORANGE" in r.msg and "RED" in r.msg


def test_fail_even_when_found_target_true_but_actual_is_wrong():
    # The exact old false positive: a loose match set found_target=True, yet the panel
    # is RED while ORANGE was expected. Reading the real colour must still FAIL it.
    r = _check(ORANGE, detected="RED", found_target=True)
    assert r.status == "FAIL"
    assert "shows RED" in r.msg


def test_falls_back_to_liveness_when_colour_unreadable():
    # Blink-off / unreadable frame -> detected None -> old behaviour by found_target.
    assert _check(RED, detected=None, found_target=True).status == "PASS"
    assert _check(RED, detected=None, found_target=False).status == "FAIL"
