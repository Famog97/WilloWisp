"""
InputControlPort (R-HEX driven port) — how the core drives mouse/keyboard.

The core expresses intent (click here, type this, press these keys); a local
adapter wraps pyautogui, a remote/web deployment forwards to an agent on the SCADA
host. The core never imports pyautogui or an OS hook.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class InputControlPort(ABC):
    @abstractmethod
    def click(self, x: int, y: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def right_click(self, x: int, y: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def hotkey(self, *keys: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def type_text(self, text: str, interval: float = 0.0) -> None:
        raise NotImplementedError
