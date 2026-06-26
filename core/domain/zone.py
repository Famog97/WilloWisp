"""
Zone — a named screen rectangle (pure geometry, absolute desktop coords).

Domain value object (R-HEX-3): no UI/toolkit dependency. Relocated verbatim from
``baru.Zone`` (M2.1); ``baru`` re-exports it as a shim.
"""
from __future__ import annotations


class Zone:
    def __init__(self, x1, y1, x2, y2, zone_type="include", monitor_index=0):
        self.x1, self.y1 = min(x1, x2), min(y1, y2)
        self.x2, self.y2 = max(x1, x2), max(y1, y2)
        self.zone_type = zone_type
        self.label = ""
        self.monitor_index = monitor_index  # which display this zone was drawn on

    @property
    def width(self):  return self.x2 - self.x1
    @property
    def height(self): return self.y2 - self.y1
    @property
    def cx(self): return self.x1 + self.width // 2
    @property
    def cy(self): return self.y1 + self.height // 2

    def contains(self, x, y): return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def to_dict(self):
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2,
                "type": self.zone_type, "label": self.label, "monitor_index": self.monitor_index}

    @classmethod
    def from_dict(cls, d):
        z = cls(d["x1"], d["y1"], d["x2"], d["y2"], d["type"], d.get("monitor_index", 0))
        z.label = d.get("label", "")
        return z
