"""
Reference plugin — copy this file to add a new action capability.

It is NOT auto-loaded by the app (nothing imports `plugins/`). It is surfaced
only when discovery runs, e.g. `discover_directory("plugins/actions")`, at which
point the `@register()` decorator below adds it to the registry under its `key`.

Being a no-op, it is safe to discover anywhere: it never touches the screen,
protocol, or filesystem.
"""
from iscs_core import register, CapabilityMeta, StepResult, StepStatus


@register()
class ExampleNoOpAction:
    key = "example_noop"
    meta = CapabilityMeta(
        name="Example No-Op",
        category="action",
        description="Reference plugin (key not in ProcedureType). Demonstrates P6.3: "
                    "a brand-new step type that's addable, saves/loads, and runs via the registry.",
        params_schema={"message": ""},
        addable=True,     # appears in the Add-Step palette (proves arbitrary plugin keys work)
    )

    def execute(self, ctx) -> StepResult:
        # Capabilities read what they need off the execution context defensively,
        # so the same class works under the legacy bridge and future contexts.
        proc = getattr(ctx, "proc", None)
        message = ""
        if proc is not None:
            message = (getattr(proc, "params", {}) or {}).get("message", "")

        log = getattr(ctx, "log", None)
        if callable(log):
            log(f"example_noop ran (message={message!r})")

        return StepResult(StepStatus.PASS, message=message or "no-op")
