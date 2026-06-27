"""Local InputControlPort adapter — wraps pyautogui.

Driven adapter (outside the hexagon): the only place pyautogui is imported. Lazy
import so the module loads where pyautogui is unavailable.
"""
from __future__ import annotations

from typing import Tuple

from core.ports.input_control import InputControlPort


class PyAutoGuiInput(InputControlPort):
    def click(self, x: int, y: int) -> None:
        import pyautogui
        pyautogui.click(x, y)

    def position(self) -> Tuple[int, int]:
        import pyautogui
        p = pyautogui.position()
        return int(p[0]), int(p[1])

    def right_click(self, x: int, y: int) -> None:
        import pyautogui
        pyautogui.rightClick(x, y)

    def hotkey(self, *keys: str) -> None:
        import pyautogui
        pyautogui.hotkey(*keys)

    def type_text(self, text: str, interval: float = 0.0) -> None:
        import pyautogui
        pyautogui.typewrite(text, interval=interval)
