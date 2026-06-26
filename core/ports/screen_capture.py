"""
ScreenCapturePort (R-HEX driven port) — how the core obtains pixels of a region.

The core never calls a screen-grab library directly. A local desktop adapter wraps
PIL.ImageGrab/mss; a remote/web deployment fulfils the same contract with a capture
agent running on the SCADA host. Coordinates are absolute desktop space (R-HEX-3).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ScreenCapturePort(ABC):
    """Grab a rectangular region of the desktop. Returns an image object
    (PIL.Image for the local adapter) or None if capture is unavailable."""

    @abstractmethod
    def grab(self, x1: int, y1: int, x2: int, y2: int,
             monitor_index: int = 0) -> Any:
        raise NotImplementedError
