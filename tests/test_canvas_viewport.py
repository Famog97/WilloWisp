"""
M5 / R-HEX-3 — CanvasViewport: pure canvas<->absolute coordinate maths.

No display needed (origin is an injected provider), so the coordinate model is
unit-tested in isolation from the OverlayWindow widget.
"""
from adapters.driving.ui_tkinter.components.canvas_viewport import CanvasViewport


def test_round_trips_with_fixed_origin():
    vp = CanvasViewport(lambda: (100, 50))         # window origin at screen (100, 50)
    assert vp.to_abs(10, 5) == (110, 55)
    assert vp.to_canvas(110, 55) == (10, 5)
    # round-trip is identity
    ax, ay = vp.to_abs(33, 77)
    assert vp.to_canvas(ax, ay) == (33, 77)


def test_uses_live_origin_each_call():
    origin = [0, 0]
    vp = CanvasViewport(lambda: tuple(origin))
    assert vp.to_abs(5, 5) == (5, 5)
    origin[0], origin[1] = 200, 300              # window moved
    assert vp.to_abs(5, 5) == (205, 305)
    assert vp.to_canvas(205, 305) == (5, 5)
