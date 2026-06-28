"""
adapters/driving/ui_tkinter/dispatcher.py  (M5.1 — TkEventDispatcher)

The Tkinter R-HEX-2 adapter: marshals a worker-thread callable onto the Tk main
loop via ``root.after(0, …)``. The core (``WilloWispCoreAPI.emit`` / event
subscribers, the run threads) hands work here without knowing the UI is Tkinter —
exactly mirroring the CLI's ``SyncEventDispatcher``.

Note: this module imports no tkinter — ``root`` is any object exposing ``.after``,
so the dispatcher is unit-testable headlessly.
"""
from __future__ import annotations

from typing import Any, Callable

from core.ports.event_dispatcher import EventDispatcher


class TkEventDispatcher(EventDispatcher):
    """Schedules ``fn(*args, **kwargs)`` onto the Tk loop owned by ``root``."""

    def __init__(self, root: Any) -> None:
        self._root = root          # a Tk widget/root exposing .after(ms, callable)

    def dispatch(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        def _run():
            fn(*args, **kwargs)
        try:
            self._root.after(0, _run)
        except Exception:
            # The loop is gone (e.g. during shutdown) — best-effort inline fallback
            # so a late event never raises out of a worker thread.
            _run()
