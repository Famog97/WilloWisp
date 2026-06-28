"""
adapters/driving/ui_tkinter/hotkey_adapter.py

This file's responsibility is: bind global OS hotkeys to run / stop / pause intents,
marshalling each onto the UI loop.

Driving adapter — the only UI place that touches the `keyboard` library. Intents are
injected callbacks; the EventDispatcher (R-HEX-2) marshals them onto the Tk loop.
Best-effort: a missing or blocked keyboard library is a silent no-op, never a crash.
"""
from __future__ import annotations

import time
from typing import Any, Callable

_HOTKEYS = ("ctrl+5", "ctrl+f12", "escape", "space")


class HotkeyAdapter:
    def __init__(self, dispatcher: Any, *, on_run: Callable, on_stop: Callable,
                 on_pause: Callable, run_debounce_sec: float = 0.5) -> None:
        self._dispatcher = dispatcher
        self._on_run = on_run
        self._on_stop = on_stop
        self._on_pause = on_pause
        self._debounce = run_debounce_sec
        self._last_run = 0.0

    def register(self) -> None:
        try:
            import keyboard
        except Exception:
            return
        try:
            keyboard.add_hotkey("ctrl+5", self._hk_run, suppress=False)
            keyboard.add_hotkey("ctrl+f12", self._hk_stop, suppress=True)
            keyboard.add_hotkey("escape", self._hk_stop, suppress=False)
            keyboard.add_hotkey("space", self._hk_space, suppress=False)
        except Exception:
            pass

    def unregister(self) -> None:
        try:
            import keyboard
            for hk in _HOTKEYS:
                keyboard.remove_hotkey(hk)
        except Exception:
            pass

    # ── hotkey handlers (fire on the keyboard lib's thread → marshal to the UI) ──
    def _hk_run(self) -> None:
        now = time.time()
        if now - self._last_run < self._debounce:
            return
        self._last_run = now
        self._dispatcher.dispatch(self._on_run)

    def _hk_stop(self) -> None:
        self._dispatcher.dispatch(self._on_stop)

    def _hk_space(self) -> None:
        self._dispatcher.dispatch(self._on_pause)
