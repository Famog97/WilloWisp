"""
core/services/run_coordinator.py  (M3.4)

Headless run orchestration in pure core/: SuiteRunner (the multi-card/rerun suite
orchestrator) and generate_points (grid/sequence click-point generator), relocated
from baru. No UI/OS imports — mouse/keyboard goes through the injected
InputControlPort; PIL / pandas / FrameSampler / lifecycle events are guarded optional
deps; output paths come from core.services.config.get_log_dir(). baru re-exports
SuiteRunner / generate_points / the run logger as shims.
"""
from __future__ import annotations

import copy
import datetime
import json
import logging
import re
import threading
import time
from logging.handlers import RotatingFileHandler as _RotatingFileHandler
from pathlib import Path

logger = logging.getLogger("AutoClick")

# ── core collaborators (all headless) ──────────────────────────────────────────
from core.domain.scenario import Monitor, Scenario
from core.domain.results import VerifyResult
from core.services.verifier import ISCSVerifier
from core.services.engine import build_runner_from_scenario
from core.services.report_service import ReportManager
from core.services.evidence_collector import FailureEvidenceCollector
from core.services.expected_state import _get_state_indices, build_expected
from core.services.config import get_log_dir

# ── guarded optional deps (behind flags, exactly as baru did) ──────────────────
try:
    from PIL import ImageGrab, ImageDraw
    PIL_AVAILABLE = True
except Exception:
    ImageGrab = ImageDraw = None
    PIL_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    pd = None
    PANDAS_AVAILABLE = False

try:
    from iscs_Sampler_Anchor import FrameSampler
    UPGRADES_AVAILABLE = True
except Exception:
    FrameSampler = None
    UPGRADES_AVAILABLE = False

try:
    from iscs_core import (bus as CORE_BUS, SuiteStarted, SuiteCompleted,
                           CardStarted, CardCompleted)
    _CORE_EVENTS_OK = True
except Exception:
    CORE_BUS = None
    SuiteStarted = SuiteCompleted = CardStarted = CardCompleted = None
    _CORE_EVENTS_OK = False

# The engine lives in core (always available) and all input goes through the
# InputControlPort, so these former baru capability flags are constant here.
WORKFLOW_AVAILABLE = True
PYAUTOGUI_AVAILABLE = True


# ── Test run log — written per suite run into suite folder, rotating 10 x 100MB
# SuiteRunner calls _init_test_run_log(suite_dir) at start of each run.
# Separate logger so it never mixes with app_debug.
test_run_logger = logging.getLogger("test_run")
test_run_logger.setLevel(logging.INFO)
test_run_logger.propagate = False   # don't bleed into app_debug

def init_test_run_log(suite_dir: pathlib.Path):
    """
    Set up the rotating test_run.log inside the suite folder.
    Called once at the start of each suite run.
    Removes any previous handler so each run gets its own log.
    """
    for h in test_run_logger.handlers[:]:
        test_run_logger.removeHandler(h)
        h.close()
    handler = _RotatingFileHandler(
        suite_dir / "test_run.log",
        maxBytes    = 100 * 1024 * 1024,   # 100 MB per file
        backupCount = 9,                    # 10 files max
        encoding    = "utf-8"
    )
    handler.setFormatter(logging.Formatter('%(asctime)s  %(message)s'))
    test_run_logger.addHandler(handler)


def generate_points(mode, monitor: Monitor, spacing: int, zones: list):
    valid, all_pts = [], []
    if mode == "iscs": 
        return valid, all_pts
        
    if mode == "grid":
        has_include = any(z.zone_type == "include" for z in zones)
        for y in range(monitor.y + spacing, monitor.y + monitor.height, spacing):
            for x in range(monitor.x + spacing, monitor.x + monitor.width, spacing):
                all_pts.append((x, y))
                if any(z.contains(x, y) for z in zones if z.zone_type == "exclude"): continue
                if has_include and not any(z.contains(x, y) for z in zones if z.zone_type == "include"): continue
                valid.append({"x": x, "y": y, "label": "grid_pt", "zone": None})
    elif mode == "sequence":
        for i, z in enumerate([z for z in zones if z.zone_type == "target"]):
            valid.append({"x": z.cx, "y": z.cy, "label": f"Target_{i+1}", "zone": z})
            all_pts.append((z.cx, z.cy))
    return valid, all_pts


class SuiteRunner(threading.Thread):
    def __init__(self, scenarios, monitors, protocols, config, on_scenario_start, on_progress, on_paused, on_pass_done, on_suite_done, on_log, suite_title="", rerun_failed_count=0, on_rec_start=None, on_rec_stop=None, on_rec_update=None, event_bus=None, input_control=None, on_proto_status=None):
        super().__init__(daemon=True)
        self.scenarios, self.monitors, self.protocols = scenarios, monitors, protocols
        self.rerun_failed_count = rerun_failed_count  # -1 = till pass, 0 = disabled, N = N times
        self.config = config
        self.suite_title = suite_title.strip()
        self.on_scenario_start, self.on_progress, self.on_paused = on_scenario_start, on_progress, on_paused
        self.on_pass_done, self.on_suite_done, self.on_log = on_pass_done, on_suite_done, on_log
        self._stop_event = threading.Event()
        self._pause_event = threading.Event(); self._pause_event.set()
        self.results_all = []
        self.active_samplers = []  # Tracks active samplers for early exit
        self.current_rerun_attempt = 0
        # ── Recorder callbacks (all optional / None if recording disabled) ──
        self._on_rec_start  = on_rec_start   # (sc, evidence_dir) -> Recorder | None
        self._on_rec_stop   = on_rec_stop    # (rec, card_name)
        self._on_rec_update = on_rec_update  # (rec, point_id, equip_desc, attr_desc)
        self._active_rec    = None           # currently running Recorder (or None)
        # Lifecycle event bus (FR-28). Additive: events are published alongside the
        # existing recorder callbacks / report call; nothing depends on a subscriber.
        self.event_bus = event_bus if event_bus is not None else CORE_BUS
        # M3.4: mouse/keyboard goes through the InputControlPort (the only place
        # pyautogui lives), so SuiteRunner carries no OS-automation import itself.
        if input_control is None:
            from adapters.driven.input.pyautogui_input import PyAutoGuiInput
            input_control = PyAutoGuiInput()
        self._input = input_control
        # M3.4: protocol-wait status goes through an injected callback instead of
        # reaching into __main__.app.hud — keeps SuiteRunner free of the live UI.
        # Signature: on_proto_status(state: "waiting"|"online", done, total, msg).
        self._on_proto_status = on_proto_status

    def _emit(self, event):
        """Publish a lifecycle event if a bus + event class are present. Never
        raises — EventBus.publish isolates subscriber errors (NFR-11)."""
        bus = getattr(self, "event_bus", None)
        if bus is not None and event is not None:
            try:
                bus.publish(event)
            except Exception:
                pass

    # ── Recorder lifecycle via events (B3 / P2.3) ────────────────────────────
    def _on_event_card_started(self, event):
        """Start the per-card recorder when a CardStarted (carrying scenario +
        evidence_dir) arrives. Sets self._active_rec so per-point overlay updates
        keep working, and marks the event handled so run() won't also start one."""
        sc     = getattr(event, "scenario", None)
        ev_dir = getattr(event, "evidence_dir", None)
        if sc is None or ev_dir is None or not self._on_rec_start:
            return
        event.recorder_handled = True
        try:
            self._active_rec = self._on_rec_start(sc, ev_dir)
        except Exception as _re:
            self.on_log(f"⚠ Recorder start error: {_re}")
            self._active_rec = None

    def _on_event_card_completed(self, event):
        """Stop the per-card recorder on CardCompleted."""
        if not self._on_rec_stop:
            return
        event.recorder_handled = True
        rec = getattr(self, "_active_rec", None)
        if rec is not None:
            try:
                self._on_rec_stop(rec, getattr(event, "card_name", ""))
            except Exception as _re:
                self.on_log(f"⚠ Recorder stop error: {_re}")
        self._active_rec = None

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()
        # Abort all running samplers instantly
        for s in list(self.active_samplers):
            try: s.stop()
            except: pass
    def pause(self, r="manual"): self._pause_reason = r; self._pause_event.clear()
    def resume(self): self._pause_reason = ""; self._pause_event.set()
    @property
    def is_paused(self): return not self._pause_event.is_set()

    def _sleep(self, seconds: float, granularity: float = 0.1):
        """Interruptible sleep — returns early if stop is requested."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return
            time.sleep(min(granularity, deadline - time.monotonic()))

    def _take_screenshot(self, sc_dir, idx, prefix, mon, pt_data=None, mode="sequence"):
        if not PIL_AVAILABLE: return ""
        ss_name = f"{idx:04d}_{prefix}.png"
        ss_path = sc_dir / ss_name

        if mode == "sequence" and pt_data and pt_data.get("zone"):
            z = pt_data["zone"]
            pad = self.config.get("wide_crop_pad", 200)   # M3.4: was module global WIDE_CROP_PAD
            x1 = max(mon.x, z.x1 - pad)
            y1 = max(mon.y, z.y1 - pad)
            x2 = min(mon.x + mon.width, z.x2 + pad)
            y2 = min(mon.y + mon.height, z.y2 + pad)
            bbox = (x1, y1, x2, y2)
        else:
            bbox = (mon.x, mon.y, mon.x + mon.width, mon.y + mon.height)

        try:
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
            if pt_data:
                draw = ImageDraw.Draw(img)
                lx = pt_data["x"] - bbox[0]
                ly = pt_data["y"] - bbox[1]
                r = 8
                draw.ellipse((lx - r, ly - r, lx + r, ly + r), outline="#FF1744", width=3)
                draw.line((lx, ly - r - 6, lx, ly + r + 6), fill="#FF1744", width=3)
                draw.line((lx - r - 6, ly, lx + r + 6, ly), fill="#FF1744", width=3)
            img.save(str(ss_path))
            return str(ss_path)
        except Exception as ex:
            self.on_log(f"Suite screenshot error: {ex}")
            return ""

    def run(self):
        try:
            ts        = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            prefix    = f"{self.suite_title}_" if self.suite_title else ""
            safe_prefix = re.sub(r'[^\w\-]', '_', prefix)
            suite_dir = get_log_dir() / f"{safe_prefix}suite_{ts}"
            suite_dir.mkdir(parents=True, exist_ok=True)
            init_test_run_log(suite_dir)
            test_run_logger.info(f"Suite started: {suite_dir.name}")

            # Wrapper for logging
            _orig_on_log = self.on_log
            def _on_log_tee(msg):
                test_run_logger.info(msg)
                _orig_on_log(msg)
            self.on_log = _on_log_tee

            suite_results_accum = []  # Master accumulator for the consolidated report
            suite_start_time = datetime.datetime.now()
            self._emit(SuiteStarted(title=self.suite_title or "ISCS Test Suite Run") if _CORE_EVENTS_OK else None)

            # B3: drive the recorder via Card events. Subscribe this run's recorder
            # handlers to its bus; unsubscribed in finally so they never leak across
            # runs. Only when recording callbacks are present.
            self._rec_unsubs = []
            if _CORE_EVENTS_OK and self.event_bus is not None and self._on_rec_start:
                self._rec_unsubs.append(self.event_bus.subscribe(CardStarted, self._on_event_card_started))
                self._rec_unsubs.append(self.event_bus.subscribe(CardCompleted, self._on_event_card_completed))

            for sc_idx, sc in enumerate(self.scenarios):
                if self._stop_event.is_set(): break
                safe_card_name = re.sub(r'[^\w\-]', '_', sc.name)
                card_loop   = getattr(sc, "card_loop", 1)
                card_infinite = getattr(sc, "card_infinite", False)
                card_iter = 0

                while not self._stop_event.is_set():
                    card_iter += 1
                    if not card_infinite and card_iter > card_loop:
                        break
                    
                    pass_dir = suite_dir / f"loop_{card_iter:04d}"
                    pass_dir.mkdir(exist_ok=True)
                    
                    scenario_folder_name = f"{sc_idx+1}_{safe_card_name}"
                    self.on_scenario_start(card_iter, -1 if card_infinite else card_loop, sc_idx+1, len(self.scenarios), sc)
                    self.current_rerun_attempt = 0

                    # Start recorder — event-driven (CardStarted) if a subscriber
                    # handles it, else inline (legacy) so recording is never lost.
                    _card_ev_dir = pass_dir / scenario_folder_name
                    _card_ev_dir.mkdir(parents=True, exist_ok=True)
                    _card_rec = None
                    _cs_evt = None
                    if _CORE_EVENTS_OK:
                        _cs_evt = CardStarted(card_name=sc.name, loop=card_iter,
                                              scenario_index=sc_idx + 1,
                                              total_scenarios=len(self.scenarios),
                                              scenario=sc, evidence_dir=_card_ev_dir)
                        self._emit(_cs_evt)
                    if _cs_evt is not None and getattr(_cs_evt, "recorder_handled", False):
                        _card_rec = self._active_rec        # started by the subscriber
                    else:
                        if self._on_rec_start:
                            try:
                                _card_rec = self._on_rec_start(sc, _card_ev_dir)
                            except Exception as _re:
                                self.on_log(f"⚠ Recorder start error: {_re}")
                        self._active_rec = _card_rec
                    
                    # Run Scenario
                    sc_results_accum = self._run_scenario(sc, _card_ev_dir, card_iter, sc_idx)
                    
                    # Handle reruns
                    if self.rerun_failed_count != 0 and not self._stop_event.is_set() and sc.mode == "iscs":
                        failed_ids = self._collect_failed_point_ids(sc, sc_results_accum)
                        rerun_attempt = 0
                        while not self._stop_event.is_set() and failed_ids:
                            if self.rerun_failed_count > 0 and rerun_attempt >= self.rerun_failed_count:
                                break
                            
                            rerun_attempt += 1
                            self.current_rerun_attempt = rerun_attempt
                            _n_failed = len(failed_ids)
                            self.on_log(f"↺ Rerun attempt {rerun_attempt} — {_n_failed} failed point(s) for '{sc.name}'")
                            self.on_progress(card_iter, -1 if card_infinite else card_loop, sc_idx + 1, len(self.scenarios), -rerun_attempt, _n_failed, f"↺ Rerun #{rerun_attempt}", "")
                            
                            rerun_dir = pass_dir / f"{sc_idx+1}_{safe_card_name}_rerun{rerun_attempt:02d}"
                            
                            sc_rerun = Scenario.__new__(Scenario)
                            sc_rerun.__dict__.update(copy.deepcopy(sc.__dict__))
                            sc_rerun.iscs_points = [p for p in sc.iscs_points if p.get("point_id") in failed_ids]
                            
                            rerun_results = self._run_scenario(sc_rerun, rerun_dir, card_iter, sc_idx)
                            for rec in rerun_results:
                                rec["rerun_attempt"] = rerun_attempt
                                
                            sc_results_accum.extend(rerun_results)
                            failed_ids = self._collect_failed_point_ids(sc, sc_results_accum)
                    
                    # Stop recorder — event-driven (CardCompleted) if handled, else inline.
                    _cc_evt = None
                    if _CORE_EVENTS_OK:
                        _cc_evt = CardCompleted(card_name=sc.name, loop=card_iter)
                        self._emit(_cc_evt)
                    if not (_cc_evt is not None and getattr(_cc_evt, "recorder_handled", False)):
                        if _card_rec is not None and self._on_rec_stop:
                            try:
                                self._on_rec_stop(_card_rec, sc.name)
                            except Exception as _re:
                                self.on_log(f"⚠ Recorder stop error: {_re}")
                        self._active_rec = None

                    # Assign loop/scenario metadata to result objects
                    for item in sc_results_accum:
                        item["loop_num"] = card_iter
                        item["scenario_name"] = sc.name
                        item["scenario_idx"] = sc_idx + 1

                    suite_results_accum.extend(sc_results_accum)

            # Suite finished → emit SuiteCompleted carrying the report payload. The
            # report subsystem generates HTML/Excel as a SUBSCRIBER (P2.3), so the
            # runner no longer calls ReportManager directly.
            suite_end_time = datetime.datetime.now()
            title_lbl = self.suite_title if self.suite_title else "ISCS Test Suite Run"
            _report_handled = False
            if _CORE_EVENTS_OK and self.event_bus is not None:
                _passed = sum(1 for r in suite_results_accum if r.get("overall") == "PASS")
                _evt = SuiteCompleted(
                    title=title_lbl,
                    passed=_passed, failed=len(suite_results_accum) - _passed,
                    results=suite_results_accum, output_dir=suite_dir,
                    start_time=suite_start_time, end_time=suite_end_time,
                    on_log=self.on_log,
                )
                try:
                    self.event_bus.publish(_evt)
                except Exception:
                    pass
                _report_handled = bool(getattr(_evt, "report_generated", False))

            # Safety net: if NO subscriber generated the report (events off, or no
            # report subscriber wired), generate it directly so reports are never
            # lost. report_generated precisely tracks whether the report ran, so
            # other (e.g. dashboard) subscribers don't suppress this fallback.
            if not _report_handled and suite_results_accum and ReportManager is not None:
                try:
                    ReportManager.generate_reports(
                        suite_results_accum, suite_dir, suite_start_time, suite_end_time, title=title_lbl
                    )
                    self.on_log(f"✅ Consolidated Suite Report generated successfully inside: {suite_dir.name}")
                except Exception as report_ex:
                    self.on_log(f"⚠ Failed to generate consolidated suite report: {report_ex}")
                    logger.error("Suite report compilation error", exc_info=True)

            self.on_suite_done(suite_dir, "", self._stop_event.is_set())
        except Exception as e:
            self.on_log(f"Suite Crash: {e}")
            self.on_suite_done(None, str(e), True)
        finally:
            # B3: always unsubscribe this run's recorder handlers so they never
            # leak onto the shared bus across runs.
            for _unsub in getattr(self, "_rec_unsubs", []):
                try: _unsub()
                except Exception: pass
            self._rec_unsubs = []

    def _run_scenario(self, sc, sc_dir, p_num, s_idx):
        sc_dir.mkdir(exist_ok=True)
        sc_results = []

        # Track scenario execution start
        start_time = datetime.datetime.now()

        if sc.mode == "iscs":
            # ── Build zones_dict (same logic as before — unchanged) ───────────
            zones_dict = {}
            for page_zones in sc.zones_per_page.values():
                for zt, z in page_zones.items():
                    if zt not in zones_dict:
                        zones_dict[zt] = z
            for z in sc.zones:
                if z.zone_type not in zones_dict:
                    zones_dict[z.zone_type] = z
            verifier = ISCSVerifier(zones_dict, self.config, stop_event=self._stop_event)

            # Protocol comes from the card config, not the point
            card_cfg   = getattr(sc, "card_cfg", {})
            proto_cfg  = card_cfg.get("protocol", {})
            proto_type = proto_cfg.get("type", "MODBUS")
            handler    = self.protocols.get_protocol(proto_type)

            if not handler.check_health():
                self.on_log(f"ISCS Engine waiting: Protocol '{proto_type}' starting/offline...")
                if self._on_proto_status:
                    self._on_proto_status("waiting", 0, len(sc.iscs_points), "protocol offline")
                while not handler.check_health():
                    if self._stop_event.is_set(): break
                    self._sleep(0.5)
                if not self._stop_event.is_set():
                    self.on_log(f"Protocol '{proto_type}' is now online! Resuming...")
                    if self._on_proto_status:
                        self._on_proto_status("online", 0, len(sc.iscs_points), f"{proto_type} Connected!")

            # ── PROCEDURE ENGINE ─────────────────────────────────────────────
            # Delegates per-point execution to ProcedureRunner when available.
            # Falls back to the original hardcoded pipeline if iscs_workflow.py
            # is missing, so the app always stays runnable.
            if WORKFLOW_AVAILABLE:
                def _on_progress_wrap(point_id, done, total):
                    card_loop = getattr(sc, "card_loop", 1)
                    self.on_progress(p_num, card_loop, s_idx + 1, len(self.scenarios),
                                     done, total, point_id, "…")
                    
                    # ── Update recorder overlay with current point metadata ──
                    _rec = getattr(self, "_active_rec", None)
                    if _rec is not None and self._on_rec_update:
                        try:
                            # Resolve point metadata matching the keys parsed from your Excel sheet
                            _pt = next(
                                (p for p in sc.iscs_points
                                 if str(p.get("point_id", "")).strip() == str(point_id).strip()),
                                {}
                            )
                            self._on_rec_update(
                                _rec,
                                str(point_id),
                                str(_pt.get("equipment_desc", "")),
                                str(_pt.get("attribute_desc", "")),
                            )
                        except Exception as e:
                            logger.debug(f"Failed to update overlay metadata: {e}")

                runner = build_runner_from_scenario(
                    sc, verifier, handler, self.config,
                    self.on_log, self._stop_event, self._pause_event,
                )
                traces = runner.run_scenario(
                    sc, sc_dir, p_num, s_idx, on_progress=_on_progress_wrap
                )

                # Final PASS/FAIL mirror to the HUD. Use the count of points
                # actually run (len(traces)) rather than len(sc.iscs_points),
                # since deleted IO folders mean fewer points may have run.
                _total_run = len(traces)
                for _done, trace in enumerate(traces, 1):
                    sc_results.extend(trace.flat_records)
                    card_loop = getattr(sc, "card_loop", 1)
                    self.on_progress(p_num, card_loop, s_idx + 1, len(self.scenarios),
                                     _done, _total_run, trace.point_id, trace.overall)

            else:
                # ── FALLBACK: original hardcoded pipeline (preserved verbatim) ─
                self.on_log("WARNING: iscs_workflow not available — using legacy execution pipeline.")
                self._run_scenario_legacy_iscs(
                    sc, sc_dir, p_num, s_idx, sc_results,
                    verifier, handler, card_cfg, zones_dict,
                )

            # ── POST-RUN RAW DATA DUMP ───────────────────────────────────────
            end_time = datetime.datetime.now()

            if PANDAS_AVAILABLE:
                pd.DataFrame(sc_results).to_csv(sc_dir / "Test_Execution_Summary.csv", index=False)
            else:
                with open(sc_dir / "Test_Execution_Summary.json", "w") as f:
                    json.dump(sc_results, f, indent=2)

            if self._stop_event.is_set():
                self.on_log("  Test stopped — raw data saved for completed points.")
                
            # Diagnostics block to confirm sc_results collection is working
            self.on_log(f"[Debug] _run_scenario completed. sc_results count: {len(sc_results)}")
            self.results_all.extend(sc_results)
            self.on_log(f"[Debug] self.results_all total count now: {len(self.results_all)}")
            
            return sc_results
                    
        else:
            mon = Monitor(0, sc.monitor_info['x'], sc.monitor_info['y'], sc.monitor_info['width'], sc.monitor_info['height'])
            pts, _ = generate_points(sc.mode, mon, sc.grid_spacing, sc.zones)
            
            for i, pt in enumerate(pts):
                if self._stop_event.is_set(): break
                
                # Check Pause
                if not self._pause_event.is_set():
                    self.on_paused(getattr(self, '_pause_reason', 'manual'))
                    while not self._pause_event.wait(timeout=0.2):
                        if self._stop_event.is_set(): break
                    if self._stop_event.is_set(): break

                x, y = pt["x"], pt["y"]
                label = pt.get("label", f"pt_{i}")
                result = {"x": x, "y": y, "label": label, "status": "ok", "screenshot": ""}
                
                try:
                    self._input.click(x, y)
                    time.sleep(0.06)

                    # Check Mouse Drift Safety
                    ax, ay = self._input.position()
                    if abs(ax - x) + abs(ay - y) > self.config.get("mouse_drift_px", 15):
                        self.pause("mouse moved")
                        self.on_paused("mouse moved")
                        self._pause_event.wait(timeout=0.2)
                        if self._stop_event.is_set(): break

                    # Capture screenshot after a small delay
                    time.sleep(self.config.get("screenshot_delay", 0.25))
                    result["screenshot"] = self._take_screenshot(sc_dir, i, f"click_{label}", mon, pt, sc.mode)
                except Exception as ex:
                    result["status"] = f"error: {ex}"
                    self.on_log(f"Suite click error: {ex}")

                sc_results.append(result)
                self.on_progress(p_num, self.loop_count, s_idx+1, len(self.scenarios), i+1, len(pts), x, y)
                
                rem = self.config.get("click_delay", 1.5) - self.config.get("screenshot_delay", 0.25) - 0.06
                if rem > 0: time.sleep(rem)
                
            # Write scenario JSON report
            with open(sc_dir / "results.json", "w") as f:
                json.dump(sc_results, f, indent=2)
            self.results_all.extend(sc_results)

    # --- REPLACE SuiteRunner._collect_failed_point_ids WITH THIS ---
    def _collect_failed_point_ids(self, sc, current_results: list) -> set:
        """Collects point IDs that failed on their most recent attempt in this specific card iteration."""
        card_point_ids = {str(p.get("point_id")).strip() for p in sc.iscs_points if p.get("point_id")}
        self.on_log(f"[Debug] Card '{sc.name}' expected point IDs: {list(card_point_ids)}")
        self.on_log(f"[Debug] Scanning {len(current_results)} records from current iteration.")

        latest_status = {}
        for rec in current_results:
            pt_id = str(rec.get("point_id", "")).strip()
            if pt_id and pt_id in card_point_ids:
                status = str(rec.get("overall", "FAIL")).upper()
                latest_status[pt_id] = status

        self.on_log(f"[Debug] Latest resolved states in current iteration: {latest_status}")
        failures = {pt_id for pt_id, status in latest_status.items() if status == "FAIL"}
        self.on_log(f"[Debug] Calculated failure set for rerun targeting: {list(failures)}")
        return failures

    # ──────────────────────────────────────────────────────────────────────────
    # LEGACY FALLBACK — original hardcoded ISCS pipeline (verbatim preservation)
    # Called only when iscs_workflow.py is not available (WORKFLOW_AVAILABLE=False)
    # ──────────────────────────────────────────────────────────────────────────
    def _run_scenario_legacy_iscs(self, sc, sc_dir, p_num, s_idx, sc_results,
                                   verifier, handler, card_cfg, zones_dict):
        """Original hardcoded 7-step ISCS execution pipeline, preserved verbatim
        as a safe fallback when iscs_workflow.py is missing."""
        for i, pt in enumerate(sc.iscs_points):
            if self._stop_event.is_set(): break

            nav      = card_cfg.get("navigation", {})
            def _xy(key): return nav.get(key, {}).get("x", 0), nav.get(key, {}).get("y", 0)
            nav_wait   = self.config.get("nav_wait_sec", 1.0)
            hm_x, hm_y = _xy("home_btn")
            al_x, al_y = _xy("alarm_list_btn")
            ev_x, ev_y = _xy("event_list_btn")
            rc_x, rc_y = _xy("rightclick_row1")
            pg_x, pg_y = _xy("rightclick_page_btn")

            def _click_home():
                if hm_x != 0 and hm_y != 0 and PYAUTOGUI_AVAILABLE:
                    self._input.click(hm_x, hm_y)
                    self._sleep(nav_wait)

            if not self._pause_event.is_set():
                self.on_paused(getattr(self, '_pause_reason', 'manual'))
                while not self._pause_event.wait(timeout=0.2):
                    if self._stop_event.is_set(): break
                if self._stop_event.is_set(): break

            point_id = pt.get("point_id", f"pt_{i}")
            self.on_log(f"[{i+1}/{len(sc.iscs_points)}] Testing: {point_id}")
            self.on_progress(p_num, self.loop_count, s_idx+1, len(self.scenarios),
                             i+1, len(sc.iscs_points), point_id, "…")

            point_results = []
            point_pass    = True

            trigger_idx, reset_idx = _get_state_indices(pt)
            expected_alarm = build_expected(pt, trigger_idx)
            expected_norm  = build_expected(pt, reset_idx)

            alarm_zone = verifier.alarm_zone
            resolved_bbox = (alarm_zone.x1, alarm_zone.y1, alarm_zone.x2, alarm_zone.y2) if alarm_zone else None
            if alarm_zone and verifier.anchor_mgr:
                resolved = verifier.anchor_mgr.resolve("alarm_panel")
                if resolved:
                    resolved_bbox = resolved

            # STEP 1: Trigger (Symmetric Order: Trigger, then Start Sampler)
            trigger_ok = False; sampler = None; trigger_time = None; trigger_ns = None
            try:
                handler.trigger_alarm(pt)
                trigger_time = datetime.datetime.now(); trigger_ns = time.time_ns(); trigger_ok = True
            except Exception as ex:
                point_pass = False
                self.on_log(f"  [x] Trigger failed for {point_id}: {ex}")

            if trigger_ok and not self._stop_event.is_set():
                if UPGRADES_AVAILABLE and resolved_bbox:
                    sampler = FrameSampler(resolved_bbox,
                                           duration_sec=float(self.config.get("detection_duration_sec", 8.0)),
                                           interval_ms=int(self.config.get("sampler_interval_ms", 100)))
                    self.active_samplers.append(sampler)
                    sampler.start()  # No .join() here! Left to run concurrently.

                # STEP 2: Verify alarm panel
                if alarm_zone:
                    self.on_log(f"  Checking TRIGGER state (v{trigger_idx})...")
                    alarm_res = verifier.verify_alarm_panel(
                        expected_alarm, sc_dir, point_idx=i, trigger_time=trigger_time,
                        file_suffix="alarm_panel_trigger", sampler=sampler, trigger_ns=trigger_ns)
                    point_results.extend(alarm_res)
                    if any(r.status == "FAIL" for r in alarm_res): point_pass = False
                else:
                    point_results.append(VerifyResult("alarm_panel", "SKIP", "No alarm_panel zone drawn."))
                    
                # Clean up trigger sampler
                if sampler and sampler in self.active_samplers:
                    if self._stop_event.is_set():
                        sampler.stop()
                    sampler.join(timeout=0.5)
                    self.active_samplers.remove(sampler)

                # STEP 3: Alarm List
                if not self._stop_event.is_set():
                    if al_x != 0 or al_y != 0:
                        _click_home()
                        if PYAUTOGUI_AVAILABLE: self._input.click(al_x, al_y); self._sleep(nav_wait)
                        al_zone = zones_dict.get("alarm_list")
                        if al_zone:
                            _al_bbox = (al_zone.x1, al_zone.y1, al_zone.x2, al_zone.y2)
                            _al_s = FrameSampler(_al_bbox,
                                                  duration_sec=float(self.config.get("sampler_duration_sec", 2.0)),
                                                  interval_ms=int(self.config.get("sampler_interval_ms", 100))) if UPGRADES_AVAILABLE else None
                            if _al_s: _al_s.start(); _al_s.join(timeout=float(self.config.get("sampler_duration_sec", 2.0)) + 0.5)
                            _al_ns = time.time_ns()
                            al_res = verifier.verify_list("alarm_list", expected_alarm, al_zone, sc_dir,
                                                           point_idx=i, sampler=_al_s, trigger_ns=_al_ns)
                            for r in al_res: r.step = r.step.replace("alarm_list/", "alarm_list/trigger/")
                            point_results.extend(al_res)
                            if any(r.status == "FAIL" for r in al_res): point_pass = False
                        else:
                            point_results.append(VerifyResult("alarm_list", "SKIP", "No alarm_list zone drawn."))
                    else:
                        point_results.append(VerifyResult("alarm_list", "SKIP", "Alarm list btn not configured."))

                # STEP 4: Event List
                if not self._stop_event.is_set():
                    if ev_x != 0 or ev_y != 0:
                        _click_home()
                        if PYAUTOGUI_AVAILABLE: self._input.click(ev_x, ev_y); self._sleep(nav_wait)
                        ev_zone = zones_dict.get("event_list")
                        if ev_zone:
                            _ev_bbox = (ev_zone.x1, ev_zone.y1, ev_zone.x2, ev_zone.y2)
                            _ev_s = FrameSampler(_ev_bbox,
                                                  duration_sec=float(self.config.get("sampler_duration_sec", 2.0)),
                                                  interval_ms=int(self.config.get("sampler_interval_ms", 100))) if UPGRADES_AVAILABLE else None
                            if _ev_s: _ev_s.start(); _ev_s.join(timeout=float(self.config.get("sampler_duration_sec", 2.0)) + 0.5)
                            _ev_ns = time.time_ns()
                            ev_res = verifier.verify_list("event_list", expected_alarm, ev_zone, sc_dir,
                                                           point_idx=i, sampler=_ev_s, trigger_ns=_ev_ns)
                            for r in ev_res: r.step = r.step.replace("event_list/", "event_list/trigger/")
                            point_results.extend(ev_res)
                            if any(r.status == "FAIL" for r in ev_res): point_pass = False
                        else:
                            point_results.append(VerifyResult("event_list", "SKIP", "No event_list zone drawn."))
                    else:
                        point_results.append(VerifyResult("event_list", "SKIP", "Event list btn not configured."))

                # STEP 5: Equipment Page
                if not self._stop_event.is_set():
                    if rc_x != 0 and rc_y != 0 and pg_x != 0 and pg_y != 0:
                        _click_home()
                        if PYAUTOGUI_AVAILABLE:
                            click_delay = self.config.get("click_delay", 1.5)
                            self._input.right_click(rc_x, rc_y); self._sleep(click_delay)
                            self._input.click(pg_x, pg_y); self._sleep(nav_wait)
                        eq_zone = zones_dict.get("equipment_page")
                        if eq_zone:
                            eq_res = verifier.verify_inspector(expected_alarm, eq_zone, sc_dir, point_idx=i)
                            for r in eq_res: r.step = "equipment/" + r.step
                            point_results.extend(eq_res)
                            if any(r.status == "FAIL" for r in eq_res): point_pass = False
                        else:
                            point_results.append(VerifyResult("equipment_page", "SKIP", "No equipment_page zone drawn."))
                    else:
                        point_results.append(VerifyResult("equipment_page", "SKIP", "Right-click coords not configured."))

                _click_home()  # STEP 6: home before reset

            # STEP 7: Reset + verify normalize (Symmetric Order: Reset first, then Start Sampler)
            reset_ok = False; norm_sampler = None; reset_ns = None
            
            try:
                # 1. Reset the alarm FIRST on the simulator
                handler.reset_alarm(pt)
                reset_ns = time.time_ns()
                reset_ok = True
            except Exception as ex:
                self.on_log(f"  [x] Reset failed for {point_id}: {ex}")
                
            if reset_ok and not self._stop_event.is_set():
                # 2. Start the sampler IMMEDIATELY after reset
                if UPGRADES_AVAILABLE and resolved_bbox:
                    norm_sampler = FrameSampler(resolved_bbox,
                                                 duration_sec=float(self.config.get("detection_duration_sec", 8.0)),
                                                 interval_ms=int(self.config.get("sampler_interval_ms", 100)))
                    self.active_samplers.append(norm_sampler)
                    norm_sampler.start()  # No .join() here! Left to run concurrently.
                    
                # 3. Perform visual verification
                if alarm_zone:
                    self.on_log(f"  Checking NORMALIZE state (v{reset_idx})...")
                    norm_res = verifier.verify_alarm_panel(
                        expected_norm, sc_dir, point_idx=i, trigger_time=None,
                        file_suffix="alarm_panel_normalize", sampler=norm_sampler, trigger_ns=reset_ns)
                    for r in norm_res: 
                        r.step = r.step.replace("alarm_panel/", "normalize/")
                    point_results.extend(norm_res)
                    if any(r.status == "FAIL" for r in norm_res): 
                        point_pass = False

            overall = "PASS" if point_pass else "FAIL"
            diag_data = None
            if not point_pass:
                try:
                    diag_data = FailureEvidenceCollector.collect(
                        session_dir=sc_dir, point_idx=i, pt=pt,
                        point_results=point_results, verifier=verifier,
                        trigger_time=trigger_time,
                        expected_alarm=expected_alarm, config=self.config,
                        reset_time=datetime.datetime.fromtimestamp(reset_ns / 1e9) if reset_ns else None,
                        expected_norm=expected_norm)
                except Exception as fe:
                    logger.warning(f"FailureEvidenceCollector failed: {fe}")

            sc_results.append({
                "point_id": point_id, "overall": overall, "failure_diagnostics": diag_data,
                "trigger_datetime":    next((r.msg for r in point_results if r.step == "alarm_panel/datetime"),    ""),
                "trigger_identifier":  next((r.msg for r in point_results if r.step == "alarm_panel/identifier"),  ""),
                "trigger_description": next((r.msg for r in point_results if r.step == "alarm_panel/description"), ""),
                "trigger_value":       next((r.msg for r in point_results if r.step == "alarm_panel/value"),       ""),
                "trigger_severity":    next((r.msg for r in point_results if r.step == "alarm_panel/severity"),    ""),
                "trigger_color":       next((r.msg for r in point_results if r.step == "alarm_panel/color"),       ""),
                "trigger_overall":     "PASS" if not any(r.status=="FAIL" for r in point_results if r.step.startswith("alarm_panel")) else "FAIL",
                "norm_identifier":     next((r.msg for r in point_results if r.step == "normalize/identifier"),    ""),
                "norm_datetime":       next((r.msg for r in point_results if r.step == "normalize/datetime"),      ""),
                "norm_value":          next((r.msg for r in point_results if r.step == "normalize/value"),         ""),
                "norm_severity":       next((r.msg for r in point_results if r.step == "normalize/severity"),      ""),
                "norm_color":          next((r.msg for r in point_results if r.step == "normalize/color"),         ""),
                "norm_overall":        "PASS" if not any(r.status=="FAIL" for r in point_results if r.step.startswith("normalize")) else "FAIL",
                "al_trigger_identifier": next((r.msg for r in point_results if r.step == "alarm_list/trigger/identifier"), ""),
                "al_trigger_value":      next((r.msg for r in point_results if r.step == "alarm_list/trigger/value"),      ""),
                "al_trigger_severity":   next((r.msg for r in point_results if r.step == "alarm_list/trigger/severity"),   ""),
                "al_trigger_color":      next((r.msg for r in point_results if r.step == "alarm_list/trigger/color"),      ""),
                "al_trigger_overall":    "FAIL" if any(r.status=="FAIL" for r in point_results if r.step.startswith("alarm_list/trigger")) else "PASS" if any(r.step.startswith("alarm_list/trigger") for r in point_results) else "SKIP",
                "al_norm_value":         next((r.msg for r in point_results if r.step == "alarm_list/normalize/value"),    ""),
                "al_norm_color":         next((r.msg for r in point_results if r.step == "alarm_list/normalize/color"),    ""),
                "al_norm_overall":       "FAIL" if any(r.status=="FAIL" for r in point_results if r.step.startswith("alarm_list/normalize")) else "PASS" if any(r.step.startswith("alarm_list/normalize") for r in point_results) else "SKIP",
                "ev_trigger_identifier": next((r.msg for r in point_results if r.step == "event_list/trigger/identifier"), ""),
                "ev_trigger_value":      next((r.msg for r in point_results if r.step == "event_list/trigger/value"),      ""),
                "ev_trigger_severity":   next((r.msg for r in point_results if r.step == "event_list/trigger/severity"),   ""),
                "ev_trigger_color":      next((r.msg for r in point_results if r.step == "event_list/trigger/color"),      ""),
                "ev_trigger_overall":    "FAIL" if any(r.status=="FAIL" for r in point_results if r.step.startswith("event_list/trigger")) else "PASS" if any(r.step.startswith("event_list/trigger") for r in point_results) else "SKIP",
                "ev_norm_value":         next((r.msg for r in point_results if r.step == "event_list/normalize/value"),    ""),
                "ev_norm_color":         next((r.msg for r in point_results if r.step == "event_list/normalize/color"),    ""),
                "ev_norm_overall":       "FAIL" if any(r.status=="FAIL" for r in point_results if r.step.startswith("event_list/normalize")) else "PASS" if any(r.step.startswith("event_list/normalize") for r in point_results) else "SKIP",
                "eq_overall":  next((r.status for r in point_results if r.step.startswith("equipment")), "SKIP"),
                "eq_detail":   next((r.msg for r in point_results if r.step.startswith("equipment") and r.status != "SKIP"), ""),
                "screenshot":  next((r.screenshot for r in point_results if r.screenshot), ""),
            })
            card_loop = getattr(sc, "card_loop", 1)
            self.on_progress(p_num, card_loop, s_idx+1, len(self.scenarios),
                             i+1, len(sc.iscs_points), point_id, overall)


# ═════════════════════════════════════════════════════════════════════════════
#  RUN SERVICE  (M4 — the facade's run_service seam over SuiteRunner)
# ═════════════════════════════════════════════════════════════════════════════
def _noop(*_a, **_k):
    return None


class SuiteRunService:
    """Adapts SuiteRunner's per-run thread lifecycle to the WilloWispCoreAPI
    ``run_service`` contract (``start``/``stop``/``pause``/``resume``/``get_state``).

    A composition root (the CLI or the Tk app) injects the collaborators — config,
    the protocol manager, the InputControlPort, the event bus, and optional
    log/progress callbacks — once; each ``start(scenarios, …)`` then spins up a
    SuiteRunner for that run. UI-agnostic: callbacks default to no-ops, so a headless
    caller drives a full author→run→report cycle without any GUI.
    """

    def __init__(self, *, config, protocols, monitors=None, input_control=None,
                 event_bus=None, on_log=None, on_progress=None):
        self._config     = config
        self._protocols  = protocols
        self._monitors   = monitors or []
        self._input      = input_control
        self._bus        = event_bus if event_bus is not None else CORE_BUS
        self._on_log     = on_log or _noop
        self._on_progress = on_progress or _noop
        self._active = None     # the SuiteRunner of the current/last run

    def start(self, scenarios, *, monitors=None, suite_title="", rerun_failed_count=0):
        runner = SuiteRunner(
            scenarios, monitors or self._monitors, self._protocols, self._config,
            _noop, self._on_progress, _noop, _noop, _noop, self._on_log,
            suite_title=suite_title, rerun_failed_count=rerun_failed_count,
            event_bus=self._bus, input_control=self._input,
        )
        self._active = runner
        runner.start()
        return runner

    def stop(self):
        if self._active is not None:
            self._active.stop()

    def pause(self):
        if self._active is not None:
            self._active.pause()

    def resume(self):
        if self._active is not None:
            self._active.resume()

    def get_state(self) -> str:
        r = self._active
        if r is None or not r.is_alive():
            return "idle"
        return "paused" if r.is_paused else "running"

    def join(self, timeout=None):
        """Block until the active run finishes (for synchronous CLI/headless callers)."""
        if self._active is not None:
            self._active.join(timeout)
