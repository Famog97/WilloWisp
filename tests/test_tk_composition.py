"""
M5 — the Tk composition root builds the facade with a TkEventDispatcher.

Uses a fake root (anything with .after) and fake driven ports, so it runs with no
display and no hardware.
"""
import pytest

from adapters.driving.ui_tkinter.composition import build_tk_core_api
from adapters.driving.ui_tkinter.dispatcher import TkEventDispatcher
from core.ports.input_control import InputControlPort


class _FakeRoot:
    def after(self, ms, fn):
        fn()


class _FakeInput(InputControlPort):
    def click(self, x, y): pass
    def position(self): return (0, 0)
    def right_click(self, x, y): pass
    def hotkey(self, *k): pass
    def type_text(self, t, interval=0.0): pass


class _FakeProtocols:
    def get_protocol(self, n): return None
    def stop_all(self): pass


@pytest.fixture
def api(tmp_path):
    return build_tk_core_api(
        _FakeRoot(), config_path=tmp_path / "c.json", base_dir=tmp_path,
        protocols=_FakeProtocols(), input_control=_FakeInput(), assets=None)


def test_tk_facade_uses_tk_dispatcher(api):
    assert isinstance(api._dispatcher, TkEventDispatcher)


def test_tk_facade_catalogue_and_emit(api):
    assert {"trigger_alarm", "delay"} <= {t["key"] for t in api.list_step_types()}
    seen = []
    api.emit(lambda v: seen.append(v), 42)     # marshals through the (fake) Tk loop
    assert seen == [42]
