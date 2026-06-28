"""
adapters/driving/cli/composition.py  (M4.1 — CLI composition root)

The CLI front-end uses the shared driving composition (which defaults to a
SyncEventDispatcher — exactly what a console/headless run wants). Re-exported here so
`adapters.driving.cli.composition.build_core_api` stays a stable entry point.
"""
from __future__ import annotations

from adapters.driving.composition import build_core_api

__all__ = ["build_core_api"]
