"""
Protocol action capabilities (final Phase 3 port) — trigger_alarm / reset_alarm,
ported from ProcedureRunner._exec_trigger_alarm / _exec_reset_alarm.

These were intentionally the LAST step types to leave the engine (protocol +
sampler timing critical). The capability replicates the legacy logic exactly:
it sends the signal via the runner's protocol handler FIRST, records the trigger/
reset timestamps on the shared exec-context, then starts the frame sampler
IMMEDIATELY after — so detection timing is unchanged. Registered with
override=True to supersede the legacy adapters by key; the legacy _exec_* methods
remain as the fallback if these plugins are removed.

Receives the LegacyExecContext bridge: ctx.exec (ExecContext with .pt /
.resolved_bbox / trigger+reset fields), ctx.runner (.handler, .config),
ctx.sampler_ok, ctx.log.
"""
import datetime
import time

from iscs_core import register, CapabilityMeta, StepResult, StepStatus


def _log(ctx, msg):
    fn = getattr(ctx, "log", None)
    if callable(fn):
        fn(msg)


def _frame_sampler_cls():
    """The FrameSampler class, or None if the upgrades module isn't installed."""
    try:
        from iscs_Sampler_Anchor import FrameSampler
        return FrameSampler
    except ImportError:
        return None


def _start_sampler(ctx, ec, runner, attr: str, note: str) -> None:
    """Start a FrameSampler on the resolved bbox and stash it on the exec-context
    under `attr` (`sampler` for trigger, `norm_sampler` for reset). No-op when the
    sampler is unavailable or there's no resolved bbox — matching the legacy guard."""
    if not getattr(ctx, "sampler_ok", False):
        return
    FrameSampler = _frame_sampler_cls()
    if FrameSampler is None or not getattr(ec, "resolved_bbox", None):
        return
    cfg = getattr(runner, "config", {}) or {}
    dur = float(cfg.get("detection_duration_sec", 8.0))
    ims = int(cfg.get("sampler_interval_ms", 100))
    sampler = FrameSampler(ec.resolved_bbox, duration_sec=dur, interval_ms=ims)
    sampler.start()
    setattr(ec, attr, sampler)
    _log(ctx, note)


@register(override=True)
class TriggerAlarmAction:
    key = "trigger_alarm"
    meta = CapabilityMeta(
        name="Trigger Alarm", category="action", requires=["protocol"],
        description="Send the alarm signal via the configured protocol "
                    "(Modbus/SNMP), then start the frame sampler immediately.")

    def execute(self, ctx) -> StepResult:
        ec = getattr(ctx, "exec", None)
        runner = getattr(ctx, "runner", None)
        if ec is None or runner is None or not getattr(ec, "pt", None):
            _log(ctx, "SKIPPED: Standalone run contains no active Modbus/SNMP IO point.")
            return StepResult(StepStatus.SKIP)

        # 1. Trigger the alarm FIRST
        runner.handler.trigger_alarm(ec.pt)
        ec.trigger_time = datetime.datetime.now()
        ec.trigger_ns = time.time_ns()
        ec.trigger_ok = True
        _log(ctx, f"Alarm triggered at {ec.trigger_time.strftime('%H:%M:%S.%f')[:-3]}")

        # 2. Start the frame sampler IMMEDIATELY after trigger
        _start_sampler(ctx, ec, runner, "sampler",
                       "FrameSampler started (running concurrently).")
        return StepResult(StepStatus.PASS)


@register(override=True)
class ResetAlarmAction:
    key = "reset_alarm"
    meta = CapabilityMeta(
        name="Reset Alarm", category="action", requires=["protocol"],
        description="Send the reset/normalize signal via the configured protocol, "
                    "then start the normalization sampler immediately.")

    def execute(self, ctx) -> StepResult:
        ec = getattr(ctx, "exec", None)
        runner = getattr(ctx, "runner", None)
        if ec is None or runner is None or not getattr(ec, "pt", None):
            _log(ctx, "SKIPPED: Standalone run contains no active Modbus/SNMP IO point.")
            return StepResult(StepStatus.SKIP)

        # 1. Reset the alarm FIRST
        runner.handler.reset_alarm(ec.pt)
        ec.reset_ns = time.time_ns()
        ec.reset_ok = True
        _log(ctx, "Alarm reset.")

        # 2. Start the normalization sampler IMMEDIATELY after reset
        _start_sampler(ctx, ec, runner, "norm_sampler",
                       "Normalization sampler started (running concurrently).")
        return StepResult(StepStatus.PASS)
