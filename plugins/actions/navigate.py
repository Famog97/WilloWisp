"""
Navigation action capabilities (P3.1), ported from
_exec_navigate_home / _exec_navigate_alarm_list / _exec_navigate_event_list /
_exec_navigate_equip_page. Click the configured nav coordinates with the
configured nav_wait between clicks; skip cleanly when coords aren't set.
"""
import time

from iscs_core import register, CapabilityMeta, StepResult, StepStatus


def _params(ctx):
    proc = getattr(ctx, "proc", None)
    return (getattr(proc, "params", {}) or {}) if proc is not None else {}


def _cfg(ctx, key, default):
    runner = getattr(ctx, "runner", None)
    cfg = getattr(runner, "config", {}) if runner is not None else {}
    return (cfg or {}).get(key, default)


def _log(ctx, msg):
    fn = getattr(ctx, "log", None)
    if callable(fn):
        fn(msg)


def _sleep(ctx, secs):
    runner = getattr(ctx, "runner", None)
    if runner is not None and hasattr(runner, "_sleep"):
        runner._sleep(secs)
    else:
        time.sleep(secs)


def _pyautogui(ctx, note="navigation skipped."):
    try:
        import pyautogui
        return pyautogui
    except ImportError:
        _log(ctx, f"pyautogui not available — {note}")
        return None


@register(override=True)
class NavigateHomeAction:
    key = "navigate_home"
    meta = CapabilityMeta(name="Return to Home", category="action",
                          description="Click the Home button.")

    def execute(self, ctx) -> StepResult:
        pg = _pyautogui(ctx)
        if pg is None:
            return StepResult(StepStatus.SKIP)
        p = _params(ctx)
        ec = getattr(ctx, "exec", None)
        extra = getattr(ec, "extra", {}) if ec is not None else {}
        hm_x = p.get("home_x", 0) or (extra or {}).get("home_x", 0)
        hm_y = p.get("home_y", 0) or (extra or {}).get("home_y", 0)
        if hm_x == 0 and hm_y == 0:
            return StepResult(StepStatus.SKIP)
        pg.click(hm_x, hm_y)
        _sleep(ctx, _cfg(ctx, "nav_wait_sec", 1.0))
        _log(ctx, f"Clicked Home ({hm_x}, {hm_y}).")
        return StepResult(StepStatus.PASS)


class _NavigateListBase:
    """Home (optional) then a single nav-button click."""
    X_KEY = ""
    Y_KEY = ""
    LABEL = ""

    def execute(self, ctx) -> StepResult:
        pg = _pyautogui(ctx)
        if pg is None:
            return StepResult(StepStatus.SKIP)
        p = _params(ctx)
        nav_wait = _cfg(ctx, "nav_wait_sec", 1.0)
        hm_x, hm_y = p.get("home_x", 0), p.get("home_y", 0)
        tx, ty = p.get(self.X_KEY, 0), p.get(self.Y_KEY, 0)
        if tx == 0 and ty == 0:
            return StepResult(StepStatus.SKIP)
        if hm_x or hm_y:
            pg.click(hm_x, hm_y)
            _sleep(ctx, nav_wait)
        pg.click(tx, ty)
        _sleep(ctx, nav_wait)
        _log(ctx, f"Navigated to {self.LABEL} ({tx}, {ty}).")
        return StepResult(StepStatus.PASS)


@register(override=True)
class NavigateAlarmListAction(_NavigateListBase):
    key = "navigate_alarm_list"
    X_KEY, Y_KEY, LABEL = "al_x", "al_y", "Alarm List"
    meta = CapabilityMeta(name="Navigate to Alarm List", category="action",
                          description="Click Home then the Alarm List nav button.")


@register(override=True)
class NavigateEventListAction(_NavigateListBase):
    key = "navigate_event_list"
    X_KEY, Y_KEY, LABEL = "ev_x", "ev_y", "Event List"
    meta = CapabilityMeta(name="Navigate to Event List", category="action",
                          description="Click Home then the Event List nav button.")


@register(override=True)
class NavigateEquipmentPageAction:
    key = "navigate_equipment_page"
    meta = CapabilityMeta(name="Navigate to Equipment Page", category="action",
                          description="Click Home, right-click the alarm row, open the equipment page.")

    def execute(self, ctx) -> StepResult:
        pg = _pyautogui(ctx)
        if pg is None:
            return StepResult(StepStatus.SKIP)
        p = _params(ctx)
        nav_wait = _cfg(ctx, "nav_wait_sec", 1.0)
        hm_x, hm_y = p.get("home_x", 0), p.get("home_y", 0)
        rc_x, rc_y = p.get("rc_x", 0), p.get("rc_y", 0)
        pg_x, pg_y = p.get("pg_x", 0), p.get("pg_y", 0)
        if rc_x == 0 or pg_x == 0:
            return StepResult(StepStatus.SKIP)
        if hm_x or hm_y:
            pg.click(hm_x, hm_y)
            _sleep(ctx, nav_wait)
        pg.rightClick(rc_x, rc_y)
        _sleep(ctx, _cfg(ctx, "click_delay", 1.5))
        pg.click(pg_x, pg_y)
        _sleep(ctx, nav_wait)
        _log(ctx, f"Navigated to Equipment Page via right-click ({rc_x},{rc_y}) → ({pg_x},{pg_y}).")
        return StepResult(StepStatus.PASS)
