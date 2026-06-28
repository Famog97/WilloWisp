"""
adapters/driving/ui_tkinter/components/screen_selector.py

This file's responsibility is: a horizontal monitor-picker strip — one button per
display — that calls back with the chosen Monitor.

Pure widget: imports only tkinter, holds no app/business logic. Colours live here.
"""
from __future__ import annotations

import tkinter as tk

SCREEN_COLORS = ["#2979FF", "#FF6F00", "#AA00FF", "#00BCD4", "#FF4081"]


class ScreenSelectorPanel(tk.Frame):
    def __init__(self, master, monitors, on_select):
        super().__init__(master, bg="#0f0f0f")
        self.monitors = monitors
        self.on_select = on_select
        self.selected = 0
        self._cards = []
        self._build()

    def _build(self):
        tk.Label(self, text="SELECT SCREEN", bg="#0f0f0f", fg="#aaaaaa",
                 font=("Consolas", 8)).pack(side="left", padx=(0, 10))
        for i, mon in enumerate(self.monitors):
            color = SCREEN_COLORS[i % len(SCREEN_COLORS)]
            card = tk.Button(self, text=f"◉ Display {mon.display_num}\n{mon.width}×{mon.height}",
                             bg="#1a1a1a", fg=color, font=("Consolas", 9, "bold"),
                             relief="flat", padx=10, pady=6, cursor="hand2", bd=0,
                             command=lambda idx=i: self._select(idx))
            card.pack(side="left", padx=4)
            self._cards.append(card)

    def _highlight(self, idx):
        self.selected = idx
        for i, card in enumerate(self._cards):
            color = SCREEN_COLORS[i % len(SCREEN_COLORS)]
            card.config(bg=color if i == idx else "#1a1a1a", fg="#000" if i == idx else color)

    def _select(self, idx):
        self._highlight(idx)
        self.on_select(self.monitors[idx])

    def lock(self):
        for c in self._cards:
            c.config(state="disabled")

    def unlock(self):
        for c in self._cards:
            c.config(state="normal")
