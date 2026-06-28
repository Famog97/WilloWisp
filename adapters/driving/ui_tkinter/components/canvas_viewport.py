"""
adapters/driving/ui_tkinter/components/canvas_viewport.py

This file's responsibility is: map between canvas-pixel coordinates and absolute
screen coordinates (R-HEX-3 — the pure coordinate model, separated from the widget).

The overlay canvas is 1:1 with the screen, offset by the window's screen origin. The
origin comes from an injected provider (the live window position), so the maths here
imports no tkinter and is unit-testable with a fixed origin.
"""
from __future__ import annotations

from typing import Callable, Tuple


class CanvasViewport:
    def __init__(self, origin_provider: Callable[[], Tuple[int, int]]) -> None:
        self._origin = origin_provider          # () -> (origin_x, origin_y) on screen

    def to_abs(self, cx: int, cy: int) -> Tuple[int, int]:
        ox, oy = self._origin()
        return cx + ox, cy + oy

    def to_canvas(self, ax: int, ay: int) -> Tuple[int, int]:
        ox, oy = self._origin()
        return ax - ox, ay - oy
