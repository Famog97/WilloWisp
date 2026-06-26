"""
iscs_assets.py
════════════════════════════════════════════════════════════════════════════
ISCS AutoClick — Asset & Region Repository
════════════════════════════════════════════════════════════════════════════

Manages a global, persistent store of reusable verification assets.

Entities
────────
  TextAsset     — expected OCR string, reusable across any step/flow/card
  ImageAsset    — reference image for OpenCV template matching
  Region        — named screen area (coords + monitor), reusable across steps
  FlowTemplate  — saved reusable sequence of Procedure steps

Storage
───────
  iscs_assets.json        — beside baru.py (APP_DIR)
  assets/images/          — image files referenced by ImageAsset entries

ID scheme
─────────
  TXT_0001 / IMG_0001 / RGN_0001 / TPL_0001
  Auto-incremented, never reused after deletion.

Usage
─────
  from iscs_assets import AssetManager

  mgr = AssetManager.instance()          # singleton, loads once
  t   = mgr.create_text_asset("High Alarm Label", "HIGH ALARM")
  r   = mgr.create_region("Alarm Panel Top Row", [120, 45, 890, 95], monitor=1)
  mgr.save()                             # explicit save (also auto-saves on write)
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# OCR engine (shared with the rest of the app). Guarded so the module still
# imports if iscs_OCR is unavailable — text bindings then fall back to
# pytesseract directly inside _exec_text.
try:
    import iscs_OCR
except ImportError:
    iscs_OCR = None

logger = logging.getLogger("AutoClick")

# ── resolved at first AssetManager.instance() call ───────────────────────────
_APP_DIR: Optional[Path] = None

def set_app_dir(path: Union[str, Path]) -> None:
    """Called once from baru.py at startup to anchor asset storage."""
    global _APP_DIR
    _APP_DIR = Path(path)


def _get_app_dir() -> Path:
    if _APP_DIR is not None:
        return _APP_DIR
    # Fallback: resolve relative to this file's location
    return Path(__file__).parent


# ── Asset-store schema versioning (FR-27) ─────────────────────────────────────
# Tags iscs_assets.json so older/newer files coexist. Bump and register a
# migrator when the file shape changes. Kept self-contained (no iscs_core
# dependency) so the asset store stays standalone.
ASSETS_SCHEMA_VERSION = 1
_ASSET_MIGRATORS = {}   # {from_version: callable(dict) -> dict}


def register_asset_migrator(from_version: int, fn) -> None:
    """Register a migrator upgrading the asset file FROM `from_version` to the next."""
    _ASSET_MIGRATORS[from_version] = fn


def _migrate_assets_dict(raw: dict, migrators=None, current: int = ASSETS_SCHEMA_VERSION) -> dict:
    """Upgrade a persisted asset dict to the current schema version. Missing
    version = current (pre-versioning files are already in the current shape);
    a newer version raises rather than silently mangling the file."""
    migrators = _ASSET_MIGRATORS if migrators is None else migrators
    version = raw.get("schema_version", current)
    if not isinstance(version, int):
        version = current
    if version > current:
        raise ValueError(
            f"Asset file schema_version {version} is newer than supported ({current}). "
            f"Upgrade the application to load this asset library."
        )
    while version < current:
        migrator = migrators.get(version)
        if migrator is None:
            raise ValueError(f"No migrator registered to upgrade asset schema from v{version}.")
        raw = migrator(raw)
        version += 1
    return raw


# ═════════════════════════════════════════════════════════════════════════════
#  ENTITY  DATACLASSES
# ═════════════════════════════════════════════════════════════════════════════

# M2.3: asset entity value objects relocated to core/domain/assets.py;
# re-exported here as shims so all existing references are unchanged.
from core.domain.assets import (
    TextAsset, ImageAsset, Region, FlowTemplate, BindingType, StepBinding,
)


# ═════════════════════════════════════════════════════════════════════════════
#  ASSET  MANAGER  (singleton)
# ═════════════════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AssetManager:
    """
    Singleton manager for all assets, regions, and flow templates.

    Thread-safe writes via an internal lock.
    Auto-saves after every mutating operation.

    Access via AssetManager.instance() — never instantiate directly.
    """

    _instance:  Optional["AssetManager"] = None
    _lock:      threading.Lock           = threading.Lock()

    # ── singleton ─────────────────────────────────────────────────────────────
    @classmethod
    def instance(cls) -> "AssetManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._load()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Force re-load from disk (useful after external file changes)."""
        with cls._lock:
            cls._instance = None

    # ── init ──────────────────────────────────────────────────────────────────
    def __init__(self) -> None:
        self._rw_lock: threading.RLock = threading.RLock()

        self._text_assets:    Dict[str, TextAsset]    = {}
        self._image_assets:   Dict[str, ImageAsset]   = {}
        self._regions:        Dict[str, Region]        = {}
        self._flow_templates: Dict[str, FlowTemplate]  = {}

        # ID counters — highest numeric suffix seen, incremented for new IDs
        self._counters: Dict[str, int] = {
            "TXT": 0, "IMG": 0, "RGN": 0, "TPL": 0,
        }

    # ── paths ─────────────────────────────────────────────────────────────────
    @property
    def _json_path(self) -> Path:
        return _get_app_dir() / "iscs_assets.json"

    @property
    def images_dir(self) -> Path:
        p = _get_app_dir() / "assets" / "images"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── persistence ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        """Load from iscs_assets.json. Safe to call if file doesn't exist yet."""
        with self._rw_lock:
            if not self._json_path.exists():
                logger.info("iscs_assets: No asset file found — starting fresh.")
                return
            try:
                raw = json.loads(self._json_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"iscs_assets: Failed to load {self._json_path}: {e}")
                return

            try:
                raw = _migrate_assets_dict(raw)        # upgrade older files first (FR-27)
            except Exception as e:
                logger.error(f"iscs_assets: Schema migration failed: {e}")
                return

            for d in raw.get("text_assets", []):
                try:
                    t = TextAsset.from_dict(d)
                    self._text_assets[t.id] = t
                    self._bump_counter("TXT", t.id)
                except Exception as e:
                    logger.warning(f"iscs_assets: Skipping bad text asset: {e}")

            for d in raw.get("image_assets", []):
                try:
                    i = ImageAsset.from_dict(d)
                    self._image_assets[i.id] = i
                    self._bump_counter("IMG", i.id)
                except Exception as e:
                    logger.warning(f"iscs_assets: Skipping bad image asset: {e}")

            for d in raw.get("regions", []):
                try:
                    r = Region.from_dict(d)
                    self._regions[r.id] = r
                    self._bump_counter("RGN", r.id)
                except Exception as e:
                    logger.warning(f"iscs_assets: Skipping bad region: {e}")

            for d in raw.get("flow_templates", []):
                try:
                    ft = FlowTemplate.from_dict(d)
                    self._flow_templates[ft.id] = ft
                    self._bump_counter("TPL", ft.id)
                except Exception as e:
                    logger.warning(f"iscs_assets: Skipping bad template: {e}")

            logger.info(
                f"iscs_assets: Loaded "
                f"{len(self._text_assets)} text, "
                f"{len(self._image_assets)} image, "
                f"{len(self._regions)} regions, "
                f"{len(self._flow_templates)} templates."
            )

    def save(self) -> None:
        """Persist current state to iscs_assets.json (atomic write)."""
        with self._rw_lock:
            data = {
                "schema_version": ASSETS_SCHEMA_VERSION,
                "text_assets":    [t.to_dict() for t in self._text_assets.values()],
                "image_assets":   [i.to_dict() for i in self._image_assets.values()],
                "regions":        [r.to_dict() for r in self._regions.values()],
                "flow_templates": [ft.to_dict() for ft in self._flow_templates.values()],
            }
            tmp = self._json_path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                               encoding="utf-8")
                tmp.replace(self._json_path)
            except Exception as e:
                logger.error(f"iscs_assets: Save failed: {e}")
                if tmp.exists():
                    tmp.unlink(missing_ok=True)

    # ── ID generation ─────────────────────────────────────────────────────────
    def _bump_counter(self, prefix: str, existing_id: str) -> None:
        """Update counter from an already-loaded ID string."""
        try:
            num = int(existing_id.split("_", 1)[1])
            self._counters[prefix] = max(self._counters[prefix], num)
        except (IndexError, ValueError):
            pass

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}_{self._counters[prefix]:04d}"

    # ── TEXT ASSET CRUD ───────────────────────────────────────────────────────
    def create_text_asset(self, name: str, value: str,
                          description: str = "") -> TextAsset:
        with self._rw_lock:
            t = TextAsset(
                id          = self._next_id("TXT"),
                name        = name.strip(),
                value       = value,
                description = description,
                created_at  = _now_iso(),
                updated_at  = _now_iso(),
            )
            self._text_assets[t.id] = t
        self.save()
        logger.info(f"iscs_assets: Created text asset {t.id} — {t.name!r}")
        return t

    def update_text_asset(self, asset_id: str, *,
                          name: Optional[str] = None,
                          value: Optional[str] = None,
                          description: Optional[str] = None) -> Optional[TextAsset]:
        with self._rw_lock:
            t = self._text_assets.get(asset_id)
            if t is None:
                return None
            if name        is not None: t.name        = name.strip()
            if value       is not None: t.value       = value
            if description is not None: t.description = description
            t.updated_at = _now_iso()
        self.save()
        return t

    def delete_text_asset(self, asset_id: str) -> bool:
        with self._rw_lock:
            if asset_id not in self._text_assets:
                return False
            del self._text_assets[asset_id]
        self.save()
        logger.info(f"iscs_assets: Deleted text asset {asset_id}")
        return True

    def get_text_asset(self, asset_id: str) -> Optional[TextAsset]:
        return self._text_assets.get(asset_id)

    def list_text_assets(self) -> List[TextAsset]:
        return sorted(self._text_assets.values(), key=lambda x: x.id)

    # ── IMAGE ASSET CRUD ──────────────────────────────────────────────────────
    def create_image_asset(self, name: str, source_path: Union[str, Path],
                           description: str = "") -> ImageAsset:
        """
        Copy source_path into assets/images/ under a stable filename.
        source_path can be any image file — PNG, JPG etc.
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Image source not found: {source}")

        with self._rw_lock:
            new_id   = self._next_id("IMG")
            filename = f"{new_id}{source.suffix.lower()}"
            dest     = self.images_dir / filename
            shutil.copy2(source, dest)

            w, h = 0, 0
            try:
                from PIL import Image as _PILImage
                with _PILImage.open(dest) as img:
                    w, h = img.size
            except Exception:
                pass

            ia = ImageAsset(
                id          = new_id,
                name        = name.strip(),
                filename    = filename,
                description = description,
                width       = w,
                height      = h,
                created_at  = _now_iso(),
                updated_at  = _now_iso(),
            )
            self._image_assets[ia.id] = ia
        self.save()
        logger.info(f"iscs_assets: Created image asset {ia.id} — {ia.name!r} ({w}x{h})")
        return ia

    def create_image_asset_from_bytes(self, name: str, data: bytes,
                                       ext: str = ".png",
                                       description: str = "") -> ImageAsset:
        """Create image asset directly from in-memory bytes (e.g. screenshot crop)."""
        with self._rw_lock:
            new_id   = self._next_id("IMG")
            filename = f"{new_id}{ext}"
            dest     = self.images_dir / filename
            dest.write_bytes(data)

            w, h = 0, 0
            try:
                from PIL import Image as _PILImage
                import io
                with _PILImage.open(io.BytesIO(data)) as img:
                    w, h = img.size
            except Exception:
                pass

            ia = ImageAsset(
                id          = new_id,
                name        = name.strip(),
                filename    = filename,
                description = description,
                width       = w,
                height      = h,
                created_at  = _now_iso(),
                updated_at  = _now_iso(),
            )
            self._image_assets[ia.id] = ia
        self.save()
        return ia

    def update_image_asset(self, asset_id: str, *,
                           name: Optional[str] = None,
                           source_path: Optional[Union[str, Path]] = None,
                           description: Optional[str] = None) -> Optional[ImageAsset]:
        with self._rw_lock:
            ia = self._image_assets.get(asset_id)
            if ia is None:
                return None
            if name        is not None: ia.name        = name.strip()
            if description is not None: ia.description = description
            if source_path is not None:
                src = Path(source_path)
                new_filename = f"{asset_id}{src.suffix.lower()}"
                dest = self.images_dir / new_filename
                shutil.copy2(src, dest)
                # Remove old file if different name
                old = self.images_dir / ia.filename
                if old != dest and old.exists():
                    old.unlink(missing_ok=True)
                ia.filename = new_filename
                try:
                    from PIL import Image as _PILImage
                    with _PILImage.open(dest) as img:
                        ia.width, ia.height = img.size
                except Exception:
                    pass
            ia.updated_at = _now_iso()
        self.save()
        return ia

    def delete_image_asset(self, asset_id: str,
                           delete_file: bool = True) -> bool:
        with self._rw_lock:
            ia = self._image_assets.get(asset_id)
            if ia is None:
                return False
            if delete_file:
                img_path = self.images_dir / ia.filename
                img_path.unlink(missing_ok=True)
            del self._image_assets[asset_id]
        self.save()
        logger.info(f"iscs_assets: Deleted image asset {asset_id}")
        return True

    def get_image_asset(self, asset_id: str) -> Optional[ImageAsset]:
        return self._image_assets.get(asset_id)

    def get_image_path(self, asset_id: str) -> Optional[Path]:
        ia = self._image_assets.get(asset_id)
        if ia is None:
            return None
        p = self.images_dir / ia.filename
        return p if p.exists() else None

    def list_image_assets(self) -> List[ImageAsset]:
        return sorted(self._image_assets.values(), key=lambda x: x.id)

    # ── REGION CRUD ───────────────────────────────────────────────────────────
    def create_region(self, name: str,
                      coords: tuple[int, int, int, int],
                      monitor_index: int = 0,
                      description: str = "") -> Region:
        x1, y1, x2, y2 = coords
        with self._rw_lock:
            r = Region(
                id            = self._next_id("RGN"),
                name          = name.strip(),
                x1=x1, y1=y1, x2=x2, y2=y2,
                monitor_index = monitor_index,
                description   = description,
                created_at    = _now_iso(),
                updated_at    = _now_iso(),
            )
            self._regions[r.id] = r
        self.save()
        logger.info(f"iscs_assets: Created region {r.id} — {r.name!r} {coords}")
        return r

    def update_region(self, region_id: str, *,
                      name:          Optional[str]                    = None,
                      coords:        Optional[tuple[int,int,int,int]] = None,
                      monitor_index: Optional[int]                    = None,
                      description:   Optional[str]                    = None) -> Optional[Region]:
        with self._rw_lock:
            r = self._regions.get(region_id)
            if r is None:
                return None
            if name          is not None: r.name          = name.strip()
            if description   is not None: r.description   = description
            if monitor_index is not None: r.monitor_index = monitor_index
            if coords        is not None:
                r.x1, r.y1, r.x2, r.y2 = coords
            r.updated_at = _now_iso()
        self.save()
        return r

    def delete_region(self, region_id: str) -> bool:
        with self._rw_lock:
            if region_id not in self._regions:
                return False
            del self._regions[region_id]
        self.save()
        logger.info(f"iscs_assets: Deleted region {region_id}")
        return True

    def get_region(self, region_id: str) -> Optional[Region]:
        return self._regions.get(region_id)

    def list_regions(self) -> List[Region]:
        return sorted(self._regions.values(), key=lambda x: x.id)

    # ── FLOW TEMPLATE CRUD ────────────────────────────────────────────────────
    def create_flow_template(self, name: str, steps: List[dict],
                             description: str = "") -> FlowTemplate:
        with self._rw_lock:
            ft = FlowTemplate(
                id          = self._next_id("TPL"),
                name        = name.strip(),
                description = description,
                steps       = [dict(s) for s in steps],
                created_at  = _now_iso(),
                updated_at  = _now_iso(),
            )
            self._flow_templates[ft.id] = ft
        self.save()
        logger.info(f"iscs_assets: Created template {ft.id} — {ft.name!r} ({len(steps)} steps)")
        return ft

    def update_flow_template(self, template_id: str, *,
                             name:        Optional[str]        = None,
                             steps:       Optional[List[dict]] = None,
                             description: Optional[str]        = None) -> Optional[FlowTemplate]:
        with self._rw_lock:
            ft = self._flow_templates.get(template_id)
            if ft is None:
                return None
            if name        is not None: ft.name        = name.strip()
            if description is not None: ft.description = description
            if steps       is not None: ft.steps       = [dict(s) for s in steps]
            ft.updated_at = _now_iso()
        self.save()
        return ft

    def delete_flow_template(self, template_id: str) -> bool:
        with self._rw_lock:
            if template_id not in self._flow_templates:
                return False
            del self._flow_templates[template_id]
        self.save()
        logger.info(f"iscs_assets: Deleted template {template_id}")
        return True

    def get_flow_template(self, template_id: str) -> Optional[FlowTemplate]:
        return self._flow_templates.get(template_id)

    def list_flow_templates(self) -> List[FlowTemplate]:
        return sorted(self._flow_templates.values(), key=lambda x: x.id)

    # ── SEARCH ────────────────────────────────────────────────────────────────
    def search(self, query: str) -> Dict[str, List[Any]]:
        """
        Search all entity types by name, id, value, or description.
        Returns dict with keys: text_assets, image_assets, regions, templates.
        Empty query returns all entities.
        """
        q = query.strip()
        if not q:
            return {
                "text_assets":    self.list_text_assets(),
                "image_assets":   self.list_image_assets(),
                "regions":        self.list_regions(),
                "flow_templates": self.list_flow_templates(),
            }
        return {
            "text_assets":    [t  for t  in self._text_assets.values()    if t.matches(q)],
            "image_assets":   [i  for i  in self._image_assets.values()   if i.matches(q)],
            "regions":        [r  for r  in self._regions.values()         if r.matches(q)],
            "flow_templates": [ft for ft in self._flow_templates.values()  if ft.matches(q)],
        }

    # ── BINDING RESOLUTION (used by ProcedureRunner at execution time) ────────
    def resolve_binding(self, binding: "StepBinding") -> Dict[str, Any]:
        """
        Resolve a StepBinding to the actual asset values + region coords
        needed at execution time.

        Returns dict with resolved fields, or raises LookupError if
        any referenced entity is missing.
        """
        result: Dict[str, Any] = {
            "type":      binding.type,
            "threshold": binding.threshold,
            "on_fail":   binding.on_fail,
        }

        # Resolve region
        if binding.region_id:
            region = self.get_region(binding.region_id)
            if region is None:
                raise LookupError(f"Region {binding.region_id!r} not found in asset store")
            result["region"]        = region
            result["region_coords"] = region.coords
        else:
            raise LookupError("StepBinding has no region_id")

        # Resolve text asset (TEXT and HYBRID)
        if binding.type in (BindingType.TEXT, BindingType.HYBRID):
            ta = self.get_text_asset(binding.asset_id)
            if ta is None:
                raise LookupError(f"Text asset {binding.asset_id!r} not found")
            result["text_asset"]    = ta
            result["expected_text"] = ta.value

        # Resolve image asset (IMAGE and HYBRID)
        if binding.type in (BindingType.IMAGE, BindingType.HYBRID):
            img_id = (binding.image_asset_id
                      if binding.type == BindingType.HYBRID
                      else binding.asset_id)
            ia = self.get_image_asset(img_id)
            if ia is None:
                raise LookupError(f"Image asset {img_id!r} not found")
            img_path = self.get_image_path(img_id)
            if img_path is None:
                raise LookupError(f"Image file for {img_id!r} not found on disk")
            result["image_asset"] = ia
            result["image_path"]  = img_path

        return result

    # ── STATS ─────────────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, int]:
        return {
            "text_assets":    len(self._text_assets),
            "image_assets":   len(self._image_assets),
            "regions":        len(self._regions),
            "flow_templates": len(self._flow_templates),
        }

    def __repr__(self) -> str:
        s = self.stats()
        return (f"<AssetManager text={s['text_assets']} "
                f"image={s['image_assets']} "
                f"regions={s['regions']} "
                f"templates={s['flow_templates']}>")


# ═════════════════════════════════════════════════════════════════════════════
#  BINDING EXECUTOR  (called by ProcedureRunner — no Tkinter dependency)
# ═════════════════════════════════════════════════════════════════════════════

class BindingExecutor:
    """
    Executes a StepBinding at runtime.
    Called by ProcedureRunner when a step has a binding attached.
    Does NOT modify any existing verification logic.

    Returns a dict:
        {
          "status":   "PASS" | "FAIL" | "SKIP",
          "message":  str,
          "expected": str,
          "actual":   str,
          "score":    float,   # image match score (0.0–1.0) or 1.0 for text
        }
    """

    def __init__(self, asset_manager: Optional[AssetManager] = None) -> None:
        self._mgr = asset_manager or AssetManager.instance()

    def execute(self, binding: StepBinding,
                screenshot_fn: Optional[Any] = None) -> Dict[str, Any]:
        """
        Execute a binding.

        screenshot_fn: callable(x1, y1, x2, y2, monitor_index) -> PIL.Image
                       If None, uses PIL.ImageGrab internally.
        """
        try:
            resolved = self._mgr.resolve_binding(binding)
        except LookupError as e:
            if binding.on_fail == "skip":
                return {"status": "SKIP", "message": str(e),
                        "expected": "", "actual": "", "score": 0.0}
            return {"status": "FAIL", "message": f"Asset resolution failed: {e}",
                    "expected": "", "actual": "", "score": 0.0}

        region: Region = resolved["region"]

        # Capture region screenshot
        try:
            img = self._capture_region(region, screenshot_fn)
        except Exception as e:
            msg = f"Region capture failed: {e}"
            if binding.on_fail == "skip":
                return {"status": "SKIP", "message": msg,
                        "expected": "", "actual": "", "score": 0.0}
            return {"status": "FAIL", "message": msg,
                    "expected": "", "actual": "", "score": 0.0}

        btype = binding.type

        # Dispatch by registered resolver (FR-16) — no per-type branching.
        try:
            resolver = get_binding_resolver(btype)
        except LookupError:
            return {"status": "SKIP",
                    "message": f"Unknown binding type {btype!r}",
                    "expected": "", "actual": "", "score": 0.0}
        return resolver.resolve(img, resolved)

    # ── capture ───────────────────────────────────────────────────────────────
    def _capture_region(self, region: Region, screenshot_fn) -> Any:
        if screenshot_fn is not None:
            return screenshot_fn(region.x1, region.y1,
                                 region.x2, region.y2,
                                 region.monitor_index)
        try:
            from PIL import ImageGrab
            # all_screens=True so non-primary monitors are captured
            full = ImageGrab.grab(all_screens=True)
            return full.crop((region.x1, region.y1, region.x2, region.y2))
        except Exception as e:
            raise RuntimeError(f"PIL ImageGrab failed: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  BINDING RESOLVERS  (Strategy + Registry — FR-16, retires R9)
# ═════════════════════════════════════════════════════════════════════════════
#
# Each binding kind (TEXT / IMAGE / HYBRID / future, e.g. a vision-LLM) is a
# self-contained resolver registered by string key. BindingExecutor dispatches
# by key instead of an if/elif chain, so adding a binding type means dropping in
# a resolver and registering it — no edit to BindingExecutor.
#
# Kept self-contained in this module (no iscs_core import) so the asset store
# stays standalone, consistent with the schema-versioning design (P6.1b).

class BindingResolver:
    """Strategy for executing one binding kind against a captured region image.

    Subclasses set ``kind`` (matches ``BindingType`` / ``StepBinding.type``) and
    implement ``resolve(img, resolved) -> result dict`` returning the same shape
    ``BindingExecutor.execute`` does (status / message / expected / actual /
    score, plus optional detail keys).
    """
    kind: str = ""

    def resolve(self, img: Any, resolved: dict) -> Dict[str, Any]:
        raise NotImplementedError


_BINDING_RESOLVERS: Dict[str, BindingResolver] = {}


def register_binding_resolver(resolver: BindingResolver, *,
                              override: bool = False) -> None:
    """Register a binding resolver by its ``kind`` key (FR-7 duplicate check)."""
    kind = getattr(resolver, "kind", "")
    if not kind:
        raise ValueError("BindingResolver.kind must be a non-empty string")
    if kind in _BINDING_RESOLVERS and not override:
        raise ValueError(
            f"Binding resolver already registered for kind {kind!r} "
            f"(pass override=True to replace)")
    _BINDING_RESOLVERS[kind] = resolver


def get_binding_resolver(kind: str) -> BindingResolver:
    """Look up a resolver by kind; raises ``LookupError`` with a clear message."""
    try:
        return _BINDING_RESOLVERS[kind]
    except KeyError:
        known = ", ".join(sorted(_BINDING_RESOLVERS)) or "(none)"
        raise LookupError(
            f"No binding resolver registered for {kind!r}. Known kinds: {known}")


def list_binding_resolvers() -> List[str]:
    """All registered binding kinds (drives diagnostics / future UI)."""
    return sorted(_BINDING_RESOLVERS)


class TextBindingResolver(BindingResolver):
    """OCR the region and check the expected text is contained in the result."""
    kind = BindingType.TEXT

    def resolve(self, img: Any, resolved: dict) -> Dict[str, Any]:
        expected: str = resolved["expected_text"]
        asset: TextAsset = resolved["text_asset"]

        actual = ""
        try:
            if iscs_OCR is not None and hasattr(iscs_OCR, "run"):
                actual = iscs_OCR.run(img, layout="sparse").strip()
            else:
                # Fallback — try pytesseract directly
                import pytesseract
                actual = pytesseract.image_to_string(
                    img, config="--oem 3 --psm 11").strip()
        except Exception as e:
            return {"status": "FAIL",
                    "message": f"OCR failed: {e}",
                    "expected": expected, "actual": "", "score": 0.0}

        passed = expected.lower() in actual.lower()
        return {
            "status":   "PASS" if passed else "FAIL",
            "message":  (f"Text match: found {actual!r}"
                         if passed else
                         f"Text mismatch: expected {expected!r}, got {actual!r}"),
            "expected": expected,
            "actual":   actual,
            "score":    1.0 if passed else 0.0,
            "asset_id": asset.id,
            "asset_name": asset.name,
        }


class ImageBindingResolver(BindingResolver):
    """Template-match the region against the reference image (OpenCV)."""
    kind = BindingType.IMAGE

    def resolve(self, img: Any, resolved: dict) -> Dict[str, Any]:
        threshold: float   = resolved["threshold"]
        img_path:  Path    = resolved["image_path"]
        asset:     ImageAsset = resolved["image_asset"]

        try:
            import cv2
            import numpy as np
            from PIL import Image as _PILImage

            # Convert region crop to BGR numpy
            region_np = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
            # Load template
            template  = cv2.imread(str(img_path))
            if template is None:
                raise FileNotFoundError(f"Template image unreadable: {img_path}")

            rh, rw = region_np.shape[:2]
            th, tw = template.shape[:2]

            # cv2.matchTemplate requires the template to be SMALLER than the
            # search image. A verify-custom reference is cropped from the same
            # region it checks, so template and region are ~equal size — which
            # makes matchTemplate return a degenerate 0.000. Detect that case
            # and compare the two images directly at a common size instead.
            if th >= rh or tw >= rw:
                # Resize template to exactly the region size, then score by
                # normalized correlation of the whole images.
                template_rs = cv2.resize(template, (rw, rh),
                                         interpolation=cv2.INTER_AREA)
                a = region_np.astype("float32").ravel()
                b = template_rs.astype("float32").ravel()
                a -= a.mean(); b -= b.mean()
                denom = (np.linalg.norm(a) * np.linalg.norm(b))
                score = float(np.dot(a, b) / denom) if denom > 1e-9 else 0.0
                score = max(0.0, score)   # clamp negative correlation to 0
            else:
                result = cv2.matchTemplate(region_np, template, cv2.TM_CCOEFF_NORMED)
                score  = float(result.max())

            passed = score >= threshold

            return {
                "status":     "PASS" if passed else "FAIL",
                "message":    (f"Image match score {score:.3f} >= {threshold}"
                               if passed else
                               f"Image match score {score:.3f} < threshold {threshold}"),
                "expected":   f"≥ {threshold} (template: {asset.name})",
                "actual":     f"{score:.3f}",
                "score":      score,
                "asset_id":   asset.id,
                "asset_name": asset.name,
            }
        except ImportError:
            return {"status": "SKIP",
                    "message": "opencv-python not installed — image binding skipped",
                    "expected": "", "actual": "", "score": 0.0}
        except Exception as e:
            return {"status": "FAIL",
                    "message": f"Image match error: {e}",
                    "expected": "", "actual": "", "score": 0.0}


class HybridBindingResolver(BindingResolver):
    """Both the TEXT and IMAGE checks must pass.

    Delegates to the registered TEXT and IMAGE resolvers, so swapping either of
    those (e.g. a smarter text backend) automatically applies to HYBRID too.
    """
    kind = BindingType.HYBRID

    def resolve(self, img: Any, resolved: dict) -> Dict[str, Any]:
        text_result  = get_binding_resolver(BindingType.TEXT).resolve(img, resolved)
        image_result = get_binding_resolver(BindingType.IMAGE).resolve(img, resolved)

        text_pass  = text_result["status"]  == "PASS"
        image_pass = image_result["status"] == "PASS"
        both_pass  = text_pass and image_pass

        return {
            "status":    "PASS" if both_pass else "FAIL",
            "message":   (f"Hybrid: text={'PASS' if text_pass else 'FAIL'}, "
                          f"image={'PASS' if image_pass else 'FAIL'}"),
            "expected":  f"text={text_result['expected']!r}  "
                         f"image≥{resolved['threshold']}",
            "actual":    f"text={text_result['actual']!r}  "
                         f"image={image_result['score']:.3f}",
            "score":     min(image_result["score"], 1.0 if text_pass else 0.0),
            "text_detail":  text_result,
            "image_detail": image_result,
        }


# Register the built-in resolvers. New binding kinds register the same way.
register_binding_resolver(TextBindingResolver())
register_binding_resolver(ImageBindingResolver())
register_binding_resolver(HybridBindingResolver())


# ── Module-level convenience functions ───────────────────────────────────────

def get_manager() -> AssetManager:
    """Shortcut for AssetManager.instance()."""
    return AssetManager.instance()
