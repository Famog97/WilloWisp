"""
core/domain/observation.py

This file's responsibility is: hold what verification perception observed on the
alarm panel — the captured image, merged OCR text, colour/blink flags, and latency.

Pure value object: no perception, no decision logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PanelObservation:
    best_img: Any = None          # PIL image of the best-evidence frame (or None)
    merged_text: str = ""         # OCR text read from the panel
    found_target: bool = False    # the (expected) alarm colour was seen
    found_grey: bool = False      # the blink "off" colour was seen
    elapsed_latency: float = 0.0  # seconds from trigger to first confirmed frame
    detected_color: Any = None    # the alarm colour ACTUALLY shown (palette name), or None
