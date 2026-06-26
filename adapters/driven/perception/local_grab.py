"""Local desktop ScreenCapturePort adapter — wraps PIL.ImageGrab.

Driven adapter (outside the hexagon): the only place screen-grab libraries are
imported. Lazy import so the module loads even where PIL is unavailable.
"""
from __future__ import annotations

from typing import Any

from core.ports.screen_capture import ScreenCapturePort


class LocalScreenCapture(ScreenCapturePort):
    def grab(self, x1: int, y1: int, x2: int, y2: int, monitor_index: int = 0) -> Any:
        from PIL import ImageGrab  # lazy: optional dependency
        return ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
