"""
M1 — core port interfaces + their local driven adapters.

Asserts the ports are abstract contracts, the SyncEventDispatcher reference impl
works, the BaseProtocol promotion (M1.4) is in effect, and each local adapter
delegates to its legacy backend (legacy monkeypatched — no real screen/OCR/input).
"""
import sys
from types import SimpleNamespace

import pytest

from core.ports import (
    EventDispatcher, SyncEventDispatcher,
    ScreenCapturePort, InputControlPort, OcrPort, ProtocolPort, BaseProtocol,
)


# ── EventDispatcher (M1.1) ──────────────────────────────────────────────────────

def test_event_dispatcher_is_abstract():
    with pytest.raises(TypeError):
        EventDispatcher()


def test_sync_dispatcher_runs_immediately():
    seen = []
    SyncEventDispatcher().dispatch(lambda a, b: seen.append((a, b)), 1, b=2)
    assert seen == [(1, 2)]


# ── abstract contracts (M1.2/M1.3/M1.5) ─────────────────────────────────────────

@pytest.mark.parametrize("port", [ScreenCapturePort, InputControlPort, OcrPort])
def test_ports_are_abstract(port):
    with pytest.raises(TypeError):
        port()


# ── ProtocolPort promotion (M1.4) ───────────────────────────────────────────────

def test_baseprotocol_is_the_promoted_port():
    import baru
    assert baru.BaseProtocol is ProtocolPort, "baru.BaseProtocol must be the core port"
    # concrete defaults preserved (ModbusProtocol relies on not overriding these)
    p = ProtocolPort(config={})
    assert p.check_health() is False
    assert p.start() is None and p.stop() is None
    with pytest.raises(NotImplementedError):
        p.trigger_alarm({})


def test_modbus_protocol_still_subclasses_the_port():
    import baru
    assert issubclass(baru.ModbusProtocol, ProtocolPort)


# ── local driven adapters delegate to legacy backends ───────────────────────────

def test_local_screen_capture_delegates_to_imagegrab(monkeypatch):
    calls = {}
    def _grab(**k):
        calls["kw"] = k
        return "IMG"
    fake_pil = SimpleNamespace(ImageGrab=SimpleNamespace(grab=_grab))
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    from adapters.driven.perception.local_grab import LocalScreenCapture
    out = LocalScreenCapture().grab(1, 2, 3, 4)
    assert out == "IMG" and calls["kw"]["bbox"] == (1, 2, 3, 4)


def test_tesseract_ocr_delegates(monkeypatch):
    import iscs_OCR
    monkeypatch.setattr(iscs_OCR, "run", lambda img, lang="eng", layout="block": f"R:{layout}")
    monkeypatch.setattr(iscs_OCR, "run_digits", lambda img, psm=10: f"D:{psm}")
    from adapters.driven.perception.tesseract_ocr import TesseractOcr
    ocr = TesseractOcr()
    assert ocr.read("img", layout="sparse") == "R:sparse"
    assert ocr.read_digits("img", psm=7) == "D:7"


def test_pyautogui_input_delegates(monkeypatch):
    rec = []
    fake = SimpleNamespace(
        click=lambda x, y: rec.append(("click", x, y)),
        rightClick=lambda x, y: rec.append(("right", x, y)),
        hotkey=lambda *k: rec.append(("hotkey", k)),
        typewrite=lambda t, interval=0: rec.append(("type", t)))
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    from adapters.driven.input.pyautogui_input import PyAutoGuiInput
    a = PyAutoGuiInput()
    a.click(5, 6); a.right_click(7, 8); a.hotkey("ctrl", "s"); a.type_text("hi")
    assert rec == [("click", 5, 6), ("right", 7, 8), ("hotkey", ("ctrl", "s")), ("type", "hi")]
