"""
Asset-domain value objects (M2.3).

Pure data: the reusable verification assets (text / image / region / flow-template)
and the step-binding descriptor. Relocated verbatim from ``iscs_assets``;
``iscs_assets`` re-exports them as shims. No I/O, no UI, no engine dependency — the
repositories / persistence / image store that operate on these live in the
driven-persistence adapter (M2.3 cont).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class TextAsset:
    """A named expected-text string for OCR comparison."""
    id:          str
    name:        str
    value:       str           # expected OCR output
    description: str = ""
    created_at:  str = ""
    updated_at:  str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TextAsset":
        return cls(
            id          = d["id"],
            name        = d.get("name", ""),
            value       = d.get("value", ""),
            description = d.get("description", ""),
            created_at  = d.get("created_at", ""),
            updated_at  = d.get("updated_at", ""),
        )

    def matches(self, query: str) -> bool:
        q = query.lower()
        return (q in self.id.lower() or q in self.name.lower()
                or q in self.value.lower() or q in self.description.lower())


@dataclass
class ImageAsset:
    """A named reference image for OpenCV template matching."""
    id:          str
    name:        str
    filename:    str           # relative to assets/images/
    description: str = ""
    width:       int = 0       # cached dimensions for display
    height:      int = 0
    created_at:  str = ""
    updated_at:  str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ImageAsset":
        return cls(
            id          = d["id"],
            name        = d.get("name", ""),
            filename    = d.get("filename", ""),
            description = d.get("description", ""),
            width       = d.get("width", 0),
            height      = d.get("height", 0),
            created_at  = d.get("created_at", ""),
            updated_at  = d.get("updated_at", ""),
        )

    def matches(self, query: str) -> bool:
        q = query.lower()
        return (q in self.id.lower() or q in self.name.lower()
                or q in self.filename.lower() or q in self.description.lower())


@dataclass
class Region:
    """A named screen area for screenshot cropping / OCR / template matching."""
    id:            str
    name:          str
    x1:            int
    y1:            int
    x2:            int
    y2:            int
    monitor_index: int  = 0    # 0 = primary; matches Monitor.display_num - 1
    description:   str  = ""
    created_at:    str  = ""
    updated_at:    str  = ""

    # ── convenience ──────────────────────────────────────────────────────────
    @property
    def coords(self) -> tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Region":
        return cls(
            id            = d["id"],
            name          = d.get("name", ""),
            x1            = d.get("x1", 0),
            y1            = d.get("y1", 0),
            x2            = d.get("x2", 0),
            y2            = d.get("y2", 0),
            monitor_index = d.get("monitor_index", 0),
            description   = d.get("description", ""),
            created_at    = d.get("created_at", ""),
            updated_at    = d.get("updated_at", ""),
        )

    def matches(self, query: str) -> bool:
        q = query.lower()
        return (q in self.id.lower() or q in self.name.lower()
                or q in self.description.lower())


@dataclass
class FlowTemplate:
    """
    A saved, reusable sequence of Procedure step dicts.
    Steps are stored as plain dicts (Procedure.to_dict()) so this module
    has no import dependency on iscs_workflow.
    """
    id:          str
    name:        str
    description: str        = ""
    steps:       List[dict] = field(default_factory=list)
    created_at:  str        = ""
    updated_at:  str        = ""

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "name":        self.name,
            "description": self.description,
            "steps":       self.steps,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FlowTemplate":
        return cls(
            id          = d["id"],
            name        = d.get("name", ""),
            description = d.get("description", ""),
            steps       = d.get("steps", []),
            created_at  = d.get("created_at", ""),
            updated_at  = d.get("updated_at", ""),
        )

    def matches(self, query: str) -> bool:
        q = query.lower()
        return (q in self.id.lower() or q in self.name.lower()
                or q in self.description.lower())


# ── Binding descriptor (stored inside Procedure.binding) ──────────────────────

class BindingType:
    TEXT   = "TEXT"
    IMAGE  = "IMAGE"
    HYBRID = "HYBRID"


@dataclass
class StepBinding:
    """
    Optional attachment on a Procedure step linking it to an asset + region.
    Stored as Procedure.binding (serialised to/from dict).

    type        : BindingType constant
    asset_id    : id of TextAsset or ImageAsset
    image_asset_id : second asset id for HYBRID (image half)
    region_id   : id of Region to capture
    threshold   : 0.0–1.0 similarity threshold for IMAGE/HYBRID matching
    on_fail     : "fail" | "skip" | "warn"
    """
    type:           str
    asset_id:       str  = ""
    image_asset_id: str  = ""   # HYBRID only — image half
    region_id:      str  = ""
    threshold:      float = 0.85
    on_fail:        str  = "fail"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StepBinding":
        return cls(
            type           = d.get("type", BindingType.TEXT),
            asset_id       = d.get("asset_id", ""),
            image_asset_id = d.get("image_asset_id", ""),
            region_id      = d.get("region_id", ""),
            threshold      = float(d.get("threshold", 0.85)),
            on_fail        = d.get("on_fail", "fail"),
        )

    @classmethod
    def text(cls, asset_id: str, region_id: str,
             on_fail: str = "fail") -> "StepBinding":
        return cls(type=BindingType.TEXT, asset_id=asset_id,
                   region_id=region_id, on_fail=on_fail)

    @classmethod
    def image(cls, asset_id: str, region_id: str,
              threshold: float = 0.85, on_fail: str = "fail") -> "StepBinding":
        return cls(type=BindingType.IMAGE, asset_id=asset_id,
                   region_id=region_id, threshold=threshold, on_fail=on_fail)

    @classmethod
    def hybrid(cls, text_asset_id: str, image_asset_id: str,
               region_id: str, threshold: float = 0.85,
               on_fail: str = "fail") -> "StepBinding":
        return cls(type=BindingType.HYBRID, asset_id=text_asset_id,
                   image_asset_id=image_asset_id, region_id=region_id,
                   threshold=threshold, on_fail=on_fail)
