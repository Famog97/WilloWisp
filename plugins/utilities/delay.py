"""
Delay capability — first real capability ported out of the engine (Phase 3 / B1).

Ported verbatim from ProcedureRunner._exec_delay. Registered with override=True so
it SUPERSEDES the legacy "delay" adapter once discovered, demonstrating the whole
point of the architecture: a dropped-in file replaces built-in behavior by key,
with no change to the engine, dispatcher, enum, UI, or reports.
"""
from iscs_core import register, CapabilityMeta, StepResult, StepStatus


@register(override=True)
class DelayCapability:
    key = "delay"
    meta = CapabilityMeta(
        name="Delay",
        category="utility",
        description="Wait a fixed number of seconds (interruptible by Stop).",
        params_schema={"delay_sec": {"type": "number", "default": 1.0}},
    )

    def execute(self, ctx) -> StepResult:
        proc = getattr(ctx, "proc", None)
        params = (getattr(proc, "params", {}) or {}) if proc is not None else {}
        try:
            delay = float(params.get("delay_sec", 1.0))
        except (TypeError, ValueError):
            delay = 1.0

        log = getattr(ctx, "log", None)
        if callable(log):
            log(f"Waiting {delay:.1f}s…")

        # Use the runner's interruptible sleep so Stop still aborts the wait —
        # exactly as the legacy _exec_delay did. Fall back to time.sleep when no
        # runner is present (e.g. a standalone/unit context).
        runner = getattr(ctx, "runner", None)
        if runner is not None and hasattr(runner, "_sleep"):
            runner._sleep(delay)
        else:
            import time
            time.sleep(delay)

        return StepResult(StepStatus.PASS)
