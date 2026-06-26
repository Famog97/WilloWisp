"""
EventDispatcher port (R-HEX-2) — the thread-marshalling boundary.

The core runs on worker threads and must deliver work/events onto the UI's own
loop without naming a UI toolkit. A UI injects its own dispatcher:
  - Tkinter  → schedules via ``root.after(0, ...)``
  - PyQt     → emits a signal
  - Web      → pushes onto an asyncio queue / WebSocket
  - CLI/tests → runs synchronously (``SyncEventDispatcher`` below)

The contract is intentionally tiny: hand a callable + args to ``dispatch`` and the
adapter guarantees it runs on the correct loop. No core code knows which UI is in
use. Pure-Python, zero dependencies (lives in the hexagon interior).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class EventDispatcher(ABC):
    """Marshals a callable from a worker thread onto the UI's loop."""

    @abstractmethod
    def dispatch(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Schedule ``fn(*args, **kwargs)`` to run on the UI loop/thread."""
        raise NotImplementedError


class SyncEventDispatcher(EventDispatcher):
    """Reference implementation: runs the callable immediately on the caller's
    thread. Used by the CLI adapter and by tests (no UI loop to marshal onto).
    Optionally echoes a short line for console visibility."""

    def __init__(self, echo: bool = False) -> None:
        self._echo = echo

    def dispatch(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if self._echo:
            print(f"[event] {getattr(fn, '__name__', fn)}")
        fn(*args, **kwargs)
