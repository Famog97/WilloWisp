"""
Config & severity — core service (M2.2).

Relocates the configuration defaults, the severity↔colour matrix, and the
config.json load/save out of ``baru`` into the hexagon interior. ``ConfigProvider``
holds the live config dict (same instance ``baru.APP_CONFIG`` re-exports, so all
existing mutations/reads are unchanged). ``SeverityColorClassifier`` is the single
owner of the colour matrix (consumed by the verification split in M2.4).

No UI/OS imports — pure stdlib.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

# ── Severity matrix (state → display text + RGB colour). Tuples, never JSON. ──
SEVERITY_MATRIX = {
    "1": {"text": "1", "color": (255, 0,   0),   "name": "RED"},     # RED    — Supercritical
    "2": {"text": "2", "color": (255, 126, 0), "name": "ORANGE"},  # ORANGE — Critical
    "3": {"text": "3", "color": (255, 255, 0), "name": "YELLOW"},  # YELLOW — Less Critical
    "0": {"text": "0", "color": (32,  169, 72),  "name": "GREEN"},   # GREEN  — Normal
}

# ── Default application config (overlaid by config.json at load). ──
DEFAULT_CONFIG: Dict[str, Any] = {
    "modbus_port": 502,
    "tesseract_cmd": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "tesseract_lang": "eng",
    "severity_matrix": SEVERITY_MATRIX,
    "grid_spacing": 40,
    "click_delay": 1.5,
    "mouse_drift_px": 15,
    "nav_wait_sec": 1.0,
    "detection_duration_sec": 8.0,
    "sampler_interval_ms":  100,
}


class ConfigProvider:
    """Owns the live config dict: defaults overlaid by config.json, with save.
    The severity matrix is never round-tripped through JSON (tuples↔lists)."""

    def __init__(self, config_path) -> None:
        self._path = Path(config_path)
        self._cfg: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> Dict[str, Any]:
        if self._path.exists():
            try:
                with open(self._path, "r") as f:
                    loaded = json.load(f)
                loaded.pop("severity_matrix", None)  # never load from JSON
                self._cfg.update(loaded)
            except Exception as e:
                print(f"Failed to load config.json: {e}")
        return self._cfg

    def save(self) -> None:
        try:
            to_save = {k: v for k, v in self._cfg.items() if k != "severity_matrix"}
            with open(self._path, "w") as f:
                json.dump(to_save, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    @property
    def config(self) -> Dict[str, Any]:
        return self._cfg


class SeverityColorClassifier:
    """Single owner of the severity↔colour mapping."""

    def __init__(self, matrix: Optional[dict] = None) -> None:
        self._m = matrix if matrix is not None else SEVERITY_MATRIX

    def name(self, rgb) -> str:
        for entry in self._m.values():
            if entry.get("color") == rgb:
                return entry.get("name", "")
        return ""

    def color(self, severity):
        entry = self._m.get(str(severity))
        return entry["color"] if entry else None

    def entry(self, severity) -> Optional[dict]:
        return self._m.get(str(severity))
