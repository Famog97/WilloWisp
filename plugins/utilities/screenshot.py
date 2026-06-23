"""
Screenshot utility capability (P3.1), ported from _exec_screenshot. Grabs a
region (or the whole screen when no coords) and saves it under the point's dir.
"""
import datetime

from iscs_core import register, CapabilityMeta, StepResult, StepStatus


@register(override=True)
class ScreenshotCapability:
    key = "screenshot"
    meta = CapabilityMeta(name="Screenshot", category="utility",
                          description="Capture a region (or full screen) to the evidence folder.",
                          params_schema={"x1": 0, "y1": 0, "x2": 0, "y2": 0})

    def execute(self, ctx) -> StepResult:
        log = getattr(ctx, "log", None) or (lambda _m: None)
        ec  = getattr(ctx, "exec", None)
        proc = getattr(ctx, "proc", None)
        params = (getattr(proc, "params", {}) or {}) if proc is not None else {}
        try:
            from PIL import ImageGrab
            x1, y1 = params.get("x1", 0), params.get("y1", 0)
            x2, y2 = params.get("x2", 0), params.get("y2", 0)
            bbox = (x1, y1, x2, y2) if any([x1, y1, x2, y2]) else None
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = ec.sc_dir / f"{ec.point_idx:04d}_manual_ss_{ts}.png"
            img.save(str(path))
            log(f"Screenshot saved → {path.name}")
            return StepResult(StepStatus.PASS, screenshot=str(path))
        except Exception as exc:
            log(f"Screenshot failed: {exc}")
            return StepResult(StepStatus.FAIL)
