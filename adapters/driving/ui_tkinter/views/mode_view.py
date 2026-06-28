"""
adapters/driving/ui_tkinter/views/mode_view.py

This file's responsibility is: present the operating-mode selector — three buttons
(Targeted Sequence / Grid Scan / Suite Runner) — and highlight the active one.

Pure widget: imports only tkinter. Clicks forward to an injected on_select(mode)
callback; the App owns the run_mode state and the mode-change orchestration. Colours
live here.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Dict

_BG = "#1a1a1a"
_INACTIVE_BG = "#2a2a2a"
_INACTIVE_FG = "#666"
# active (bg, fg) per mode
_ACTIVE = {
    "sequence": ("#AA00FF", "#000"),   # TARGET_COLOR
    "grid": ("#00C853", "#000"),       # INCLUDE_COLOR
    "iscs": ("#FF00FF", "#fff"),       # ALARM_PANEL_COLOR
}


class ModeView:
    def __init__(self, parent: Any, on_select: Callable[[str], None]) -> None:
        # Builds into the caller's `parent` row frame (the App keeps that frame so it
        # can place its own Info button on the same bar).
        tk.Label(parent, text="OPERATING MODE:", bg=_BG, fg="#aaa",
                 font=("Consolas", 9, "bold")).pack(side="left", padx=10)
        bs = dict(font=("Consolas", 10, "bold"), relief="flat", padx=16, pady=6,
                  cursor="hand2", bd=0)
        self._btns: Dict[str, tk.Button] = {}
        for mode, label in (("sequence", "🎯 Targeted Sequence (RPA)"),
                            ("grid", "▦ Grid Scan (Fuzzer)"),
                            ("iscs", "🚨 Suite Runner")):
            btn = tk.Button(parent, text=label,
                            command=lambda m=mode: on_select(m), **bs)
            btn.pack(side="left", padx=4)
            self._btns[mode] = btn

    def set_active(self, mode: str) -> None:
        for key, btn in self._btns.items():
            if key == mode:
                bg, fg = _ACTIVE.get(mode, (_INACTIVE_BG, _INACTIVE_FG))
                btn.config(bg=bg, fg=fg)
            else:
                btn.config(bg=_INACTIVE_BG, fg=_INACTIVE_FG)
