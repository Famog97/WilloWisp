"""
adapters/driving/ui_tkinter/composition.py  (M5 — Tk composition root)

The Tkinter front-end's wiring: the same shared core assembly as the CLI, but with a
TkEventDispatcher so outbound work/events from worker threads marshal onto the Tk loop
(R-HEX-2). Returns a ready WilloWispCoreAPI the GUI talks to instead of reaching into
core internals.
"""
from __future__ import annotations

from typing import Any

from adapters.driving.composition import build_core_api
from adapters.driving.ui_tkinter.dispatcher import TkEventDispatcher


def build_tk_core_api(root: Any, **kwargs) -> "WilloWispCoreAPI":  # noqa: F821
    """Build the facade for the Tk app, marshalling onto `root`'s loop.

    `root` is the Tk application/root (anything with `.after`). Extra kwargs pass
    through to the shared builder (e.g. config_path, protocols, input_control).
    """
    return build_core_api(event_dispatcher=TkEventDispatcher(root), **kwargs)
