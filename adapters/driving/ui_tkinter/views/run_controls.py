"""
adapters/driving/ui_tkinter/views/run_controls.py

This file's responsibility is: own the Run / Pause / Stop button cluster (full +
compact rows) and reflect the run state on it.

A driving adapter: it builds the buttons into App-provided toolbar frames, forwards
clicks to injected intent callbacks (on_run / on_pause / on_stop), and exposes
set_run_state(...) so the run state drives the buttons — callers never poke the
widgets. Colours/styles live here. (The App keeps the responsive full/compact swap
and the non-run toolbar buttons.)
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Optional

_RUN = "#00C853"     # INCLUDE_COLOR — run / resume
_PAUSE = "#FFD600"   # PAUSE_COLOR
_STOP = "#FF1744"    # EXCLUDE_COLOR


class RunControls:
    def __init__(self, full_frame: Any, compact_frame: Any, *,
                 on_run: Callable, on_pause: Callable, on_stop: Callable,
                 tooltip: Optional[Callable[[Any, str], Any]] = None) -> None:
        sf = dict(font=("Consolas", 10, "bold"), relief="flat", padx=11, pady=7, cursor="hand2")
        ic = dict(font=("Consolas", 13, "bold"), relief="flat", padx=9, pady=5, cursor="hand2", width=2)

        self.btn_run = tk.Button(full_frame, text="▶ Run  [Ctrl+5]", bg=_RUN, fg="#000",
                                 command=on_run, **sf, state="disabled"); self.btn_run.pack(side="left", padx=3)
        self.btn_pause = tk.Button(full_frame, text="⏸ Pause  [Space]", bg=_PAUSE, fg="#000",
                                   command=on_pause, **sf, state="disabled"); self.btn_pause.pack(side="left", padx=3)
        self.btn_stop = tk.Button(full_frame, text="■ Stop  [Esc]", bg=_STOP, fg="#fff",
                                  command=on_stop, **sf, state="disabled"); self.btn_stop.pack(side="left", padx=3)

        self.btn_run_c = tk.Button(compact_frame, text="▶", bg=_RUN, fg="#000",
                                   command=on_run, **ic, state="disabled"); self.btn_run_c.pack(side="left", padx=2)
        self.btn_pause_c = tk.Button(compact_frame, text="⏸", bg=_PAUSE, fg="#000",
                                     command=on_pause, **ic, state="disabled"); self.btn_pause_c.pack(side="left", padx=2)
        self.btn_stop_c = tk.Button(compact_frame, text="■", bg=_STOP, fg="#fff",
                                    command=on_stop, **ic, state="disabled"); self.btn_stop_c.pack(side="left", padx=2)
        if tooltip:
            tooltip(self.btn_run_c, "▶ Run Test  [Ctrl+5]")
            tooltip(self.btn_pause_c, "⏸ Pause / Resume  [Space]")
            tooltip(self.btn_stop_c, "■ Stop Test  [Esc / Ctrl+F12]")

    def set_run_enabled(self, can_run: bool) -> None:
        """Enable/disable just the Run buttons (idle-state refresh)."""
        s = "normal" if can_run else "disabled"
        self.btn_run.config(state=s); self.btn_run_c.config(state=s)

    def set_run_state(self, state: str, *, can_run: bool = True) -> None:
        if state == "idle":
            self.set_run_enabled(can_run)
            self.btn_pause.config(state="disabled", text="⏸ Pause  [Space]", bg=_PAUSE, fg="#000")
            self.btn_pause_c.config(state="disabled", text="⏸", bg=_PAUSE, fg="#000")
            self.btn_stop.config(state="disabled"); self.btn_stop_c.config(state="disabled")
        elif state == "running":
            self.btn_run.config(state="disabled"); self.btn_run_c.config(state="disabled")
            self.btn_pause.config(state="normal", text="⏸ Pause  [Space]", bg=_PAUSE, fg="#000")
            self.btn_pause_c.config(state="normal", text="⏸", bg=_PAUSE, fg="#000")
            self.btn_stop.config(state="normal"); self.btn_stop_c.config(state="normal")
        elif state == "paused":
            self.btn_pause.config(text="▶ Resume  [Space]", bg=_RUN, fg="#000")
            self.btn_pause_c.config(text="▶", bg=_RUN, fg="#000")
        elif state == "stopping":
            self.btn_pause.config(state="disabled"); self.btn_pause_c.config(state="disabled")
            self.btn_stop.config(state="disabled"); self.btn_stop_c.config(state="disabled")
