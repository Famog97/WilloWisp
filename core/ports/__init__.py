"""Core outbound ports (Hexagonal) — see RESTRUCTURE_DESIGN.md §1.0/§1.0b.

Pure interfaces the core depends on; concrete adapters live under
``adapters/driven/`` and are injected at startup. No UI/OS-automation imports here.
"""
from .event_dispatcher import EventDispatcher, SyncEventDispatcher
from .screen_capture import ScreenCapturePort
from .input_control import InputControlPort
from .ocr import OcrPort
from .protocol import ProtocolPort, BaseProtocol

__all__ = [
    "EventDispatcher", "SyncEventDispatcher",
    "ScreenCapturePort", "InputControlPort", "OcrPort",
    "ProtocolPort", "BaseProtocol",
]
