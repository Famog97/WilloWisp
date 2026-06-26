"""Tesseract OcrPort adapter — delegates to the existing iscs_OCR engine.

Driven adapter (outside the hexagon). For M1 it thinly wraps the legacy module;
M2.4 moves the preprocessing/reader logic itself behind this adapter.
"""
from __future__ import annotations

from typing import Any

from core.ports.ocr import OcrPort


class TesseractOcr(OcrPort):
    def read(self, image: Any, layout: str = "block", lang: str = "eng") -> str:
        import iscs_OCR  # lazy
        return iscs_OCR.run(image, lang=lang, layout=layout)

    def read_digits(self, image: Any, psm: int = 10) -> str:
        import iscs_OCR  # lazy
        return iscs_OCR.run_digits(image, psm=psm)
