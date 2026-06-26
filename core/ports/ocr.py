"""
OcrPort (R-HEX driven port) — how the core reads text from an image.

The core's verification logic asks "what text is in this image?"; the local adapter
wraps Tesseract (`iscs_OCR`), but a different OCR/vision backend can satisfy the same
contract. The core never imports pytesseract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OcrPort(ABC):
    @abstractmethod
    def read(self, image: Any, layout: str = "block", lang: str = "eng") -> str:
        """Recognize text. ``layout`` ∈ {tabular, block, single_line, sparse}."""
        raise NotImplementedError

    @abstractmethod
    def read_digits(self, image: Any, psm: int = 10) -> str:
        """Recognize an isolated numeric cell (digit whitelist)."""
        raise NotImplementedError
