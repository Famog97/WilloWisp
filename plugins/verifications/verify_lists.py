"""
Verify Alarm List + Verify Event List — verification capabilities (P3.2), ported
from _exec_verify_alarm_list / _exec_verify_event_list.

Both sample the list region briefly (FrameSampler) and delegate to the backend's
verify_list, then re-tag step names to the list's trigger column. The two share
one implementation parameterised by list type, so the file demonstrates that a
plugin file may register more than one capability.
"""
import time

from iscs_core import register, CapabilityMeta, StepResult, StepStatus


class _VerifyListBase:
    """Shared logic for alarm_list / event_list verification."""
    LIST_TYPE = ""
    ZONE_KEY = ""

    def execute(self, ctx) -> StepResult:
        ec      = getattr(ctx, "exec", None)
        log     = getattr(ctx, "log", None) or (lambda _m: None)
        runner  = getattr(ctx, "runner", None)
        backend = getattr(runner, "verifier", None) if runner is not None else None
        config  = getattr(runner, "config", {}) if runner is not None else {}

        if ec is None or backend is None:
            return StepResult(StepStatus.SKIP, message="No verifier/context available.")

        zone = (getattr(ec, "zones_dict", {}) or {}).get(self.ZONE_KEY)
        if not zone:
            return StepResult(StepStatus.SKIP)

        sampler, trig_ns = None, time.time_ns()
        try:
            from iscs_Sampler_Anchor import FrameSampler
            bbox = (zone.x1, zone.y1, zone.x2, zone.y2)
            dur  = float(config.get("sampler_duration_sec", 2.0))
            ims  = int(config.get("sampler_interval_ms", 100))
            sampler = FrameSampler(bbox, duration_sec=dur, interval_ms=ims)
            sampler.start()
            sampler.join(timeout=dur + 0.5)
            trig_ns = time.time_ns()
        except ImportError:
            sampler = None

        results = backend.verify_list(
            self.LIST_TYPE, ec.expected_alarm, zone, ec.sc_dir,
            point_idx=ec.point_idx, sampler=sampler, trigger_ns=trig_ns,
        )
        prefix = f"{self.LIST_TYPE}/"
        for r in results:
            step = getattr(r, "step", None)
            if step:
                r.step = step.replace(prefix, f"{prefix}trigger/")

        failed = any(getattr(r, "status", "") == "FAIL" for r in results)
        log(f"→ {'FAIL' if failed else 'PASS'}")
        return StepResult(StepStatus.FAIL if failed else StepStatus.PASS,
                          data={"verify_results": results})


@register(override=True)
class VerifyAlarmListCapability(_VerifyListBase):
    key = "verify_alarm_list"
    LIST_TYPE = "alarm_list"
    ZONE_KEY = "alarm_list"
    meta = CapabilityMeta(name="Verify Alarm List", category="verification",
                          description="OCR + colour check on the alarm list zone.",
                          requires=["verifier"])


@register(override=True)
class VerifyEventListCapability(_VerifyListBase):
    key = "verify_event_list"
    LIST_TYPE = "event_list"
    ZONE_KEY = "event_list"
    meta = CapabilityMeta(name="Verify Event List", category="verification",
                          description="OCR + colour check on the event list zone.",
                          requires=["verifier"])
