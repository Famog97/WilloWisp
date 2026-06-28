"""
adapters/driving/ui_tkinter/views/run_progress_view.py

This file's responsibility is: render run progress as a bar plus a one-line status label.

Imports only tkinter + the EventDispatcher port. set_fraction / set_text / reset marshal
the widget update onto the Tk loop via the dispatcher (R-HEX-2), so run threads update
progress without ever touching widgets off-thread. Colours live here (localized change).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional

from core.ports.event_dispatcher import EventDispatcher

_BG = "#0f0f0f"
_ACCENT = "#00C853"          # green progress fill


class RunProgressView:
    def __init__(self, parent: Any, dispatcher: Optional[EventDispatcher] = None,
                 *, idle_text: str = "Ready.") -> None:
        self._dispatcher = dispatcher
        self._idle_text = idle_text
        self.frame = tk.Frame(parent, bg=_BG)
        self._var = tk.DoubleVar()
        style = ttk.Style(parent)
        style.theme_use("default")
        style.configure("G.Horizontal.TProgressbar", troughcolor="#1a1a1a",
                        background=_ACCENT, bordercolor=_BG)
        ttk.Progressbar(self.frame, variable=self._var, maximum=100,
                        style="G.Horizontal.TProgressbar").pack(fill="x")
        self._label = tk.Label(self.frame, text=idle_text, bg=_BG, fg="#aaaaaa",
                               font=("Consolas", 9), anchor="w")
        self._label.pack(fill="x")

    def pack(self, **kwargs) -> "RunProgressView":
        self.frame.pack(**kwargs)
        return self

    def set_fraction(self, pct: float) -> None:
        self._marshal(self._var.set, pct)

    def set_text(self, msg: str) -> None:
        self._marshal(self._set_text, msg)

    def reset(self) -> None:
        self.set_fraction(0)
        self.set_text(self._idle_text)

    # ── internals ────────────────────────────────────────────────────────────
    def _set_text(self, msg: str) -> None:
        self._label.config(text=msg)

    def _marshal(self, fn, *args) -> None:
        if self._dispatcher is not None:
            self._dispatcher.dispatch(fn, *args)
        else:
            fn(*args)
