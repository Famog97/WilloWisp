"""
Input action capabilities (P3.1), ported from ProcedureRunner._exec_click /
_exec_right_click / _exec_hotkey / _exec_type_text.

Self-contained (plugin files load individually): mouse/keyboard via pyautogui,
waits via the runner's interruptible _sleep so Stop still aborts.
"""
import time

from iscs_core import register, CapabilityMeta, StepResult, StepStatus


def _params(ctx):
    proc = getattr(ctx, "proc", None)
    return (getattr(proc, "params", {}) or {}) if proc is not None else {}


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


def _pyautogui(ctx):
    try:
        import pyautogui
        return pyautogui
    except ImportError:
        _log(ctx, "pyautogui not available.")
        return None


@register(override=True)
class ClickAction:
    key = "click"
    meta = CapabilityMeta(name="Click", category="action",
                          description="Left-click at (x, y).",
                          params_schema={"x": 0, "y": 0, "wait_after": 0.5})

    def execute(self, ctx) -> StepResult:
        pg = _pyautogui(ctx)
        if pg is None:
            return StepResult(StepStatus.SKIP)
        p = _params(ctx)
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        wait = float(p.get("wait_after", 0.5))
        if x == 0 and y == 0:
            _log(ctx, "Click: no coords.")
            return StepResult(StepStatus.SKIP)
        pg.click(x, y)
        _sleep(ctx, wait)
        _log(ctx, f"Clicked ({x}, {y})  wait={wait}s")
        return StepResult(StepStatus.PASS)


@register(override=True)
class RightClickAction:
    key = "right_click"
    meta = CapabilityMeta(name="Right Click", category="action",
                          description="Right-click at (x, y).",
                          params_schema={"x": 0, "y": 0, "wait_after": 0.5})

    def execute(self, ctx) -> StepResult:
        pg = _pyautogui(ctx)
        if pg is None:
            return StepResult(StepStatus.SKIP)
        p = _params(ctx)
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        wait = float(p.get("wait_after", 0.5))
        if x == 0 and y == 0:
            _log(ctx, "Right Click: no coords.")
            return StepResult(StepStatus.SKIP)
        pg.rightClick(x, y)
        _sleep(ctx, wait)
        _log(ctx, f"Right-clicked ({x}, {y})  wait={wait}s")
        return StepResult(StepStatus.PASS)


@register(override=True)
class HotkeyAction:
    key = "hotkey"
    meta = CapabilityMeta(name="Hotkey", category="action",
                          description="Press a key combo, e.g. 'ctrl+s'.",
                          params_schema={"keys": "", "wait_after": 0.5})

    def execute(self, ctx) -> StepResult:
        pg = _pyautogui(ctx)
        if pg is None:
            return StepResult(StepStatus.SKIP)
        p = _params(ctx)
        keys_raw = p.get("keys", "")
        if not keys_raw:
            _log(ctx, "Hotkey: no keys.")
            return StepResult(StepStatus.SKIP)
        wait = float(p.get("wait_after", 0.5))
        keys = [k.strip() for k in str(keys_raw).lower().split("+")]
        pg.hotkey(*keys)
        _sleep(ctx, wait)
        _log(ctx, f"Hotkey: {' + '.join(keys)}")
        return StepResult(StepStatus.PASS)


@register(override=True)
class TypeTextAction:
    key = "type_text"
    meta = CapabilityMeta(name="Type Text", category="action",
                          description="Type text. Optionally click a field first (click_first).",
                          params_schema={"click_first": False, "text": "", "x": 0, "y": 0,
                                         "wait_after": 0.3, "interval": 0.05})

    def execute(self, ctx) -> StepResult:
        pg = _pyautogui(ctx)
        if pg is None:
            return StepResult(StepStatus.SKIP)
        p = _params(ctx)
        text = str(p.get("text", ""))
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        wait = float(p.get("wait_after", 0.3))
        interval = float(p.get("interval", 0.05))
        # Only click a field first when explicitly enabled (default: just type).
        if p.get("click_first") and x and y:
            pg.click(x, y)
            _sleep(ctx, 0.2)
        pg.typewrite(text, interval=interval)
        _sleep(ctx, wait)
        _log(ctx, f"Typed {len(text)} chars")
        return StepResult(StepStatus.PASS)
