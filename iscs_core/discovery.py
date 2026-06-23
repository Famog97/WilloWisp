"""
Plugin discovery (FR-3, FR-4, NFR-12).

Three ways to surface capabilities, all funnelling into the same registry via the
``@register`` decorator that fires at import time:

  - directory   — drop a ``.py`` file in ``plugins/<category>/`` (no packaging)
  - package     — import every submodule of an installed/importable package
  - entry points — capabilities contributed by installed distributions

Discovery only *imports* modules; the modules register themselves. Pass ``into=``
to load into a specific registry (otherwise the global one) — implemented via the
ambient ``using_registry`` context so plugin modules need no registry reference.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from contextlib import nullcontext
from pathlib import Path
from typing import List, Optional, Union

from .registry import CapabilityRegistry, using_registry

logger = logging.getLogger(__name__)


def _ctx(into: Optional[CapabilityRegistry]):
    return using_registry(into) if into is not None else nullcontext()


def discover_directory(path: Union[str, Path],
                       into: Optional[CapabilityRegistry] = None) -> List[str]:
    """Import every top-level ``*.py`` file in ``path`` (files starting with ``_``
    are skipped). Returns the stems of the modules that imported successfully.
    A module that raises on import is logged and skipped (NFR-11)."""
    path = Path(path)
    loaded: List[str] = []
    if not path.is_dir():
        return loaded
    with _ctx(into):
        for py in sorted(path.glob("*.py")):
            if py.name.startswith("_"):
                continue
            mod_name = f"_wisp_plugin_{py.stem}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, py)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)   # type: ignore[union-attr]
                loaded.append(py.stem)
            except Exception:
                logger.exception("Failed to load plugin file %s", py)
    return loaded


def discover_package(package: Union[str, "object"],
                     into: Optional[CapabilityRegistry] = None) -> List[str]:
    """Import every submodule of ``package`` (a dotted name or module object) so
    its ``@register`` decorators fire. Returns the loaded submodule names."""
    if isinstance(package, str):
        package = importlib.import_module(package)
    loaded: List[str] = []
    pkg_path = getattr(package, "__path__", None)
    if pkg_path is None:
        return loaded
    with _ctx(into):
        for info in pkgutil.iter_modules(pkg_path):
            full = f"{package.__name__}.{info.name}"
            try:
                importlib.import_module(full)
                loaded.append(full)
            except Exception:
                logger.exception("Failed to import plugin module %s", full)
    return loaded


def discover_entry_points(group: str = "willowisp.capabilities",
                          into: Optional[CapabilityRegistry] = None) -> List[str]:
    """Load capabilities contributed by installed distributions under ``group``.
    Each entry point is loaded (its module imported); returns the entry-point
    names. Safe to call when nothing is installed (returns [])."""
    try:
        from importlib.metadata import entry_points
    except Exception:   # pragma: no cover - importlib.metadata always present on 3.10+
        return []

    try:
        eps = entry_points(group=group)
    except TypeError:   # pragma: no cover - very old API
        eps = entry_points().get(group, [])

    loaded: List[str] = []
    with _ctx(into):
        for ep in eps:
            try:
                ep.load()
                loaded.append(ep.name)
            except Exception:
                logger.exception("Failed to load entry point %s", getattr(ep, "name", ep))
    return loaded
