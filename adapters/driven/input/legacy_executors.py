"""
adapters/driven/input/legacy_executors.py  (M3.4 — extracted from ProcedureRunner)

The legacy ``_exec_*`` step executors, moved out of the engine so the engine itself
carries no mouse/keyboard automation (``pyautogui``) and can live in pure ``core/``.

These are the **safety-net fallback** (R-EXT-1): every step type normally runs through
its registered plugin; the registry only falls back to one of these when a plugin is
missing (e.g. a plugin file dropped during install). They were ``ProcedureRunner``
methods (``self.handler`` / ``self.config`` / ``self.verifier`` / ``self._sleep``);
extraction rebinds ``self`` -> the ``runner`` passed in by ``LegacyCapabilityAdapter``
(and by the engine's direct-fallback branch). Behaviour is otherwise byte-for-byte
the same — pyautogui / PIL / FrameSampler stay lazily imported inside each function.
"""
from __future__ import annotations

import datetime
import time

from core.domain.flow import ProcedureStatus

try:
    from adapters.driven.persistence.asset_store import BindingExecutor, StepBinding
    _ASSETS_OK = True
except Exception:                       # pragma: no cover - asset module optional
    BindingExecutor = None
    StepBinding     = None
    _ASSETS_OK      = False


def _exec_trigger_alarm(runner, proc, ctx, sampler_ok, log):
    if not ctx.pt:
        log("SKIPPED: Standalone run contains no active Modbus/SNMP IO point.")
        return ProcedureStatus.SKIP, [], ""
    try:
        from iscs_Sampler_Anchor import FrameSampler
    except ImportError:
        sampler_ok = False

    # 1. Trigger the alarm FIRST
    runner.handler.trigger_alarm(ctx.pt)
    ctx.trigger_time = datetime.datetime.now()
    ctx.trigger_ns   = time.time_ns()
    ctx.trigger_ok   = True
    log(f"Alarm triggered at {ctx.trigger_time.strftime('%H:%M:%S.%f')[:-3]}")

    # 2. Start the frame sampler IMMEDIATELY after trigger
    if sampler_ok and ctx.resolved_bbox:
        dur = float(runner.config.get("detection_duration_sec", 8.0))
        ims = int(runner.config.get("sampler_interval_ms", 100))
        ctx.sampler = FrameSampler(ctx.resolved_bbox, duration_sec=dur, interval_ms=ims)
        ctx.sampler.start()
        log("FrameSampler started (running concurrently).")

    return ProcedureStatus.PASS, [], ""

def _exec_reset_alarm(runner, proc, ctx, sampler_ok, log):
    if not ctx.pt:
        log("SKIPPED: Standalone run contains no active Modbus/SNMP IO point.")
        return ProcedureStatus.SKIP, [], ""
    try:
        from iscs_Sampler_Anchor import FrameSampler
    except ImportError:
        sampler_ok = False

    # 1. Reset the alarm FIRST
    runner.handler.reset_alarm(ctx.pt)
    ctx.reset_ns = time.time_ns()
    ctx.reset_ok = True
    log("Alarm reset.")

    # 2. Start the normalization sampler IMMEDIATELY after reset
    if sampler_ok and ctx.resolved_bbox:
        dur = float(runner.config.get("detection_duration_sec", 8.0))
        ims = int(runner.config.get("sampler_interval_ms", 100))
        ctx.norm_sampler = FrameSampler(ctx.resolved_bbox, duration_sec=dur, interval_ms=ims)
        ctx.norm_sampler.start()
        log("Normalization sampler started (running concurrently).")

    return ProcedureStatus.PASS, [], ""

def _exec_navigate_home(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        log("pyautogui not available — navigation skipped.")
        return ProcedureStatus.SKIP, [], ""

    params    = proc.params
    nav_wait  = runner.config.get("nav_wait_sec", 1.0)
    hm_x      = params.get("home_x", 0) or ctx.extra.get("home_x", 0)
    hm_y      = params.get("home_y", 0) or ctx.extra.get("home_y", 0)
    if hm_x == 0 and hm_y == 0:
        return ProcedureStatus.SKIP, [], ""

    pyautogui.click(hm_x, hm_y)
    runner._sleep(nav_wait)
    log(f"Clicked Home ({hm_x}, {hm_y}).")
    return ProcedureStatus.PASS, [], ""

def _exec_navigate_alarm_list(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        return ProcedureStatus.SKIP, [], ""

    params   = proc.params
    nav_wait = runner.config.get("nav_wait_sec", 1.0)
    hm_x, hm_y = params.get("home_x", 0), params.get("home_y", 0)
    al_x, al_y = params.get("al_x", 0),   params.get("al_y", 0)

    if al_x == 0 and al_y == 0:
        return ProcedureStatus.SKIP, [], ""

    if hm_x or hm_y:
        pyautogui.click(hm_x, hm_y);  runner._sleep(nav_wait)
    pyautogui.click(al_x, al_y);      runner._sleep(nav_wait)
    log(f"Navigated to Alarm List ({al_x}, {al_y}).")
    return ProcedureStatus.PASS, [], ""

def _exec_navigate_event_list(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        return ProcedureStatus.SKIP, [], ""

    params   = proc.params
    nav_wait = runner.config.get("nav_wait_sec", 1.0)
    hm_x, hm_y = params.get("home_x", 0), params.get("home_y", 0)
    ev_x, ev_y = params.get("ev_x", 0),   params.get("ev_y", 0)

    if ev_x == 0 and ev_y == 0:
        return ProcedureStatus.SKIP, [], ""

    if hm_x or hm_y:
        pyautogui.click(hm_x, hm_y);  runner._sleep(nav_wait)
    pyautogui.click(ev_x, ev_y);      runner._sleep(nav_wait)
    log(f"Navigated to Event List ({ev_x}, {ev_y}).")
    return ProcedureStatus.PASS, [], ""

def _exec_navigate_equip_page(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        return ProcedureStatus.SKIP, [], ""

    params   = proc.params
    nav_wait = runner.config.get("nav_wait_sec", 1.0)
    hm_x, hm_y = params.get("home_x", 0), params.get("home_y", 0)
    rc_x, rc_y = params.get("rc_x", 0),   params.get("rc_y", 0)
    pg_x, pg_y = params.get("pg_x", 0),   params.get("pg_y", 0)

    if rc_x == 0 or pg_x == 0:
        return ProcedureStatus.SKIP, [], ""

    if hm_x or hm_y:
        pyautogui.click(hm_x, hm_y);       runner._sleep(nav_wait)
    click_delay = runner.config.get("click_delay", 1.5)
    pyautogui.rightClick(rc_x, rc_y);      runner._sleep(click_delay)
    pyautogui.click(pg_x, pg_y);           runner._sleep(nav_wait)
    log(f"Navigated to Equipment Page via right-click ({rc_x},{rc_y}) → ({pg_x},{pg_y}).")
    return ProcedureStatus.PASS, [], ""

# ── Verification executors ────────────────────────────────────────────────

def _exec_verify_alarm_panel(runner, proc, ctx, sampler_ok, log):
    if not ctx.expected_alarm:
        log("SKIPPED: No expected point state loaded for verification.")
        return ProcedureStatus.SKIP, [], ""
    log(f"Checking TRIGGER state (v{ctx.trigger_idx})…")
    results = runner.verifier.verify_alarm_panel(
        ctx.expected_alarm, ctx.sc_dir,
        point_idx   = ctx.point_idx,
        trigger_time= ctx.trigger_time,
        file_suffix = "alarm_panel_trigger",
        sampler     = ctx.sampler,
        trigger_ns  = ctx.trigger_ns,
    )
    status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
    ss = next((r.screenshot for r in results if getattr(r, "screenshot", "")), "")
    log(f"→ {status.value}  ({sum(1 for r in results if r.status=='PASS')}/{len(results)} checks passed)")
    return status, results, ss

def _exec_verify_normalize(runner, proc, ctx, sampler_ok, log):
    log(f"Checking NORMALIZE state (v{ctx.reset_idx})…")
    results = runner.verifier.verify_alarm_panel(
        ctx.expected_norm, ctx.sc_dir,
        point_idx   = ctx.point_idx,
        trigger_time= None,
        file_suffix = "alarm_panel_normalize",
        sampler     = ctx.norm_sampler,
        trigger_ns  = ctx.reset_ns,
    )
    # Re-tag step names to "normalize/…" (matches existing report field mapping)
    for r in results:
        r.step = r.step.replace("alarm_panel/", "normalize/")

    status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
    log(f"→ {status.value}")
    return status, results, ""

def _exec_verify_alarm_list(runner, proc, ctx, sampler_ok, log):
    al_zone = ctx.zones_dict.get("alarm_list")
    if not al_zone:
        return ProcedureStatus.SKIP, [], ""

    try:
        from iscs_Sampler_Anchor import FrameSampler
        _al_bbox = (al_zone.x1, al_zone.y1, al_zone.x2, al_zone.y2)
        dur = float(runner.config.get("sampler_duration_sec", 2.0))
        ims = int(runner.config.get("sampler_interval_ms", 100))
        _al_s = FrameSampler(_al_bbox, duration_sec=dur, interval_ms=ims)
        _al_s.start()
        _al_s.join(timeout=dur + 0.5)
        _al_ns = time.time_ns()
    except ImportError:
        _al_s, _al_ns = None, time.time_ns()

    results = runner.verifier.verify_list(
        "alarm_list", ctx.expected_alarm, al_zone,
        ctx.sc_dir, point_idx=ctx.point_idx,
        sampler=_al_s, trigger_ns=_al_ns,
    )
    for r in results:
        r.step = r.step.replace("alarm_list/", "alarm_list/trigger/")

    status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
    log(f"→ {status.value}")
    return status, results, ""

def _exec_verify_event_list(runner, proc, ctx, sampler_ok, log):
    ev_zone = ctx.zones_dict.get("event_list")
    if not ev_zone:
        return ProcedureStatus.SKIP, [], ""

    try:
        from iscs_Sampler_Anchor import FrameSampler
        _ev_bbox = (ev_zone.x1, ev_zone.y1, ev_zone.x2, ev_zone.y2)
        dur = float(runner.config.get("sampler_duration_sec", 2.0))
        ims = int(runner.config.get("sampler_interval_ms", 100))
        _ev_s = FrameSampler(_ev_bbox, duration_sec=dur, interval_ms=ims)
        _ev_s.start()
        _ev_s.join(timeout=dur + 0.5)
        _ev_ns = time.time_ns()
    except ImportError:
        _ev_s, _ev_ns = None, time.time_ns()

    results = runner.verifier.verify_list(
        "event_list", ctx.expected_alarm, ev_zone,
        ctx.sc_dir, point_idx=ctx.point_idx,
        sampler=_ev_s, trigger_ns=_ev_ns,
    )
    for r in results:
        r.step = r.step.replace("event_list/", "event_list/trigger/")

    status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
    log(f"→ {status.value}")
    return status, results, ""

def _exec_verify_equip_page(runner, proc, ctx, sampler_ok, log):
    eq_zone = ctx.zones_dict.get("equipment_page")
    if not eq_zone:
        return ProcedureStatus.SKIP, [], ""

    results = runner.verifier.verify_inspector(
        ctx.expected_alarm, eq_zone, ctx.sc_dir, point_idx=ctx.point_idx
    )
    for r in results:
        r.step = "equipment/" + r.step

    status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
    log(f"→ {status.value}")
    return status, results, ""

def _exec_delay(runner, proc, ctx, sampler_ok, log):
    delay = float(proc.params.get("delay_sec", 1.0))
    log(f"Waiting {delay:.1f}s…")
    runner._sleep(delay)
    return ProcedureStatus.PASS, [], ""

def _exec_screenshot(runner, proc, ctx, sampler_ok, log):
    try:
        from PIL import ImageGrab
        p = proc.params
        x1, y1, x2, y2 = p.get("x1", 0), p.get("y1", 0), p.get("x2", 0), p.get("y2", 0)
        # If all coordinates are 0, grab the whole screen
        _bbox = (x1, y1, x2, y2) if any([x1, y1, x2, y2]) else None
        img = ImageGrab.grab(bbox=_bbox, all_screens=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = ctx.sc_dir / f"{ctx.point_idx:04d}_manual_ss_{ts}.png"
        img.save(str(path))
        log(f"Screenshot saved → {path.name}")
        return ProcedureStatus.PASS, [], str(path)
    except Exception as exc:
        log(f"Screenshot failed: {exc}")
        return ProcedureStatus.FAIL, [], ""

# ── / Custom executors ───────────────────────────────────────────────

def _exec_click(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
    x, y = int(proc.params.get("x", 0)), int(proc.params.get("y", 0))
    wait = float(proc.params.get("wait_after", 0.5))
    if x == 0 and y == 0:
        log("Click: no coords."); return ProcedureStatus.SKIP, [], ""
    pyautogui.click(x, y); runner._sleep(wait)
    log(f"Clicked ({x}, {y})  wait={wait}s")
    return ProcedureStatus.PASS, [], ""

def _exec_right_click(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
    x, y = int(proc.params.get("x", 0)), int(proc.params.get("y", 0))
    wait = float(proc.params.get("wait_after", 0.5))
    if x == 0 and y == 0:
        log("Right Click: no coords."); return ProcedureStatus.SKIP, [], ""
    pyautogui.rightClick(x, y); runner._sleep(wait)
    log(f"Right-clicked ({x}, {y})  wait={wait}s")
    return ProcedureStatus.PASS, [], ""

def _exec_hotkey(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
    keys_raw = proc.params.get("keys", "")
    if not keys_raw:
        log("Hotkey: no keys."); return ProcedureStatus.SKIP, [], ""
    wait = float(proc.params.get("wait_after", 0.5))
    keys = [k.strip() for k in str(keys_raw).lower().split("+")]
    pyautogui.hotkey(*keys); runner._sleep(wait)
    log(f"Hotkey: {' + '.join(keys)}")
    return ProcedureStatus.PASS, [], ""

def _exec_type_text(runner, proc, ctx, sampler_ok, log):
    try:
        import pyautogui
    except ImportError:
        log("pyautogui not available."); return ProcedureStatus.SKIP, [], ""
    text = str(proc.params.get("text", ""))
    x, y = int(proc.params.get("x", 0)), int(proc.params.get("y", 0))
    wait = float(proc.params.get("wait_after", 0.3))
    interval = float(proc.params.get("interval", 0.05))
    if x and y:
        pyautogui.click(x, y); runner._sleep(0.2)
    pyautogui.typewrite(text, interval=interval); runner._sleep(wait)
    log(f"Typed {len(text)} chars")
    return ProcedureStatus.PASS, [], ""

def _exec_verify_alarm_panel_custom(runner, proc, ctx, sampler_ok, log):
    custom = {}
    for k, pk in [("color","expected_color"),("identifier","expected_identifier"),("severity","expected_severity")]:
        if pk in proc.params:
            custom[k] = proc.params[pk]
    expected = custom if custom else ctx.expected_alarm
    log("Standalone alarm panel check...")
    results = runner.verifier.verify_alarm_panel(
        expected, ctx.sc_dir,
        point_idx   = ctx.point_idx,
        trigger_time= None,
        file_suffix = proc.params.get("file_suffix", "alarm_panel_custom"),
        sampler     = None,
        trigger_ns  = None,
    )
    status = ProcedureStatus.FAIL if any(r.status == "FAIL" for r in results) else ProcedureStatus.PASS
    ss = next((r.screenshot for r in results if getattr(r, "screenshot", "")), "")
    log(f"-> {status.value}  ({sum(1 for r in results if r.status=='PASS')}/{len(results)} checks passed)")
    return status, results, ss

# ── Asset-bound custom verify step ────────────────────────────────────

def _exec_verify_custom(runner, proc, ctx, sampler_ok, log):
    """
    Execute a VERIFY_CUSTOM step that uses the asset binding system.
    If _ASSETS_OK is False (module not installed), step is skipped.
    If binding is missing, step is skipped with a warning.
    """
    if not _ASSETS_OK or BindingExecutor is None:
        log("SKIPPED: iscs_assets module not available")
        return ProcedureStatus.SKIP, [], ""

    binding_dict = proc.binding
    if not binding_dict:
        log("SKIPPED: step has no binding configured")
        return ProcedureStatus.SKIP, [], ""

    try:
        binding = StepBinding.from_dict(binding_dict)
    except Exception as e:
        log(f"SKIPPED: could not parse binding — {e}")
        return ProcedureStatus.SKIP, [], ""

    log(f"Executing asset binding [{binding.type}] "
        f"asset={binding.asset_id!r} region={binding.region_id!r}")

    executor = BindingExecutor()
    result   = executor.execute(binding)

    status_str = result.get("status", "FAIL")
    msg        = result.get("message", "")
    expected   = result.get("expected", "")
    actual     = result.get("actual", "")
    score      = result.get("score", 0.0)

    log(f"-> {status_str}  {msg}")
    if expected or actual:
        log(f"   expected={expected!r}  actual={actual!r}  score={score:.3f}")

    # Wrap into a VerifyResult-compatible dict for the report
    from types import SimpleNamespace
    vr = SimpleNamespace(
        status     = status_str,
        step       = proc.name,
        message    = msg,
        expected   = expected,
        actual     = actual,
        screenshot = "",
    )

    if status_str == "SKIP" or binding.on_fail == "skip":
        return ProcedureStatus.SKIP, [vr], ""
    if status_str == "PASS":
        return ProcedureStatus.PASS, [vr], ""
    return ProcedureStatus.FAIL, [vr], ""
