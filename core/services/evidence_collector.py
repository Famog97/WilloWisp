"""
core/services/evidence_collector.py  (M2.6 — relocated from baru.FailureEvidenceCollector)

Gathers failure diagnostics (full screenshot, cropped OCR zones, expected-vs-actual,
Modbus/metadata, timestamp delta, coordinates) into a per-point failure folder. The
``verifier`` is passed in (used for zones/bbox/OCR), so this has no engine dependency.
Rewired off baru globals: PIL via a local guarded import, its own logger. baru
re-exports ``FailureEvidenceCollector`` as a shim. No tkinter/pyautogui import.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
from pathlib import Path

try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except Exception:
    ImageGrab = None
    PIL_AVAILABLE = False

logger = logging.getLogger("AutoClick")


class FailureEvidenceCollector:
    """
    Automated diagnostics collection utility for test failures.
    Generates a dedicated failure directory containing precise screenshots,
    cropped OCR region captures, text outputs, configuration parameters, and metadata.
    """
    @staticmethod
    def collect(session_dir: Path, point_idx: int, pt: dict, point_results: list, 
                verifier, trigger_time, expected_alarm: dict, config: dict, **kwargs) -> dict:
        import shutil
        from PIL import Image as PILImage
        
        point_id = pt.get("point_id", f"unknown_pt_{point_idx}")
        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Format a safe folder name for filesystem structures
        safe_point_id = re.sub(r'[^\w\-]', '_', str(point_id))
        fail_dir = session_dir / "failures" / f"{point_idx:04d}_{safe_point_id}_{ts_str}"
        fail_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"FailureEvidenceCollector: Writing failure diagnostics folder to {fail_dir}")

        # 1. Automatically capture full-screen screenshot
        full_ss_path = fail_dir / "full_screenshot_failure.png"
        rel_full_ss = ""
        if PIL_AVAILABLE:
            try:
                # Use the verifier coordinates context instead of global __main__ references
                bbox = verifier.bbox if (verifier and hasattr(verifier, 'bbox')) else None
                img_full = ImageGrab.grab(bbox=bbox, all_screens=True) if bbox else ImageGrab.grab(all_screens=True)
                img_full.save(str(full_ss_path))
                rel_full_ss = str(full_ss_path.relative_to(session_dir).as_posix())
            except Exception as e:
                logger.warning(f"FailureEvidenceCollector: Full screen capture failed: {e}")

        # 2. Save cropped OCR region images & 3. Save OCR extracted text
        cropped_zones_data = {}
        diagnostic_slots = [
            ("alarm_panel_trigger",   "alarm_panel",     [f"{point_idx:04d}_{point_id}_alarm_panel_trigger_*.png"]),
            ("alarm_panel_normalize", "alarm_panel",     [f"{point_idx:04d}_{point_id}_alarm_panel_normalize_*.png"]),
            ("alarm_list",           "alarm_list",       [f"{point_idx:04d}_{point_id}_alarm_list_trigger_*.png", f"{point_idx:04d}_{point_id}_alarm_list_*.png"]),
            ("event_list",           "event_list",       [f"{point_idx:04d}_{point_id}_event_list_trigger_*.png", f"{point_idx:04d}_{point_id}_event_list_*.png"]),
            ("equipment",            "equipment_page",   [f"{point_idx:04d}_{point_id}_inspector_*.png"])
        ]
        
        for slot_key, zone_name, patterns in diagnostic_slots:
            z = verifier.zones.get(zone_name) if verifier else None
            found_img_path = None
            
            for pattern in patterns:
                matches = list(session_dir.glob(pattern))
                if matches:
                    found_img_path = matches[0]
                    break
            
            if found_img_path and os.path.exists(found_img_path):
                try:
                    crop_path = fail_dir / f"crop_zone_{slot_key}.png"
                    shutil.copy2(found_img_path, crop_path)
                    rel_crop = str(crop_path.relative_to(session_dir).as_posix())

                    img_to_ocr = PILImage.open(str(crop_path))
                    raw_text = verifier._ocr_image(img_to_ocr) if verifier else ""

                    cropped_zones_data[slot_key] = {
                        "image": rel_crop,
                        "image_abs": str(crop_path.resolve()),
                        "text": raw_text.strip() if raw_text.strip() else "(Blank / No text detected)"
                    }
                except Exception as e:
                    logger.warning(f"FailureEvidenceCollector: Failed to capture slot {slot_key}: {e}")
            elif z is not None:
                try:
                    z_img = ImageGrab.grab(bbox=(z.x1, z.y1, z.x2, z.y2), all_screens=True)
                    crop_path = fail_dir / f"crop_zone_{slot_key}.png"
                    z_img.save(str(crop_path))
                    rel_crop = str(crop_path.relative_to(session_dir).as_posix())
                    raw_text = verifier._ocr_image(z_img) if verifier else ""
                    
                    cropped_zones_data[slot_key] = {
                        "image": rel_crop,
                        "image_abs": str(crop_path.resolve()),
                        "text": raw_text.strip() if raw_text.strip() else "(Blank / No text detected)"
                    }
                except Exception as e:
                    logger.warning(f"FailureEvidenceCollector: Fallback capture failed for slot {slot_key}: {e}")

        # 4. Save Pass image (visual baseline state if steps passed successfully)
        reference_passes = []
        for r in point_results:
            if r.status == "PASS" and r.screenshot and os.path.exists(r.screenshot):
                try:
                    ref_name = f"reference_pass_{Path(r.screenshot).name}"
                    shutil.copy2(r.screenshot, fail_dir / ref_name)
                    reference_passes.append(str((fail_dir / ref_name).relative_to(session_dir).as_posix()))
                except Exception as e:
                    logger.warning(f"FailureEvidenceCollector: Copy baseline pass image failed: {e}")

        # 5. Save expected vs actual comparison
        comparison = {
            "point_id": point_id,
            "expected": {
                "label_value": expected_alarm.get("label", ""),
                "severity": expected_alarm.get("severity", ""),
                "color": expected_alarm.get("color", ""),
                "is_alarm": expected_alarm.get("is_alarm", True),
                "description": expected_alarm.get("description", "")
            },
            "actual_checks": [
                {
                    "step": r.step,
                    "status": r.status,
                    "message": r.msg,
                    "screenshot_reference": Path(r.screenshot).name if r.screenshot else ""
                } for r in point_results
            ]
        }
        try:
            with open(fail_dir / "expected_vs_actual_comparison.json", "w", encoding="utf-8") as f:
                json.dump(comparison, f, indent=2)
        except Exception as e:
            logger.warning(f"FailureEvidenceCollector: Comparison save failed: {e}")

        # 6. Save alarm metadata
        metadata = {
            "point_id": pt.get("point_id", ""),
            "equipment_desc": pt.get("equipment_desc", ""),
            "location": pt.get("location", ""),
            "attribute_desc": pt.get("attribute_desc", ""),
            "station_code": pt.get("station_code", ""),
            "data_type": pt.get("data_type", ""),
            "severity_raw": pt.get("severity", ""),
            "states_table": pt.get("states", {})
        }
        try:
            with open(fail_dir / "alarm_metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            logger.warning(f"FailureEvidenceCollector: Metadata save failed: {e}")

        # Parse visual clock timestamps from the OCR messages (Supports slashes, dashes, and dots)
        dt_msg = next((r.msg for r in point_results if r.step == "alarm_panel/datetime"), "")
        match = re.search(r'(\d{2,4}[-/\.]\d{2}[-/\.]\d{2,4}\s+\d{2}:\d{2}:\d{2})', dt_msg)
        ocr_timestamp_str = match.group(1) if match else "N/A"
        
        norm_dt_msg = next((r.msg for r in point_results if r.step == "normalize/datetime"), "")
        match_norm = re.search(r'(\d{2,4}[-/\.]\d{2}[-/\.]\d{2,4}\s+\d{2}:\d{2}:\d{2})', norm_dt_msg)
        norm_ocr_timestamp_str = match_norm.group(1) if match_norm else "N/A"

        # 7. Save Modbus trigger information with nested trigger detail blocks
        payload = pt.get("payload", {})
        reset_time = kwargs.get("reset_time")
        expected_norm_dict = kwargs.get("expected_norm", {})
        
        modbus_info = {
            "protocol": pt.get("protocol", "MODBUS"),
            "device_address_unit_id": payload.get("device_address", payload.get("unit_id", 1)),
            "function_code": payload.get("fc", 3),
            "register_address": payload.get("reg", 0),
            "bit_offset": payload.get("bit", 0),
            "trigger_value": expected_alarm.get("label", ""),
            "raw_trigger_value": 1,
            "alarm_trigger": {
                "trigger_time": trigger_time.strftime('%Y-%m-%d %H:%M:%S') if trigger_time else 'N/A',
                "scada_clock_ocr": ocr_timestamp_str,
                "trigger_value": expected_alarm.get("label", "")
            },
            "normalize_trigger": {
                "trigger_time": reset_time.strftime('%Y-%m-%d %H:%M:%S') if reset_time else 'N/A',
                "scada_clock_ocr": norm_ocr_timestamp_str,
                "trigger_value": expected_norm_dict.get("label", "NORMAL") if expected_norm_dict else 'NORMAL'
            }
        }

        # 8. Save timestamp delta
        delta_seconds = None
        delta_info = {}
        if trigger_time:
            now = datetime.datetime.now()
            delta_seconds = round((now - trigger_time).total_seconds(), 2)
            
            m = re.search(r'latency=([\d\.]+)', dt_msg)
            if m:
                delta_seconds = float(m.group(1))
            else:
                delta_seconds = round((datetime.datetime.now() - trigger_time).total_seconds(), 2)
            
            delta_info = {
                "trigger_timestamp": trigger_time.strftime('%Y-%m-%d %H:%M:%S'),
                "ocr_detected_timestamp": ocr_timestamp_str,
                "calculated_delta_seconds": delta_seconds
            }
            try:
                with open(fail_dir / "timestamp_delta.json", "w", encoding="utf-8") as f:
                    json.dump(delta_info, f, indent=2)
            except Exception as e:
                logger.warning(f"FailureEvidenceCollector: Timestamp delta save failed: {e}")

        # 9. Save active screen coordinates
        zones_dict = verifier.zones if verifier else {}
        coordinates_info = {
            "active_monitor": {
                "bounds": [verifier.bbox] if verifier else None
            },
            "zones": {
                z_name: {
                    "x1": z.x1, "y1": z.y1, "x2": z.x2, "y2": z.y2,
                    "width": z.width, "height": z.height, "type": z.zone_type
                } for z_name, z in zones_dict.items() if z is not None
            }
        }
        try:
            with open(fail_dir / "active_screen_coordinates.json", "w", encoding="utf-8") as f:
                json.dump(coordinates_info, f, indent=2)
        except Exception as e:
            logger.warning(f"FailureEvidenceCollector: Active screen coordinates save failed: {e}")

        # Return diagnostics object mapped for HTML reporting
        return {
            "failure_folder": str(fail_dir.relative_to(session_dir).as_posix()),
            "full_screenshot": rel_full_ss,
            "cropped_zones": cropped_zones_data,
            "modbus_info": modbus_info,
            "metadata": metadata,
            "timestamp_delta": delta_info,
            "reference_passes": reference_passes
        }
