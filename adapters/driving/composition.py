"""
adapters/driving/composition.py  (M4/M5 — shared driving composition root)

Assembles the core behind the WilloWispCoreAPI facade: a capability registry with the
discovered plugins, the config provider, the event bus, report templates and (optional)
assets, plus the SuiteRunService as the facade's run_service. The caller injects the
front-end's EventDispatcher (CLI → SyncEventDispatcher, Tk → TkEventDispatcher) and may
inject driven ports (input/protocol/assets); the real local adapters are lazy defaults,
so a fully-faked headless build pulls no pyautogui/pymodbus/tkinter.

Both front-ends use this: the CLI (`adapters/driving/cli`) and the Tk app
(`adapters/driving/ui_tkinter`). No GUI toolkit is imported here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from iscs_core import CapabilityRegistry, EventBus, discover_directory
from core.api import WilloWispCoreAPI
from core.services.config import ConfigProvider, set_base_dir
from core.services.import_service import auto_register_procedures
from core.services.run_coordinator import SuiteRunService
from core.ports.event_dispatcher import EventDispatcher, SyncEventDispatcher
import iscs_report_templates as _templates

# repo root: …/adapters/driving/composition.py → up 2
_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_CATEGORIES = ("actions", "verifications", "utilities")


def build_core_api(
    *,
    config_path: Optional[Path] = None,
    base_dir: Optional[Path] = None,
    protocols: Any = None,
    input_control: Any = None,
    assets: Any = None,
    monitors: Optional[list] = None,
    event_dispatcher: Optional[EventDispatcher] = None,
    on_log=None,
    on_progress=None,
) -> WilloWispCoreAPI:
    """Assemble the WilloWispCoreAPI for any front-end.

    Inject `event_dispatcher` (defaults to a synchronous one) and, to stay fully fake
    (no hardware / no OS-automation import), `protocols` / `input_control` / `assets`.
    """
    base = Path(base_dir) if base_dir else _ROOT
    set_base_dir(base)

    registry = CapabilityRegistry()
    for cat in _PLUGIN_CATEGORIES:
        discover_directory(_ROOT / "plugins" / cat, into=registry)

    config = ConfigProvider(config_path or (base / "config.json"))
    bus = EventBus()

    if input_control is None:
        from adapters.driven.input.pyautogui_input import PyAutoGuiInput
        input_control = PyAutoGuiInput()
    if protocols is None:
        from adapters.driven.protocol.manager import ProtocolManager
        protocols = ProtocolManager(config.config)
    if assets is None:
        try:
            from adapters.driven.persistence.asset_store import AssetManager
            assets = AssetManager.instance()
        except Exception:
            assets = None

    run_service = SuiteRunService(
        config=config.config, protocols=protocols, monitors=monitors or [],
        input_control=input_control, event_bus=bus,
        on_log=on_log, on_progress=on_progress,
    )

    api = WilloWispCoreAPI(
        registry=registry, config_provider=config, event_bus=bus, assets=assets,
        templates=_templates, default_flow_builder=auto_register_procedures,
        run_service=run_service,
    )
    api.set_event_dispatcher(event_dispatcher or SyncEventDispatcher())
    return api
