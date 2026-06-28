"""
adapters/driving/ui_tkinter/views/log_sink.py

This file's responsibility is: render timestamped log lines into a read-only,
auto-scrolling Tk text panel.

It imports no business logic — only Tkinter and the EventDispatcher port. Worker
threads call `write()`; the dispatcher marshals the actual widget update onto the Tk
loop (R-HEX-2), so callers never touch the widget off-thread.
"""
from __future__ import annotations

import datetime
import tkinter as tk
from typing import Any, Optional

from core.ports.event_dispatcher import EventDispatcher


class LogSink:
    def __init__(self, parent: Any, dispatcher: Optional[EventDispatcher] = None,
                 *, height: int = 5) -> None:
        self._dispatcher = dispatcher
        self.frame = tk.Frame(parent, bg="#0f0f0f")
        self._text = tk.Text(self.frame, height=height, bg="#080808", fg="#aaaaaa",
                             font=("Consolas", 9), relief="flat", state="disabled")
        scroll = tk.Scrollbar(self.frame, command=self._text.yview)
        self._text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._text.pack(fill="x")

    def pack(self, **kwargs) -> "LogSink":
        self.frame.pack(**kwargs)
        return self

    def write(self, msg: str) -> None:
        """Append one log line (thread-safe via the dispatcher)."""
        if self._dispatcher is not None:
            self._dispatcher.dispatch(self._append, msg)
        else:
            self._append(msg)

    def _append(self, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._text.configure(state="normal")
        self._text.insert("end", f"[{ts}] {msg}\n")
        self._text.see("end")
        self._text.configure(state="disabled")
