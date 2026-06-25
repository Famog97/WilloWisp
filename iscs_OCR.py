"""
iscs_OCR.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OCR and Image Analysis Subsystem for ISCS Framework.
Encapsulates Tesseract interaction and adaptive image preprocessing.
"""

from __future__ import annotations
import os
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("AutoClick")

try:
    import pytesseract
    _PYTESSERACT_OK = True
except ImportError:
    _PYTESSERACT_OK = False

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False

TESSERACT_AVAILABLE = False

import shutil as _shutil

def initialize(tesseract_cmd: str) -> bool:
    """Configures the Tesseract executable path and updates availability status."""
    global TESSERACT_AVAILABLE
    resolved_cmd = tesseract_cmd
    
    # Check absolute path first; if missing, check if globally registered in system PATH
    path_exists = tesseract_cmd and os.path.exists(tesseract_cmd)
    globally_available = False
    if not path_exists:
        found_in_path = _shutil.which(tesseract_cmd or "tesseract")
        if found_in_path:
            resolved_cmd = found_in_path
            globally_available = True

    if path_exists or globally_available:
        try:
            pytesseract.pytesseract.tesseract_cmd = resolved_cmd
            pytesseract.get_tesseract_version()
            TESSERACT_AVAILABLE = True
            logger.info(f"iscs_OCR: Tesseract initialized at {resolved_cmd}")
        except Exception as e:
            TESSERACT_AVAILABLE = False
            logger.error(f"iscs_OCR: Tesseract initialization failed: {e}")
    else:
        TESSERACT_AVAILABLE = False
        if tesseract_cmd:
            logger.warning(f"iscs_OCR: Tesseract executable not found at {tesseract_cmd} or in system PATH")
    return TESSERACT_AVAILABLE

def analyze_image(img: Image.Image, region: Optional[Tuple[int, int, int, int]] = None) -> Dict[str, Any]:
    """
    Sample every 5th pixel and compute brightness/contrast/color stats.
    Returns analysis for adaptive preprocessing.
    """
    if not _NP_OK or not _PIL_OK or img is None:
        return {
            "avg_brightness": 0.5, "contrast": 0.5, "dark_ratio": 0,
            "white_ratio": 0, "dark_red_ratio": 0, "dark_blue_ratio": 0,
            "should_invert": False, "is_totally_dark": False
        }

    arr = np.array(img.convert("RGBA"), dtype=np.float32)
    if region:
        x1, y1, x2, y2 = region
        arr = arr[y1:y2, x1:x2]

    sampled = arr[::5, ::5]
    if sampled.size == 0:
        return {
            "avg_brightness": 0.5, "contrast": 0.5, "dark_ratio": 0,
            "white_ratio": 0, "dark_red_ratio": 0, "dark_blue_ratio": 0,
            "should_invert": False, "is_totally_dark": False
        }

    r, g, b = sampled[:, :, 0], sampled[:, :, 1], sampled[:, :, 2]
    lum   = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    avg      = float(np.mean(lum))
    variance = float(np.mean(lum ** 2)) - avg ** 2
    contrast = float(np.sqrt(max(variance, 0)))
    dark_ratio  = float(np.mean(lum < 0.3))
    white_ratio = float(np.mean(lum > 0.9))

    dark_red_ratio  = float(np.mean((r > 100) & (g < 60) & (b < 60) & (lum < 0.4)))
    dark_blue_ratio = float(np.mean((b > 100) & (r < 80) & (g < 80) & (lum < 0.4)))

    return {
        "avg_brightness": avg, "contrast": contrast, "dark_ratio": dark_ratio,
        "white_ratio": white_ratio, "dark_red_ratio": dark_red_ratio,
        "dark_blue_ratio": dark_blue_ratio, "should_invert": avg < 0.4 and dark_ratio > 0.5,
        "is_totally_dark": avg < 0.05,
    }

def preprocess(img: Image.Image) -> Image.Image:
    """Adaptive preprocessing before Tesseract OCR."""
    if not _PIL_OK or img is None:
        return img
    analysis = analyze_image(img)
    if analysis["is_totally_dark"]: return img.convert("L")
    processed = img.copy()
    if analysis["should_invert"]: processed = ImageOps.invert(processed.convert("RGB"))
    processed = processed.convert("L")
    if analysis["contrast"] < 0.4: processed = ImageEnhance.Contrast(processed).enhance(1.5)
    if analysis["avg_brightness"] < 0.4:
        processed = ImageEnhance.Brightness(processed).enhance(1.3)
    elif analysis["avg_brightness"] > 0.7:
        processed = ImageEnhance.Brightness(processed).enhance(0.9)
    if analysis["contrast"] > 0.6:
        processed = processed.filter(ImageFilter.GaussianBlur(radius=0.3))
    if analysis["contrast"] > 0.7 and analysis["avg_brightness"] > 0.6 and _NP_OK:
        arr = np.array(processed)
        arr = ((arr > 127) * 255).astype(np.uint8)
        processed = Image.fromarray(arr)
    return processed

def run(img: Image.Image, lang: str = "eng", single_line: bool = False, layout: str = "tabular") -> str:
    """
    Run Tesseract on a PIL image with adaptive preprocessing.
    Supported layouts: tabular, block, single_line, sparse.
    """
    if not TESSERACT_AVAILABLE or img is None or not _PYTESSERACT_OK:
        return ""
    try:
        processed = preprocess(img)
        if layout == "single_line" or single_line: psm = 7
        elif layout == "tabular": psm = 4
        elif layout == "sparse": psm = 11
        else: psm = 6
        return pytesseract.image_to_string(processed, lang=lang, config=f"--oem 3 --psm {psm}")
    except Exception as e:
        logger.warning(f"iscs_OCR.run failed: {e}")
        return ""

def run_digits(img: Image.Image, psm: int = 10) -> str:
    """
    OCR restricted to digits — for small, ISOLATED numeric cells (e.g. the SCADA
    severity column '0'/'1'). In the full-banner OCR a lone digit flanked by cell
    dividers is often misread ('0' -> '[}') or dropped; cropping just that cell
    and whitelisting digits reads it reliably.

    psm 10 = single character (best for a lone digit); psm 7 for a digit line.
    """
    if not TESSERACT_AVAILABLE or img is None or not _PYTESSERACT_OK:
        return ""
    try:
        proc = img.convert("L")
        w, h = proc.size
        if w and h:
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            proc = proc.resize((w * 3, h * 3), resample)   # upscale small glyph
        cfg = f"--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789"
        return pytesseract.image_to_string(proc, config=cfg)
    except Exception as e:
        logger.warning(f"iscs_OCR.run_digits failed: {e}")
        return ""