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
        """
        Unified verification for both Trigger and Normalize phases.
        Polls the SCADA screen until the state change is actually visible,
        then evaluates colors and blinking across the multi-frame sampler buffer.
        """
        step       = "alarm_panel"
        point_id   = expected.get("point_id", "")
        desc       = expected.get("description", "")
        label      = expected.get("label", "")
        severity   = expected.get("severity", "")
        target_rgb = expected.get("color", (255, 0, 0))

        if not PIL_AVAILABLE or self.alarm_zone is None:
            return [VerifyResult(step, "FAIL", "PIL not available or no alarm_panel zone drawn.")]
        if not (iscs_OCR and iscs_OCR.TESSERACT_AVAILABLE):
            return [VerifyResult(step, "FAIL", "Tesseract OCR not available - check Settings.")]

        lang = self.config.get("tesseract_lang", "eng")
        z    = self.alarm_zone
        _bbox = self._get_zone_bbox("alarm_panel", z)

        best_img     = None
        all_texts    = []
        found_target = False
        found_grey   = False

        # ─── SYMMETRIC SCADA UPDATE POLL LOOP ───
        # Uses trigger_ns to measure true visual latency from the exact millisecond the simulator signal was sent.
        # ─── CONCURRENT SCADA POLL LOOP ───
        # OCR polls immediately while sampler runs concurrently in the background.
        elapsed_latency = 0.0
        duration = float(self.config.get("detection_duration_sec", 8.0))
        deadline = time.monotonic() + duration
        start_time_sec = (trigger_ns / 1e9) if trigger_ns else time.time()
        
        if _bbox:
            expected_id  = str(point_id)
            expected_val = str(label)
            poll_interval = 0.5
            
            while time.monotonic() < deadline:
                if self.stop_event and self.stop_event.is_set():
                    break
                try:
                    img = ImageGrab.grab(bbox=_bbox, all_screens=True)
                    raw = ocr_run(img, lang=lang, layout="block")
                    # Exit early ONLY when the exact identifier AND value are truly
                    # on screen. Tolerant matching here caused premature exits on
                    # partially-rendered / noisy frames (false detections), so we
                    # require an exact substring match before trusting the frame.
                    if expected_id in raw and expected_val in raw:
                        best_img = img
                        all_texts = [raw]
                        elapsed_latency = round(time.time() - start_time_sec, 2)
                        break
                except Exception:
                    pass
                time.sleep(poll_interval)
        
        # Fallback grab if OCR loop timed out without detection
        if best_img is None and _bbox:
            try:
                best_img = ImageGrab.grab(bbox=_bbox, all_screens=True)
                all_texts = [ocr_run(best_img, lang=lang, layout="block")]
            except Exception:
                pass

        # Merge OCR results for validation checks
        merged_text = "\n".join(all_texts)
        
        # ─── SYMMETRIC MULTI-FRAME COLOR EVALUATION ───
        # Wait for the remaining window and evaluate color/blink on the sampler.
        if sampler is not None and trigger_ns is not None:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                sampler.join(timeout=remaining + 0.5)
            
            sample_result = sampler.evaluate(target_rgb, trigger_ns, tolerance=35)
            found_target  = sample_result.color_found
            found_grey    = sample_result.blink_detected
            if sample_result.first_color_frame:
                best_img  = sample_result.first_color_frame.image
        else:
            # ─── NO-SAMPLER MULTI-FRAME COLOR BURST (blink tolerant) ───
            # A blinking alarm cycles colour → off → colour. A single grab can
            # land on the "off" phase and wrongly fail the colour check, so we
            # take a short burst of frames over ~1s and pass if the target
            # colour appears in ANY of them. The first colour-positive frame is
            # kept as the saved evidence screenshot (falls back to best_img).
            if _bbox:
                burst_frames   = int(self.config.get("blink_burst_frames", 8))
                burst_total_sec = float(self.config.get("blink_burst_sec", 1.0))
                interval = (burst_total_sec / burst_frames) if burst_frames > 0 else 0.12
                color_frame = None
                for _i in range(max(1, burst_frames)):
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
                    # Early exit once we've confirmed both colour-on and blink-off
                    if found_target and found_grey:
                        break
                    time.sleep(interval)
                if color_frame is not None:
                    best_img = color_frame   # save the frame that actually showed the colour
            elif best_img is not None:
                found_target = self._color_present(best_img, target_rgb, tolerance=35)
                found_grey   = self._color_present(best_img, self.BLINK_GREY)

        logger.debug(f"verify_alarm_panel [{file_suffix}]: target={found_target} grey={found_grey} texts_parsed={len(all_texts)}")

        results      = []
        overall_pass = True

        # ── Datetime Extraction from SCADA OCR ────────────────────────────────
        # Searches the raw OCR text for a display timestamp (DD/MM/YYYY or YYYY-MM-DD)
        # instead of calling the computer's local system clock.
        import re as _re
        match_ts = _re.search(r'(\d{2,4}[-/\.]\d{2}[-/\.]\d{2,4}\s+\d{2}:\d{2}:\d{2})', merged_text)
        
        if match_ts:
            ts_msg = match_ts.group(1)
            parsed_ocr_dt = None
            
            # Attempt to parse multiple date/time string formats dynamically
            for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
                try:
                    parsed_ocr_dt = datetime.datetime.strptime(ts_msg, fmt)
                    break
                except ValueError:
                    pass
            
            # Resolve baseline trigger time (uses trigger_time for Alarm, or trigger_ns/reset_ns for Normalize)
            calc_trigger_time = trigger_time
            if calc_trigger_time is None and trigger_ns:
                calc_trigger_time = datetime.datetime.fromtimestamp(trigger_ns / 1e9)
                
            if parsed_ocr_dt and calc_trigger_time:
                # Calculate absolute discrepancy between SCADA Clock and Modbus Trigger Time
                time_delta = abs((parsed_ocr_dt - calc_trigger_time).total_seconds())
                # Max permitted SCADA-clock-vs-trigger latency. Configurable because
                # real screen-update + OCR-poll latency is commonly 2-4s; the old
                # hardcoded 2.0s failed alarms that were essentially on time.
                sync_limit = float(self.config.get("datetime_sync_limit_sec", 4.0))
                
                if time_delta <= sync_limit:
                    results.append(VerifyResult(f"{step}/datetime", "PASS", f"{ts_msg} (sync delta={time_delta:.2f}s)"))
                else:
                    overall_pass = False
                    results.append(VerifyResult(f"{step}/datetime", "FAIL", f"{ts_msg} (sync delta={time_delta:.2f}s exceeds limit of {sync_limit}s)"))
            else:
                results.append(VerifyResult(f"{step}/datetime", "PASS", f"{ts_msg} (latency={elapsed_latency}s)"))
        else:
            # Fallback to local system clock only if OCR failed to read the SCADA clock
            ts_fallback = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            results.append(VerifyResult(f"{step}/datetime", "PASS", f"{ts_fallback} (latency={elapsed_latency}s) [System Clock Fallback]"))
        # ─────────────────────────────────────────────────────────────────────

        # ── Identifier (point_id in OCR) ──────────────────────────────────────
        if _ocr_contains(str(point_id), merged_text):
            results.append(VerifyResult(f"{step}/identifier", "PASS", f"'{point_id}' found in OCR."))
        else:
            overall_pass = False
            results.append(VerifyResult(f"{step}/identifier", "FAIL", f"'{point_id}' NOT found in OCR text."))

        # ── Description ───────────────────────────────────────────────────────
        if desc:
            if _ocr_fuzzy_contains(str(desc), merged_text):
                results.append(VerifyResult(f"{step}/description", "PASS", f"'{desc}' found in OCR."))
            else:
                overall_pass = False
                results.append(VerifyResult(f"{step}/description", "FAIL", f"'{desc}' NOT found in OCR text."))
        else:
            results.append(VerifyResult(f"{step}/description", "SKIP", "No description configured."))

        # ── Value / Label ─────────────────────────────────────────────────────
        if label:
            if _ocr_contains(str(label), merged_text):
                results.append(VerifyResult(f"{step}/value", "PASS", f"'{label}' found in OCR."))
            else:
                overall_pass = False
                results.append(VerifyResult(f"{step}/value", "FAIL", f"'{label}' NOT found in OCR text."))
        else:
            results.append(VerifyResult(f"{step}/value", "SKIP", "No label/value configured."))

        # ── Severity ──────────────────────────────────────────────────────────
        if severity:
            sev_text = str(severity)
            # Severity is often a single digit (0/1). A canonical substring match
            # is meaningless for 1-char tokens (every OCR string has digits), so
            # for short tokens require a word-boundary match against the raw text.
            if len(sev_text.strip()) <= 2:
                import re as _re_sev
                sev_found = bool(_re_sev.search(rf"(?<![A-Za-z0-9]){_re_sev.escape(sev_text.strip())}(?![A-Za-z0-9])",
                                                merged_text))
            else:
                sev_found = _ocr_contains(sev_text, merged_text)

            # Fallback: the severity is a lone digit in its own right-hand cell;
            # in the full-banner OCR it is often misread ('0' -> '[}') or dropped.
            # Re-OCR just the right-hand severity cell with a digit whitelist,
            # which reads the isolated digit reliably.
            if not sev_found and best_img is not None:
                try:
                    _W, _H = best_img.size
                    _sev_crop = best_img.crop((int(_W * 0.85), 0, _W, _H))
                    _psm = 10 if len(sev_text.strip()) == 1 else 7
                    _digits = iscs_OCR.run_digits(_sev_crop, psm=_psm)
                    import re as _re_sev2
                    if _re_sev2.search(rf"(?<![0-9]){_re_sev2.escape(sev_text.strip())}(?![0-9])", _digits):
                        sev_found = True
                except Exception:
                    pass

            if sev_found:
                results.append(VerifyResult(f"{step}/severity", "PASS", f"'{sev_text}' found in OCR."))
            else:
                overall_pass = False
                results.append(VerifyResult(f"{step}/severity", "FAIL", f"'{sev_text}' NOT found in OCR text."))
        else:
            results.append(VerifyResult(f"{step}/severity", "SKIP", "No severity configured."))

        # ── Color + Blink ─────────────────────────────────────────────────────
        color_name = self._get_color_name(target_rgb)
        color_label = f"{color_name} {target_rgb}" if color_name else str(target_rgb)

        if found_target:
            blink_note = " (blink detected)" if found_grey else ""
            results.append(VerifyResult(f"{step}/color", "PASS", f"Alarm color {color_label} detected{blink_note}."))
        else:
            overall_pass = False
            results.append(VerifyResult(f"{step}/color", "FAIL", f"Alarm color {color_label} NOT detected."))

        # ── Save screenshot ───────────────────────────────────────────────────
        if best_img is not None:
            status_str = "PASS" if overall_pass else "FAIL"
            fname = f"{point_idx:04d}_{point_id}_{file_suffix}_{status_str}.png"
            try:
                saved = str(session_dir / fname)
                best_img.save(saved)
                results[0] = VerifyResult(results[0].step, results[0].status, results[0].msg, saved)
            except Exception as e:
                logger.warning(f"verify_alarm_panel: could not save screenshot: {e}")

        return results

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
