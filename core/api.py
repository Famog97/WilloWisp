"""
core/api.py — WilloWispCoreAPI, the single inbound gate (R-HEX-1).

Every UI (Tkinter, PyQt, Web, CLI) interacts with the core ONLY through this
facade — never by constructing engines, repositories, or services directly. The
facade owns *no* business logic; it holds injected core services and delegates.

Pure: no UI/OS-automation imports and no concrete adapter imports — all
collaborators are injected by a composition root (the per-UI startup), which keeps
the core swappable behind any front-end. Events flow outbound through the injected
`EventDispatcher` (set via `set_event_dispatcher`); the core never touches a UI loop.

Run control (`start_suite`/`stop`/…) delegates to an injected `run_service`; until a
composition root wires one, those methods raise a clear error (the rest of the API —
catalogue, config, assets, default-flow, reporting — works headlessly today).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


class WilloWispCoreAPI:
    def __init__(self, *, registry, config_provider, event_bus,
                 assets: Any = None, templates: Any = None,
                 default_flow_builder: Optional[Callable] = None,
                 run_service: Any = None) -> None:
        self._registry = registry                  # iscs_core CapabilityRegistry
        self._config = config_provider              # core.services.config.ConfigProvider
        self._bus = event_bus                       # iscs_core EventBus
        self._assets = assets                       # AssetManager / AssetLibrary
        self._templates = templates                 # iscs_report_templates module
        self._build_flow = default_flow_builder     # auto_register_procedures
        self._run = run_service                     # injected by the UI/CLI composition root
        self._dispatcher = None                     # EventDispatcher (UI-injected)

    # ── lifecycle / events ──────────────────────────────────────────────────
    def set_event_dispatcher(self, dispatcher) -> None:
        """The UI injects its EventDispatcher (R-HEX-2 thread marshalling)."""
        self._dispatcher = dispatcher

    def subscribe(self, event_type, handler) -> None:
        self._bus.subscribe(event_type, handler)

    def emit(self, fn: Callable, *args, **kwargs) -> None:
        """Deliver a callable to the UI loop via the injected dispatcher (if any)."""
        if self._dispatcher is not None:
            self._dispatcher.dispatch(fn, *args, **kwargs)
        else:
            fn(*args, **kwargs)

    # ── capability catalogue (drives schema-generated UI, R-EXT-1) ───────────
    def list_step_types(self) -> List[Dict[str, Any]]:
        out = []
        for cap in self._registry.list():
            m = cap.meta
            out.append({
                "key": cap.key,
                "name": getattr(m, "name", cap.key),
                "category": getattr(m, "category", ""),
                "params_schema": dict(getattr(m, "params_schema", {}) or {}),
                "addable": bool(getattr(m, "addable", False)),
            })
        return out

    def get_param_schema(self, step_key: str) -> Dict[str, Any]:
        cap = self._registry.get(step_key)
        return dict(getattr(cap.meta, "params_schema", {}) or {})

    def list_report_templates(self) -> List[Dict[str, str]]:
        return self._templates.list_templates() if self._templates else []

    # ── configuration ───────────────────────────────────────────────────────
    def get_config(self) -> Dict[str, Any]:
        return dict(self._config.config)

    def update_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        self._config.config.update(patch)
        self._config.save()
        return dict(self._config.config)

    # ── assets ──────────────────────────────────────────────────────────────
    def assets(self) -> Any:
        return self._assets

    # ── scenario authoring ──────────────────────────────────────────────────
    def build_default_flow(self, scenario, zones_dict: dict, nav: dict):
        if self._build_flow is None:
            raise RuntimeError("default_flow_builder not wired into WilloWispCoreAPI")
        return self._build_flow(scenario, zones_dict, nav)

    # ── reporting (offline, from persisted results) ─────────────────────────
    def generate_report(self, template_key: str, raw_results, output_dir,
                        title: str = "Test Run"):
        if self._templates is None:
            raise RuntimeError("report templates not wired into WilloWispCoreAPI")
        return self._templates.generate_template_report(
            template_key, raw_results, output_dir, title=title)

    # ── execution (delegates to an injected run service) ────────────────────
    def _require_run(self):
        if self._run is None:
            raise RuntimeError(
                "run service not wired — inject one via the composition root "
                "(SuiteRunner relocation, M3.4).")
        return self._run

    def start_suite(self, *args, **kwargs):
        return self._require_run().start(*args, **kwargs)

    def stop(self):
        return self._require_run().stop()

    def pause(self):
        return self._require_run().pause()

    def resume(self):
        return self._require_run().resume()

    def get_run_state(self):
        return self._require_run().get_state()
