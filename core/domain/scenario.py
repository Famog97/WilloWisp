"""
Scenario-domain value objects.

Currently hosts ``Monitor`` (a physical display descriptor). ``Scenario`` and
``SuiteCard`` join here in a later M2.1 sub-step. Domain value objects: no UI
dependency. Relocated verbatim from ``baru`` (M2.1); ``baru`` re-exports them.
"""
from __future__ import annotations

import re


class Monitor:
    def __init__(self, index, x, y, width, height, name=""):
        self.index, self.x, self.y, self.width, self.height = index, x, y, width, height
        self.name = name or f"Monitor {index + 1}"
        match = re.search(r'\d+', self.name)
        self.display_num = int(match.group()) if match else (index + 1)

    @property
    def label(self):
        primary = " ★" if self.x == 0 and self.y == 0 else ""
        return f"Display {self.display_num}{primary}  —  {self.width}×{self.height}  @ ({self.x}, {self.y})"
