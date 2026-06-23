"""
Tests for P3.1 — input / navigation action capabilities + the screenshot utility.
A fake pyautogui is injected so nothing actually moves the mouse.
"""
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from iscs_core import CapabilityRegistry, discover_directory, StepStatus

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = ROOT / "plugins" / "actions"
UTILITIES = ROOT / "plugins" / "utilities"


class FakePyAutoGui:
    def __init__(self):
        self.calls = []
    def click(self, x, y): self.calls.append(("click", x, y))
    def rightClick(self, x, y): self.calls.append(("rightClick", x, y))
    def hotkey(self, *keys): self.calls.append(("hotkey", keys))
    def typewrite(self, text, interval=0): self.calls.append(("typewrite", text))


@pytest.fixture
def pg(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


@pytest.fixture
def reg():
    r = CapabilityRegistry()
    discover_directory(ACTIONS, into=r)
    discover_directory(UTILITIES, into=r)
    return r


def _ctx(params=None, extra=None, config=None, sc_dir=None):
    ec = SimpleNamespace(extra=extra or {}, sc_dir=sc_dir, point_idx=0)
    runner = SimpleNamespace(_sleep=lambda s: None, config=config or {})
    return SimpleNamespace(proc=SimpleNamespace(params=params or {}), exec=ec,
                           runner=runner, log=lambda m: None)


# ── discovery / supersession ──────────────────────────────────────────────────

def test_all_actions_register(reg):
    for key in ("click", "right_click", "hotkey", "type_text", "navigate_home",
                "navigate_alarm_list", "navigate_event_list",
                "navigate_equipment_page", "screenshot"):
        assert reg.has(key), key


def test_actions_supersede_legacy():
    import iscs_workflow as wf
    r = CapabilityRegistry()
    wf.register_legacy_capabilities(into=r)
    discover_directory(ACTIONS, into=r)
    assert type(r.get("click")).__name__ == "ClickAction"
    assert type(r.get("navigate_equipment_page")).__name__ == "NavigateEquipmentPageAction"


# ── input ─────────────────────────────────────────────────────────────────────

def test_click_clicks_coords(reg, pg):
    out = reg.get("click").execute(_ctx({"x": 100, "y": 200, "wait_after": 0}))
    assert out.status is StepStatus.PASS
    assert ("click", 100, 200) in pg.calls


def test_click_skips_without_coords(reg, pg):
    assert reg.get("click").execute(_ctx({})).status is StepStatus.SKIP


def test_hotkey_parses_combo(reg, pg):
    reg.get("hotkey").execute(_ctx({"keys": "Ctrl+S", "wait_after": 0}))
    assert ("hotkey", ("ctrl", "s")) in pg.calls


def test_type_text_types(reg, pg):
    reg.get("type_text").execute(_ctx({"text": "hello", "wait_after": 0}))
    assert ("typewrite", "hello") in pg.calls


def test_type_text_does_not_click_by_default(reg, pg):
    # x/y provided but click_first OFF (default) → just types, no click.
    reg.get("type_text").execute(_ctx({"text": "hi", "x": 5, "y": 6, "wait_after": 0}))
    assert not any(c[0] == "click" for c in pg.calls)
    assert ("typewrite", "hi") in pg.calls


def test_type_text_clicks_first_when_enabled(reg, pg):
    reg.get("type_text").execute(
        _ctx({"click_first": True, "text": "hi", "x": 5, "y": 6, "wait_after": 0}))
    assert ("click", 5, 6) in pg.calls
    assert ("typewrite", "hi") in pg.calls


# ── navigate ──────────────────────────────────────────────────────────────────

def test_navigate_alarm_list_clicks_home_then_target(reg, pg):
    out = reg.get("navigate_alarm_list").execute(
        _ctx({"home_x": 5, "home_y": 6, "al_x": 50, "al_y": 60}, config={"nav_wait_sec": 0}))
    assert out.status is StepStatus.PASS
    assert ("click", 5, 6) in pg.calls and ("click", 50, 60) in pg.calls


def test_navigate_skips_without_target(reg, pg):
    assert reg.get("navigate_event_list").execute(_ctx({})).status is StepStatus.SKIP


def test_navigate_equipment_right_clicks(reg, pg):
    reg.get("navigate_equipment_page").execute(
        _ctx({"rc_x": 10, "rc_y": 20, "pg_x": 30, "pg_y": 40}, config={"nav_wait_sec": 0, "click_delay": 0}))
    assert ("rightClick", 10, 20) in pg.calls and ("click", 30, 40) in pg.calls


def test_navigate_home_uses_extra_fallback(reg, pg):
    reg.get("navigate_home").execute(_ctx({}, extra={"home_x": 9, "home_y": 9},
                                          config={"nav_wait_sec": 0}))
    assert ("click", 9, 9) in pg.calls


# ── screenshot ────────────────────────────────────────────────────────────────

def test_screenshot_saves_file(reg, monkeypatch, tmp_path):
    import PIL.ImageGrab as IG
    saved = {}
    class FakeImg:
        def save(self, p): saved["path"] = p
    monkeypatch.setattr(IG, "grab", lambda **k: FakeImg())
    out = reg.get("screenshot").execute(_ctx({}, sc_dir=tmp_path))
    assert out.status is StepStatus.PASS
    assert "manual_ss" in saved["path"]
