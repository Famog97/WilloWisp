"""
adapters/driving/ui_tkinter/views/stats_view.py

This file's responsibility is: render the top stats strip — the zone / target /
click-point / spacing counts, the run-state label, and the active-screen label.

Imports only tkinter + the EventDispatcher port. `set(field, text, color=None)`
marshals the update onto the Tk loop (R-HEX-2). Field keys: zones, include_title,
include, exclude_title, exclude, points, spacing, state, monitor. Colours live here.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Dict, Optional

from core.ports.event_dispatcher import EventDispatcher

_BG = "#0f0f0f"
_CARD = "#161616"
_TARGET = "#AA00FF"      # TARGET_COLOR
_POINT = "#2979FF"       # POINT_COLOR
_SCREEN = "#2979FF"
_MUTED = "#444"


class StatsView:
    def __init__(self, parent: Any, dispatcher: Optional[EventDispatcher] = None,
                 *, monitor_text: str = "Display 1", spacing_text: str = "40px") -> None:
        self._dispatcher = dispatcher
        self.frame = tk.Frame(parent, bg=_BG)
        self._labels: Dict[str, tk.Label] = {}
        _, self._labels["zones"] = self._make("ZONES", "0")
        self._labels["include_title"], self._labels["include"] = self._make("TARGETS", "0", _TARGET)
        self._labels["exclude_title"], self._labels["exclude"] = self._make("-", "0", _MUTED)
        _, self._labels["points"] = self._make("CLICK PTS", "0", _POINT)
        _, self._labels["spacing"] = self._make("SPACING", spacing_text)
        _, self._labels["state"] = self._make("STATE", "IDLE", _MUTED)
        _, self._labels["monitor"] = self._make("SCREEN", monitor_text, _SCREEN)

    def _make(self, title: str, value: str, color: str = "#666"):
        f = tk.Frame(self.frame, bg=_CARD, padx=12, pady=8)
        f.pack(side="left", padx=(0, 6), pady=4)
        t = tk.Label(f, text=title, bg=_CARD, fg="#aaaaaa", font=("Consolas", 8))
        t.pack()
        v = tk.Label(f, text=value, bg=_CARD, fg=color, font=("Consolas", 13, "bold"))
        v.pack()
        return t, v

    def pack(self, **kwargs) -> "StatsView":
        self.frame.pack(**kwargs)
        return self

    def set(self, field: str, text: str, color: Optional[str] = None) -> None:
        self._marshal(self._apply, field, text, color)

    def _apply(self, field: str, text: str, color: Optional[str]) -> None:
        lbl = self._labels.get(field)
        if lbl is None:
            return
        lbl.config(text=text)
        if color is not None:
            lbl.config(fg=color)

    def _marshal(self, fn, *args) -> None:
        if self._dispatcher is not None:
            self._dispatcher.dispatch(fn, *args)
        else:
            fn(*args)
