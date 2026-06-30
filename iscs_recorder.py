"""
iscs_recorder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Screen Recording Subsystem for ISCS Framework.
Captures the full screen as MP4, composites overlay text per-frame,
and auto-splits into hourly segments.

Dependencies (pip-installable, no external binary needed):
    pip install imageio imageio-ffmpeg Pillow

Usage (called by SuiteRunner / SuitePanel):
    from iscs_recorder import Recorder, RecorderSettings

    settings = RecorderSettings(fps=5, show_timestamp=True, show_remark=True)
    rec = Recorder(settings, card_name="Card 01", evidence_dir=Path("..."))
    rec.start()
    rec.update_point("BUCS-AMS-ACU-OCC-0008", "Medium Level Security Door", "Intrusion Alarm")
    rec.stop()
"""

from __future__ import annotations

import os
import re
import time
import math
import logging
import threading
import datetime
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("AutoClick")

# ── Optional PIL ──────────────────────────────────────────────────────────────
try:
    from PIL import ImageGrab, ImageDraw, ImageFont, Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False
    logger.warning("iscs_recorder: Pillow not available — recording disabled.")

# ── imageio / ffmpeg ──────────────────────────────────────────────────────────
_IMAGEIO_OK = False
_FFMPEG_PATH: Optional[str] = None

try:
    import imageio
    import imageio_ffmpeg
    _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    _IMAGEIO_OK = True
    logger.info(f"iscs_recorder: imageio-ffmpeg ready at {_FFMPEG_PATH}")
except Exception as _e:
    logger.warning(f"iscs_recorder: imageio-ffmpeg not available — {_e}")

RECORDER_AVAILABLE = _PIL_OK and _IMAGEIO_OK

# ── Constants ─────────────────────────────────────────────────────────────────
SEGMENT_SECONDS   = 3600          # 1-hour hard split
STORAGE_WARN_GB   = 2.0           # warn before recording if projected > this
OVERLAY_FONT_SIZE = 18            # px, for PIL ImageFont fallback
OVERLAY_PADDING   = 8
OVERLAY_BG_ALPHA  = 160           # 0-255 translucency of the dark banner
FPS_OPTIONS       = [1, 5, 10, 15, 24, 30, 60]
DEFAULT_FPS       = 5


# ── Settings dataclass ────────────────────────────────────────────────────────
@dataclass
class RecorderSettings:
    enabled:         bool = False
    fps:             int  = DEFAULT_FPS
    show_timestamp:  bool = True
    show_remark:     bool = True
    warn_threshold_gb: float = STORAGE_WARN_GB
    capture_display:    str  = "Auto"
    capture_resolution: str  = "Native (recommended)"

    def to_dict(self) -> dict:
        return {
            "enabled":           self.enabled,
            "fps":               self.fps,
            "show_timestamp":    self.show_timestamp,
            "show_remark":       self.show_remark,
            "warn_threshold_gb": self.warn_threshold_gb,
            "capture_display":    self.capture_display,
            "capture_resolution": self.capture_resolution,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RecorderSettings":
        s = cls()
        s.enabled           = bool(d.get("enabled",           s.enabled))
        s.fps               = int (d.get("fps",               s.fps))
        s.show_timestamp    = bool(d.get("show_timestamp",    s.show_timestamp))
        s.show_remark       = bool(d.get("show_remark",       s.show_remark))
        s.warn_threshold_gb = float(d.get("warn_threshold_gb", s.warn_threshold_gb))
        s.capture_display    = str (d.get("capture_display",    s.capture_display or "Auto"))
        s.capture_resolution = str (d.get("capture_resolution", s.capture_resolution or "Native (recommended)"))
        # Clamp fps to valid options
        if s.fps not in FPS_OPTIONS:
            s.fps = DEFAULT_FPS
        return s


def _sanitise(name: str) -> str:
    """Strip chars that are invalid in Windows filenames."""
    return re.sub(r'[^\w\-]', '_', name).strip('_') or "Recording"


def _estimate_size_gb(fps: int, duration_secs: int,
                      width: int = 1920, height: int = 1080) -> float:
    """
    Rough MP4 H.264 size estimate.
    Assumes ~0.1 bits/pixel/frame at medium quality (reasonable for SCADA screens).
    """
    bits_per_frame = width * height * 0.1
    total_bits = bits_per_frame * fps * duration_secs
    return total_bits / 8 / (1024 ** 3)


def check_disk_space(path: Path, needed_gb: float) -> tuple[bool, float]:
    """
    Returns (ok, free_gb).
    ok=False means free_gb < needed_gb.
    """
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        return free_gb >= needed_gb, free_gb
    except Exception:
        return True, 999.0   # can't check — proceed without warning


# ── Font helper ───────────────────────────────────────────────────────────────
def _get_font(size: int):
    """Return a PIL font, falling back gracefully."""
    try:
        # Try a few common Windows/cross-platform fonts
        for name in ("consola.ttf", "Consolas.ttf", "DejaVuSansMono.ttf",
                     "arial.ttf", "Arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                pass
        return ImageFont.load_default()
    except Exception:
        return None


# ── Core Recorder ─────────────────────────────────────────────────────────────
class Recorder:
    """
    Background screen recorder.  Thread-safe.

    Lifecycle:
        rec = Recorder(settings, card_name, evidence_dir)
        rec.start()                              # begins capture loop
        rec.update_point(pid, equip, attr)       # updates overlay remark
        rec.stop()                               # finalises current segment
    """

    def __init__(self,
                 settings:     RecorderSettings,
                 card_name:    str,
                 evidence_dir: Path,
                 monitor_bbox: Optional[Tuple[int, int, int, int]] = None,
                 target_resolution: Optional[Tuple[int, int]] = None):
        self.settings     = settings
        self.card_name    = _sanitise(card_name)
        self.evidence_dir = Path(evidence_dir)
        self._monitor_bbox = monitor_bbox
        self._target_resolution = target_resolution

        self._lock          = threading.Lock()
        self._stop_evt      = threading.Event()
        self._thread:       Optional[threading.Thread] = None

        # Overlay state (updated from main thread via update_point)
        self._remark_point_id: str = ""
        self._remark_equip:    str = ""
        self._remark_attr:     str = ""

        # Segment tracking
        self._segment_idx:   int = 1
        self._segment_start: Optional[datetime.datetime] = None
        self._run_ts:        str = ""          # set at start(), used in filenames

        # Font — loaded once
        self._font     = _get_font(OVERLAY_FONT_SIZE)
        self._font_sm  = _get_font(max(12, OVERLAY_FONT_SIZE - 4))

        # Writer handle (imageio FFmpegWriter)
        self._writer = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """
        Start recording.  Returns False if unavailable or already running.
        Caller should check return value and show a warning if False.
        """
        if not RECORDER_AVAILABLE:
            logger.warning("iscs_recorder: Cannot start — dependencies missing.")
            return False
        if self._thread and self._thread.is_alive():
            logger.warning("iscs_recorder: Already running.")
            return False

        self._stop_evt.clear()
        self._run_ts      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._segment_idx = 1
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="iscs-recorder")
        self._thread.start()
        logger.info(f"iscs_recorder: Started for card '{self.card_name}' "
                    f"@ {self.settings.fps} fps")
        return True

    def stop(self):
        """Signal the recording loop to stop and wait for it to finish."""
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._close_writer()
        logger.info("iscs_recorder: Stopped.")

    def update_point(self, point_id: str = "",
                     equip_desc: str = "",
                     attr_desc:  str = ""):
        """
        Thread-safe update of the overlay remark text.
        Call this each time a new point begins verification.
        Format on screen: POINT_ID  EQUIP_DESC: ATTR_DESC
        """
        with self._lock:
            self._remark_point_id = str(point_id).strip()
            self._remark_equip    = str(equip_desc).strip()
            self._remark_attr     = str(attr_desc).strip()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── Internal loop ─────────────────────────────────────────────────────────

    def _loop(self):
        fps      = self.settings.fps
        interval = 1.0 / fps

        self._open_new_segment()

        next_frame = time.monotonic()

        while not self._stop_evt.is_set():
            now = time.monotonic()
            if now < next_frame:
                time.sleep(min(0.01, next_frame - now))
                continue

            # Check 1-hour split
            if self._segment_start:
                elapsed = (datetime.datetime.now() - self._segment_start).total_seconds()
                if elapsed >= SEGMENT_SECONDS:
                    self._close_writer()
                    self._segment_idx += 1
                    self._open_new_segment()

            # Grab frame
            frame = self._grab_frame()
            if frame is not None and self._writer is not None:
                try:
                    self._writer.append_data(frame)
                except Exception as e:
                    logger.error(f"iscs_recorder: Frame write error — {e}")

            next_frame += interval

        self._close_writer()

    def _output_size(self) -> tuple[int, int]:
        """Resolves the output frame resolution based on target configuration."""
        if self._target_resolution:
            return self._target_resolution
        if self._monitor_bbox:
            return (self._monitor_bbox[2], self._monitor_bbox[3]) # width, height
        return self._screen_size()

    def _open_new_segment(self):
        """Open a new FFmpeg writer for the next segment file."""
        path = self._segment_path()
        fps  = self.settings.fps

        try:
            # Probe screen size for writer dimensions
            w, h = self._output_size()
            self._writer = imageio.get_writer(
                str(path),
                format="ffmpeg",
                mode="I",
                fps=fps,
                codec="libx264",
                output_params=[
                    "-crf",  "28",          # quality (18=lossless, 28=good, 35=small)
                    "-pix_fmt", "yuv420p",  # broad compatibility
                    "-preset", "ultrafast", # low CPU during test run
                ],
            )
            self._segment_start = datetime.datetime.now()
            logger.info(f"iscs_recorder: Opened segment → {path.name}")
        except Exception as e:
            logger.error(f"iscs_recorder: Failed to open writer — {e}")
            self._writer = None

    def _close_writer(self):
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception as e:
                logger.warning(f"iscs_recorder: Error closing writer — {e}")
            finally:
                self._writer = None

    def _segment_path(self) -> Path:
        """
        Filename scheme:
          1st segment:  CardName_20250610_143022.mp4
          2nd+ segment: CardName_Part2_20250610_143022.mp4
        """
        if self._segment_idx == 1:
            name = f"{self.card_name}_{self._run_ts}.mp4"
        else:
            name = f"{self.card_name}_Part{self._segment_idx}_{self._run_ts}.mp4"
        return self.evidence_dir / name

    def _screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the primary screen."""
        try:
            img = ImageGrab.grab(all_screens=False)
            return img.size
        except Exception:
            return (1920, 1080)

    def _grab_frame(self):
        """Grab the correct screen region and apply the overlay text banner."""
        if not _PIL_OK:
            return None
        try:
            import numpy as np
            import ctypes
            
            if self._monitor_bbox:
                # 1. Query the virtual screen offsets to handle multi-monitor layout accurately
                vx_left = ctypes.windll.user32.GetSystemMetrics(76) # SM_XVIRTUALSCREEN
                vy_top  = ctypes.windll.user32.GetSystemMetrics(77) # SM_YVIRTUALSCREEN
                
                # 2. Grab the entire virtual desktop spanning all monitors
                full_desktop = ImageGrab.grab(all_screens=True).convert("RGB")
                
                # 3. Map target physical coordinates to virtual space
                x1, y1, w, h = self._monitor_bbox
                crop_x1 = x1 - vx_left
                crop_y1 = y1 - vy_top
                crop_x2 = crop_x1 + w
                crop_y2 = crop_y1 + h
                
                img = full_desktop.crop((crop_x1, crop_y1, crop_x2, crop_y2))
            else:
                img = ImageGrab.grab(all_screens=False).convert("RGB")

            # Apply resizing if target scale was specified
            if self._target_resolution:
                tw, th = self._target_resolution
                if img.size != (tw, th):
                    img = img.resize((tw, th), Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS)

            # 4. Burn the current Point ID, Equipment, and Attribute onto the frame
            img = self._composite_overlay(img)
            return np.array(img)
        except Exception as e:
            logger.debug(f"iscs_recorder: Grab error — {e}")
            return None

    # ── Overlay compositing ───────────────────────────────────────────────────

    def _composite_overlay(self, img: "Image.Image") -> "Image.Image":
        """Burn timestamp and/or remark overlay onto a copy of the frame."""
        if not self.settings.show_timestamp and not self.settings.show_remark:
            return img

        draw  = ImageDraw.Draw(img, "RGBA")
        w, h  = img.size
        lines = []

        if self.settings.show_timestamp:
            ts = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            lines.append(("ts", ts))

        if self.settings.show_remark:
            with self._lock:
                pid   = self._remark_point_id
                equip = self._remark_equip
                attr  = self._remark_attr

            if pid or equip:
                # Format: BUCS-AMS-ACU-OCC-0008  Medium Level Security Door: Intrusion Alarm
                parts = [pid]
                if equip and attr:
                    parts.append(f"{equip}: {attr}")
                elif equip:
                    parts.append(equip)
                elif attr:
                    parts.append(attr)
                lines.append(("remark", "  ".join(p for p in parts if p)))

        if not lines:
            return img

        font    = self._font    or ImageFont.load_default()
        font_sm = self._font_sm or font

        line_h  = OVERLAY_FONT_SIZE + 4
        banner_h = len(lines) * line_h + OVERLAY_PADDING * 2

        # Draw semi-transparent banner at bottom-left
        draw.rectangle(
            [(0, h - banner_h), (w, h)],
            fill=(0, 0, 0, OVERLAY_BG_ALPHA)
        )

        y = h - banner_h + OVERLAY_PADDING
        for kind, text in lines:
            f = font if kind == "ts" else font_sm
            color = (180, 220, 255, 255) if kind == "ts" else (255, 220, 100, 255)
            draw.text((OVERLAY_PADDING, y), text, font=f, fill=color)
            y += line_h

        return img


# ── Storage warning helper (call before Recorder.start) ──────────────────────
def pre_flight_check(settings: RecorderSettings,
                     evidence_dir: Path,
                     expected_duration_secs: int = 3600) -> tuple[bool, str]:
    """
    Returns (ok, message).
    ok=False means there is a problem the user should confirm before proceeding.
    """
    if not RECORDER_AVAILABLE:
        return False, (
            "Screen recording is unavailable.\n\n"
            "Install dependencies:\n"
            "  pip install imageio imageio-ffmpeg\n\n"
            "Recording has been disabled for this run."
        )

    estimated_gb = _estimate_size_gb(settings.fps, expected_duration_secs)
    ok, free_gb  = check_disk_space(evidence_dir, settings.warn_threshold_gb)

    if not ok:
        return False, (
            f"Low disk space warning.\n\n"
            f"Free space : {free_gb:.1f} GB\n"
            f"Threshold  : {settings.warn_threshold_gb:.1f} GB\n"
            f"Estimated  : {estimated_gb:.2f} GB/hour at {settings.fps} fps\n\n"
            f"Continue recording anyway?"
        )

    if estimated_gb > free_gb * 0.8:
        return False, (
            f"Estimated recording size ({estimated_gb:.2f} GB/hr) may exceed\n"
            f"available disk space ({free_gb:.1f} GB free).\n\n"
            f"Continue recording anyway?"
        )

    return True, ""
