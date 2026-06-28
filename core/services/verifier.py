"""
core/services/verifier.py  (M2.4 — relocated from baru.ISCSVerifier)

The OCR/colour/blink/datetime verification engine. Rewired off baru module-globals:
PIL via a local guarded import, OCR via ``iscs_OCR``, text matching via
``core.services.text_match``, the severity matrix via ``core.services.config``.
The old ``UPGRADES_AVAILABLE`` guards collapse to "is the anchor/sampler provided?".
``baru`` re-exports ``ISCSVerifier`` as a shim. No tkinter/pyautogui import.
"""
from __future__ import annotations

import datetime
import logging
import time
import re
from pathlib import Path

try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except Exception:
    ImageGrab = None
    PIL_AVAILABLE = False

try:
    import iscs_OCR
except Exception:
    iscs_OCR = None

from core.services.text_match import _ocr_contains, _ocr_fuzzy_contains
from core.services.config import SEVERITY_MATRIX
from core.domain.results import VerifyResult
from core.domain.observation import PanelObservation
from core.services.verification_policy import AlarmPanelVerificationPolicy

logger = logging.getLogger("AutoClick")


def ocr_analyze_image(img, region=None):
    return iscs_OCR.analyze_image(img, region) if iscs_OCR else {}


def ocr_preprocess(img, config=None):
    return iscs_OCR.preprocess(img) if iscs_OCR else img


def ocr_run(img, lang="eng", single_line=False, layout="tabular"):
    return iscs_OCR.run(img, lang, single_line, layout) if iscs_OCR else ""


class ISCSVerifier:
    def __init__(self, zones_dict, config, anchor_mgr=None, stop_event=None):
        """Now accepts a dictionary of all mapped zones."""
        self.zones = zones_dict
        self.alarm_zone = zones_dict.get("alarm_panel")
        self.bbox = (self.alarm_zone.x1, self.alarm_zone.y1, self.alarm_zone.x2, self.alarm_zone.y2) if self.alarm_zone else None
        self.severity_matrix = config.get("severity_matrix", SEVERITY_MATRIX)
        self.config = config
        self.anchor_mgr = anchor_mgr  # Feature 1: AnchorManager (optional)
        self.stop_event = stop_event

    def _get_color_name(self, rgb):
        """Dynamic color-name resolver referencing the Severity Matrix."""
        for entry in self.severity_matrix.values():
            if entry.get("color") == rgb:
                return entry.get("name", "")
        return ""

    def _get_zone_bbox(self, zone_type: str, fallback_zone=None):
        """
        Feature 1: Return (x1,y1,x2,y2) for a zone, using visual anchoring
        if an AnchorManager is available and the zone is linked to an anchor.
        Falls back to the raw zone coordinates if anchoring is not configured.
        """
        if self.anchor_mgr:
            resolved = self.anchor_mgr.resolve(zone_type)
            if resolved:
                return resolved
        if fallback_zone:
            return (fallback_zone.x1, fallback_zone.y1,
                    fallback_zone.x2, fallback_zone.y2)
        return None

    def verify(self, point_id, expected_severity):
        if not (iscs_OCR and iscs_OCR.TESSERACT_AVAILABLE): return False, "OCR not installed/configured."
        expected = self.severity_matrix.get(str(expected_severity))
        if not expected: return False, f"Unknown severity: {expected_severity}"

        if PIL_AVAILABLE and self.bbox:
            try:
                img      = ImageGrab.grab(bbox=self.bbox, all_screens=True)
                raw_text = self._ocr_image(img, single_line=False)

                if str(point_id) not in raw_text:
                    return False, f"Point ID '{point_id}' not found."
                if expected["text"] not in raw_text:
                    return False, f"Severity '{expected['text']}' not found."

                target_rgb = expected["color"]
                if self._color_present(img, target_rgb):
                    return True, "PASS"
                return False, f"Color {target_rgb} not found in bounding box."
            except Exception as e:
                return False, f"Verification Exception: {e}"

        return False, "PIL Not Available or No Alarm Panel Drawn"

    def _grab_zone(self, zone, session_dir: Path, filename: str):
        """Grab a zone screenshot, save it, return (PIL.Image, saved_path)."""
        if not PIL_AVAILABLE or zone is None:
            return None, ""
        try:
            img = ImageGrab.grab(bbox=(zone.x1, zone.y1, zone.x2, zone.y2), all_screens=True)
            path = session_dir / filename
            img.save(str(path))
            return img, str(path)
        except Exception as e:
            logger.warning(f"_grab_zone failed ({filename}): {e}")
            return None, ""

    def _analyze_image(self, img, region=None):
        return ocr_analyze_image(img, region)

    def _preprocess_for_ocr(self, img):
        return ocr_preprocess(img, self.config)

    def _ocr_image(self, img, layout="block"):
        """Internal helper targeting layout styles."""
        lang = self.config.get("tesseract_lang", "eng")
        return ocr_run(img, lang=lang, layout=layout)

    def _color_present(self, img, target_rgb, tolerance=25):
        """Return True if target_rgb appears in the image within tolerance."""
        if img is None:
            return False
        try:
            colors = img.getcolors(maxcolors=1048576)
            if colors is None:
                px = img.load()
                w, h = img.size
                step = max(1, min(w, h) // 40)
                for y in range(0, h, step):
                    for x in range(0, w, step):
                        c = px[x, y]
                        c = c[:3] if isinstance(c, tuple) else (c, c, c)
                        if (abs(c[0] - target_rgb[0]) < tolerance and
                                abs(c[1] - target_rgb[1]) < tolerance and
                                abs(c[2] - target_rgb[2]) < tolerance):
                            return True
                return False
            for _count, color in colors:
                c = color[:3] if isinstance(color, tuple) else (color, color, color)
                if (abs(c[0] - target_rgb[0]) < tolerance and
                        abs(c[1] - target_rgb[1]) < tolerance and
                        abs(c[2] - target_rgb[2]) < tolerance):
                    return True
            return False
        except Exception:
            return False

    BLINK_GREY = (189, 189, 189)

    def _blink_color_present(self, zone, target_rgb, samples=6, interval=0.4, tolerance=25):
        found_target = False
        found_grey   = False
        for s in range(samples):
            try:
                img = ImageGrab.grab(bbox=(zone.x1, zone.y1, zone.x2, zone.y2), all_screens=True)
                if self._color_present(img, target_rgb, tolerance):
                    found_target = True
                if self._color_present(img, self.BLINK_GREY, tolerance):
                    found_grey = True
            except Exception:
                pass
            if found_target:
                break
            if s < samples - 1:
                time.sleep(interval)
        seen = []
        if found_target: seen.append(f"color {target_rgb}")
        if found_grey:   seen.append("grey (189,189,189)")
        detail = "Seen: " + " + ".join(seen) if seen else "No expected colors detected"
        return found_target, found_grey, detail

    def verify_alarm_panel(self, expected: dict, session_dir: Path, point_idx: int = 0,
                           trigger_time: datetime.datetime = None, file_suffix: str = "alarm_panel",
                           sampler=None, trigger_ns=None) -> list:
        """Coordinator: observe the panel, apply the pass/fail policy, save evidence."""
        step = "alarm_panel"
        if not PIL_AVAILABLE or self.alarm_zone is None:
            return [VerifyResult(step, "FAIL", "PIL not available or no alarm_panel zone drawn.")]
        if not (iscs_OCR and iscs_OCR.TESSERACT_AVAILABLE):
            return [VerifyResult(step, "FAIL", "Tesseract OCR not available - check Settings.")]

        obs = self._observe_panel(expected, sampler, trigger_ns)
        logger.debug(f"verify_alarm_panel [{file_suffix}]: target={obs.found_target} "
                     f"grey={obs.found_grey} text={'yes' if obs.merged_text else 'no'}")
        policy = AlarmPanelVerificationPolicy(self.config, self._reocr_severity_cell,
                                              self._get_color_name)
        results = policy.evaluate(expected, obs, step=step,
                                  trigger_time=trigger_time, trigger_ns=trigger_ns)
        self._save_panel_screenshot(obs.best_img, results, session_dir, point_idx,
                                    expected.get("point_id", ""), file_suffix)
        return results

    # -- perception (observe the panel) --------------------------------------
    def _observe_panel(self, expected, sampler, trigger_ns) -> PanelObservation:
        point_id   = expected.get("point_id", "")
        label      = expected.get("label", "")
        target_rgb = expected.get("color", (255, 0, 0))
        lang  = self.config.get("tesseract_lang", "eng")
        _bbox = self._get_zone_bbox("alarm_panel", self.alarm_zone)
        duration = float(self.config.get("detection_duration_sec", 8.0))
        deadline = time.monotonic() + duration

        best_img, merged_text, elapsed = self._poll_panel_text(
            _bbox, point_id, label, lang, deadline, trigger_ns)
        found_target, found_grey, best_img = self._evaluate_panel_color(
            _bbox, target_rgb, sampler, trigger_ns, deadline, best_img)
        return PanelObservation(best_img=best_img, merged_text=merged_text,
                                found_target=found_target, found_grey=found_grey,
                                elapsed_latency=elapsed)

    def _poll_panel_text(self, _bbox, point_id, label, lang, deadline, trigger_ns):
        """Poll the panel with OCR until the exact identifier + value appear (or time out)."""
        best_img, all_texts, elapsed = None, [], 0.0
        start = (trigger_ns / 1e9) if trigger_ns else time.time()
        if _bbox:
            want_id, want_val = str(point_id), str(label)
            while time.monotonic() < deadline:
                if self.stop_event and self.stop_event.is_set():
                    break
                try:
                    img = ImageGrab.grab(bbox=_bbox, all_screens=True)
                    raw = ocr_run(img, lang=lang, layout="block")
                    if want_id in raw and want_val in raw:
                        best_img, all_texts = img, [raw]
                        elapsed = round(time.time() - start, 2)
                        break
                except Exception:
                    pass
                time.sleep(0.5)
        if best_img is None and _bbox:           # timed out -- take one final frame
            try:
                best_img = ImageGrab.grab(bbox=_bbox, all_screens=True)
                all_texts = [ocr_run(best_img, lang=lang, layout="block")]
            except Exception:
                pass
        return best_img, "\n".join(all_texts), elapsed

    def _evaluate_panel_color(self, _bbox, target_rgb, sampler, trigger_ns, deadline, best_img):
        """Decide colour-on / blink-off across the sampler buffer, or a short burst."""
        found_target = found_grey = False
        if sampler is not None and trigger_ns is not None:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                sampler.join(timeout=remaining + 0.5)
            sr = sampler.evaluate(target_rgb, trigger_ns, tolerance=35)
            found_target, found_grey = sr.color_found, sr.blink_detected
            if sr.first_color_frame:
                best_img = sr.first_color_frame.image
        elif _bbox:
            found_target, found_grey, best_img = self._color_burst(_bbox, target_rgb, best_img)
        elif best_img is not None:
            found_target = self._color_present(best_img, target_rgb, tolerance=35)
            found_grey   = self._color_present(best_img, self.BLINK_GREY)
        return found_target, found_grey, best_img

    def _color_burst(self, _bbox, target_rgb, best_img):
        """Grab a short burst of frames; pass if the colour shows in ANY (blink tolerant)."""
        found_target = found_grey = False
        frames = int(self.config.get("blink_burst_frames", 8))
        total  = float(self.config.get("blink_burst_sec", 1.0))
        interval = (total / frames) if frames > 0 else 0.12
        color_frame = None
        for _ in range(max(1, frames)):
            if self.stop_event and self.stop_event.is_set():
                break
            try:
                frame = ImageGrab.grab(bbox=_bbox, all_screens=True)
            except Exception:
                break
            if self._color_present(frame, target_rgb, tolerance=35):
                found_target = True
                if color_frame is None:
                    color_frame = frame
            if self._color_present(frame, self.BLINK_GREY):
                found_grey = True
            if found_target and found_grey:
                break
            time.sleep(interval)
        if color_frame is not None:
            best_img = color_frame
        return found_target, found_grey, best_img

    def _reocr_severity_cell(self, best_img, sev_text) -> bool:
        """Re-OCR just the right-hand severity cell with a digit whitelist (perception)."""
        _W, _H = best_img.size
        crop = best_img.crop((int(_W * 0.85), 0, _W, _H))
        psm = 10 if len(sev_text.strip()) == 1 else 7
        digits = iscs_OCR.run_digits(crop, psm=psm)
        return bool(re.search(rf"(?<![0-9]){re.escape(sev_text.strip())}(?![0-9])", digits))

    def _save_panel_screenshot(self, best_img, results, session_dir, point_idx,
                               point_id, file_suffix):
        """Save the best-evidence frame and attach its path to the first row."""
        if best_img is None:
            return
        status = "PASS" if not any(r.status == "FAIL" for r in results) else "FAIL"
        fname = f"{point_idx:04d}_{point_id}_{file_suffix}_{status}.png"
        try:
            saved = str(session_dir / fname)
            best_img.save(saved)
            results[0] = VerifyResult(results[0].step, results[0].status, results[0].msg, saved)
        except Exception as e:
            logger.warning(f"verify_alarm_panel: could not save screenshot: {e}")

    def verify_list(self, list_type: str, expected: dict, zone, session_dir: Path, point_idx: int = 0, sampler=None, trigger_ns=None) -> list:
        point_id   = expected.get("point_id", "")
        label      = expected.get("label", "")
        target_rgb = expected.get("color", (255, 0, 0))

        color_name = self._get_color_name(target_rgb)
        color_label = f"{color_name} {target_rgb}" if color_name else str(target_rgb)

        if zone is None:
            return [VerifyResult(list_type, "SKIP", f"No {list_type} zone drawn - skipped.")]

        if not PIL_AVAILABLE:
            return [VerifyResult(list_type, "FAIL", "PIL not available.")]

        img, _ = self._grab_zone(zone, session_dir, f"_tmp_{list_type}.png")
        if img is None:
            return [VerifyResult(list_type, "FAIL", "Screenshot capture failed.")]

        raw_text = self._ocr_image(img, layout="tabular")
        logger.debug(f"verify_list[{list_type}] OCR text: {repr(raw_text[:200])}")

        results = []

        # ── Identifier ────────────────────────────────────────────────────────
        if _ocr_contains(str(point_id), raw_text) or (label and _ocr_contains(str(label), raw_text)):
            results.append(VerifyResult(f"{list_type}/identifier", "PASS", f"Point ID '{point_id}' found in OCR."))
        else:
            results.append(VerifyResult(f"{list_type}/identifier", "FAIL", f"Point ID '{point_id}' not found in {list_type} OCR text."))

        # ── Color ──
        if sampler is not None:
            _ns = trigger_ns if trigger_ns else time.time_ns()
            sr  = sampler.evaluate(target_rgb, _ns, tolerance=35)
            if sr.color_found:
                blink = " (blink detected)" if sr.blink_detected else ""
                results.append(VerifyResult(f"{list_type}/color", "PASS", f"Alarm color {color_label} detected{blink}."))
            else:
                results.append(VerifyResult(f"{list_type}/color", "FAIL", f"Alarm color {color_label} NOT detected."))
        else:
            if self._color_present(img, target_rgb, tolerance=35):
                results.append(VerifyResult(f"{list_type}/color", "PASS", f"Alarm color {color_label} detected."))
            else:
                results.append(VerifyResult(f"{list_type}/color", "FAIL", f"Alarm color {color_label} NOT detected."))

        # ── Save screenshot ───────────────────────────────────────────────────
        overall_pass = not any(r.status == "FAIL" for r in results)
        status_str   = "PASS" if overall_pass else "FAIL"
        fname        = f"{point_idx:04d}_{point_id}_{list_type}_{status_str}.png"
        saved_path   = session_dir / fname
        try:
            img.save(str(saved_path))
        except Exception as e:
            logger.warning(f"Could not save {list_type} screenshot: {e}")
            saved_path = ""

        if results:
            results[0] = VerifyResult(results[0].step, results[0].status, results[0].msg, str(saved_path))

        return results
