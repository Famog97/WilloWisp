"""
M4.4 — B10: drop-in extensibility (zero edits to existing files).

Exercises the three public extension points end-to-end:
  - capability  → discover_directory(into=…) + @register, surfaced by the facade
  - protocol    → ProtocolManager.register_protocol  (R-EXT-2)
  - resolver    → register_binding_resolver           (R-EXT, binding resolvers)

Each new thing is defined here / in a temp dir; no shipped module is modified.
"""
from pathlib import Path
from types import SimpleNamespace

from iscs_core import (CapabilityRegistry, EventBus, discover_directory,
                       StepStatus)
from core.api import WilloWispCoreAPI
from core.services.config import ConfigProvider
from core.services.import_service import auto_register_procedures
import iscs_report_templates as templates

ROOT = Path(__file__).resolve().parent.parent


def _facade(reg, tmp):
    return WilloWispCoreAPI(
        registry=reg, config_provider=ConfigProvider(tmp / "c.json"),
        event_bus=EventBus(), templates=templates,
        default_flow_builder=auto_register_procedures)


def test_dropin_capability_surfaces_and_runs(tmp_path):
    pdir = tmp_path / "myplugins"
    pdir.mkdir()
    (pdir / "widget.py").write_text(
        "from iscs_core import register, CapabilityMeta, StepResult, StepStatus\n"
        "@register()\n"
        "class Widget:\n"
        "    key = 'dropin_widget'\n"
        "    meta = CapabilityMeta(name='Drop-In Widget', category='utility',\n"
        "                          params_schema={'gain': {'type': 'number', 'default': 2}},\n"
        "                          addable=True)\n"
        "    def execute(self, ctx):\n"
        "        return StepResult(StepStatus.PASS, message='widget ran')\n",
        encoding="utf-8")

    reg = CapabilityRegistry()
    discover_directory(pdir, into=reg)          # drop-in discovered
    api = _facade(reg, tmp_path)

    cat = {t["key"]: t for t in api.list_step_types()}
    assert "dropin_widget" in cat               # appears in the catalogue…
    assert cat["dropin_widget"]["params_schema"] == {"gain": {"type": "number", "default": 2}}
    assert cat["dropin_widget"]["addable"] is True
    # …and it actually executes through the registry the engine uses
    res = reg.get("dropin_widget").execute(SimpleNamespace())
    assert res.status is StepStatus.PASS


def test_dropin_protocol_registers_and_resolves():
    from adapters.driven.protocol.manager import ProtocolManager
    from core.ports.protocol import BaseProtocol

    class FakeProtocol(BaseProtocol):
        def __init__(self, config, log_callback=None):
            self.config = config
            self.triggered = []
        def start(self): pass
        def stop(self): pass
        def trigger_alarm(self, payload): self.triggered.append(payload)
        def reset_alarm(self, payload): pass
        def check_health(self): return True

    pm = ProtocolManager({})
    pm.register_protocol("FAKE", FakeProtocol)      # drop-in protocol
    handler = pm.get_protocol("FAKE")
    assert handler.check_health() is True
    handler.trigger_alarm({"point_id": "P1"})
    assert handler.triggered == [{"point_id": "P1"}]


def test_dropin_binding_resolver_registers():
    from adapters.driven.persistence import asset_store as store
    from adapters.driven.persistence.asset_store import (
        register_binding_resolver, get_binding_resolver)

    class MyResolver:
        kind = "dropin_kind"
        def resolve(self, img, resolved):
            return {"status": "PASS", "message": "resolved by drop-in"}

    register_binding_resolver(MyResolver(), override=True)   # drop-in resolver
    try:
        got = get_binding_resolver("dropin_kind")
        assert got.kind == "dropin_kind"
        assert got.resolve(None, None)["status"] == "PASS"
    finally:
        # keep the global resolver registry clean for other tests
        store._BINDING_RESOLVERS.pop("dropin_kind", None)
