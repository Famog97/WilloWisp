"""
adapters/driving/ui_tkinter/views/settings_view.py

This file's responsibility is: present the Settings dialog and read/write app config
through the Core API.

A thin driving adapter: it imports only tkinter and talks to WilloWispCoreAPI
(get_config / update_config) — never APP_CONFIG, globals, the engine, or the verifier.
Side effects beyond config (re-init OCR, refresh the canvas, legacy globals) are the
App's job, delivered via the on_applied(config) callback.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable, Dict, Optional

_BG = "#0f0f0f"
_CARD = "#161616"

# (config key, label, description, entry width) — grouped into collapsible sections.
_SECTIONS = [
    ("⚙  General & Protocol", True, [
        ("click_delay", "Click Delay (sec):", "Wait time before taking screenshot.", 6),
        ("modbus_port", "Modbus Port:", "TCP Port for the ISCS Server (requires restart).", 6),
    ]),
    ("🧪  Suite Runner & Verification", True, [
        ("nav_wait_sec", "Nav Wait (sec):", "Wait time between navigation clicks (Suite Runner).", 6),
        ("detection_duration_sec", "Detection Duration (s):", "Observation window for concurrent text polling and blink detection.", 6),
        ("datetime_sync_limit_sec", "Datetime Sync Limit (s):", "Max allowed gap between SCADA on-screen time and trigger time before datetime FAILs.", 6),
        ("sampler_interval_ms", "Sampler Interval (ms):", "Milliseconds between each frame grab — lower = more frames.", 6),
    ]),
    ("🔤  OCR / Tesseract", True, [
        ("tesseract_cmd", "Tesseract Path:", "Path to tesseract.exe for OCR verification.", 30),
        ("tesseract_lang", "Tesseract Model:", "Model name (e.g. 'eng' or 'custom_model').", 15),
    ]),
    ("🖱  RPA / Fuzzer (advanced)", False, [
        ("grid_spacing", "Grid Spacing (px):", "Distance between grid points. (Fuzzer/RPA ONLY)", 6),
        ("mouse_drift_px", "Mouse Drift (px):", "Safety radius. Pauses if bumped.", 6),
    ]),
]

# config keys parsed as numbers on apply (everything else stays a string)
_INT_KEYS = {"grid_spacing", "mouse_drift_px", "modbus_port", "sampler_interval_ms"}
_FLOAT_KEYS = {"click_delay", "nav_wait_sec", "detection_duration_sec", "datetime_sync_limit_sec"}


class SettingsView:
    def __init__(self, parent: Any, api: Any, *,
                 on_applied: Optional[Callable[[dict], None]] = None,
                 shake: Optional[Callable[[Any], None]] = None) -> None:
        self._parent = parent
        self._api = api
        self._on_applied = on_applied or (lambda cfg: None)
        self._shake = shake
        self._win: Optional[tk.Toplevel] = None
        self._vars: Dict[str, tk.StringVar] = {}

    def show(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            if self._shake:
                self._shake(self._win)
            else:
                self._win.lift(); self._win.focus_force()
            return
        self._build(self._api.get_config())

    # ── building ─────────────────────────────────────────────────────────────
    def _build(self, cfg: dict) -> None:
        dlg = tk.Toplevel(self._parent)
        self._win = dlg
        dlg.protocol("WM_DELETE_WINDOW", self._close)
        dlg.title("⚙ Settings & Configuration")
        w, h = 640, 690
        x = self._parent.winfo_x() + (self._parent.winfo_width() // 2) - (w // 2)
        y = self._parent.winfo_y() + (self._parent.winfo_height() // 2) - (h // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.configure(bg=_BG); dlg.resizable(False, False)
        dlg.attributes("-topmost", True)

        btn_frame = tk.Frame(dlg, bg=_BG)
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=(6, 14))

        content = tk.Frame(dlg, bg=_BG); content.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(content, bg=_BG, highlightthickness=0)
        vsb = tk.Scrollbar(content, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(20, 4), pady=(16, 6))
        body = tk.Frame(canvas, bg=_BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        dlg.bind("<Destroy>", lambda e: (canvas.unbind_all("<MouseWheel>") if e.widget is dlg else None))

        self._vars = {key: tk.StringVar(value=str(cfg.get(key, "")))
                      for _, _, fields in _SECTIONS for key, *_ in fields}
        for title, expanded, fields in _SECTIONS:
            self._add_section(body, title, fields, expanded)

        tk.Button(btn_frame, text="✓ Apply & Save", bg="#2979FF", fg="#fff",
                  font=("Consolas", 10, "bold"), relief="flat", pady=6, anchor="center",
                  command=self._apply, cursor="hand2").pack(side="left", padx=5, expand=True, fill="x")
        tk.Button(btn_frame, text="Cancel", bg="#222", fg="#aaa", font=("Consolas", 10),
                  relief="flat", pady=6, anchor="center", command=self._close,
                  cursor="hand2").pack(side="left", padx=5, expand=True, fill="x")

    def _add_section(self, parent_frame, title, fields, expanded) -> None:
        ls = dict(bg=_BG, fg="#aaa", font=("Consolas", 10))
        es = dict(bg="#1a1a1a", fg="#fff", insertbackground="#fff",
                  font=("Consolas", 11), relief="flat", bd=6)
        st = {"open": expanded}
        head = tk.Frame(parent_frame, bg=_CARD, cursor="hand2"); head.pack(fill="x", pady=(8, 0))
        arrow = tk.Label(head, text=("▾" if expanded else "▸"), bg=_CARD, fg="#2979FF",
                         font=("Consolas", 11, "bold")); arrow.pack(side="left", padx=(8, 6), pady=6)
        ttl = tk.Label(head, text=title, bg=_CARD, fg="#ddd", font=("Consolas", 10, "bold"))
        ttl.pack(side="left", pady=6)
        sect = tk.Frame(parent_frame, bg=_BG)
        for r, (key, lbl, desc, width) in enumerate(fields):
            tk.Label(sect, text=lbl, **ls).grid(row=r * 2, column=0, sticky="w", pady=(8, 0))
            tk.Entry(sect, textvariable=self._vars[key], width=width, **es).grid(
                row=r * 2, column=1, padx=10, pady=(8, 0), sticky="w")
            tk.Label(sect, text=desc, bg=_BG, fg="#555", font=("Consolas", 8)).grid(
                row=r * 2 + 1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        if expanded:
            sect.pack(fill="x", padx=(6, 0), pady=(0, 4))

        def _toggle(_e=None):
            st["open"] = not st["open"]
            if st["open"]:
                sect.pack(fill="x", padx=(6, 0), pady=(0, 4)); arrow.config(text="▾")
            else:
                sect.pack_forget(); arrow.config(text="▸")
        for wdg in (head, arrow, ttl):
            wdg.bind("<Button-1>", _toggle)

    # ── apply / close ────────────────────────────────────────────────────────
    def _apply(self) -> None:
        try:
            patch = {}
            for key, var in self._vars.items():
                raw = var.get()
                patch[key] = int(raw) if key in _INT_KEYS else float(raw) if key in _FLOAT_KEYS else raw
        except ValueError:
            messagebox.showerror("Invalid Input", "Please check your numbers.", parent=self._win)
            return
        cfg = self._api.update_config(patch)     # writes live config + saves
        self._on_applied(cfg)
        self._close()

    def _close(self) -> None:
        if self._win is not None:
            self._win.destroy()
        self._win = None
