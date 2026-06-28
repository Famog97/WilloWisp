"""
core/services/workspace.py

This file's responsibility is: hold the live zone working set being authored — the
flat zone list plus the per-page zone map — and reset it.

Pure state: no tkinter, no engine. A UI binds its widgets to this session and the run
path reads zones from it, so any front-end (Tk today, a new UI tomorrow) shares one
workspace instead of the state being locked inside the GUI.
"""
from __future__ import annotations

from typing import Any, Dict, List


class WorkspaceSession:
    def __init__(self) -> None:
        self.zones: List[Any] = []                  # flat zones (sequence/grid + flat ISCS)
        self.zones_per_page: Dict[str, Any] = {}    # per-page zones for ISCS mode

    def clear(self) -> None:
        """Reset the live working set. A card's own saved zones are untouched."""
        self.zones.clear()
        self.zones_per_page.clear()

    def has_zones(self) -> bool:
        return bool(self.zones) or bool(self.zones_per_page)
