"""
Verify Normalize State — verification capability (P3.2), ported from
ProcedureRunner._exec_verify_normalize.

Same backend (ISCSVerifier.verify_alarm_panel) as Verify Alarm Panel, but checks
the NORMALIZED state after reset: different expected values, the normalize
sampler, no trigger_time, and the per-check step names are re-tagged
"alarm_panel/…" → "normalize/…" so the report maps them to the normalize column
(exactly as the legacy executor did).
"""
from iscs_core import register, CapabilityMeta, StepResult, StepStatus


@register(override=True)
class VerifyNormalizeCapability:
    key = "verify_normalize"
    meta = CapabilityMeta(
        name="Verify Normalize State",
        category="verification",
        description="OCR + colour check that the alarm panel returned to normal after reset.",
        requires=["verifier"],
    )

    def execute(self, ctx) -> StepResult:
        ec      = getattr(ctx, "exec", None)
        log     = getattr(ctx, "log", None) or (lambda _m: None)
        runner  = getattr(ctx, "runner", None)
        backend = getattr(runner, "verifier", None) if runner is not None else None

        if ec is None or backend is None:
            log("SKIPPED: no verification backend / context available.")
            return StepResult(StepStatus.SKIP, message="No verifier/context available.")

        log(f"Checking NORMALIZE state (v{getattr(ec, 'reset_idx', '?')})…")
        results = backend.verify_alarm_panel(
            ec.expected_norm, ec.sc_dir,
            point_idx    = ec.point_idx,
            trigger_time = None,
            file_suffix  = "alarm_panel_normalize",
            sampler      = ec.norm_sampler,
            trigger_ns   = ec.reset_ns,
        )

        # Re-tag step names to "normalize/…" (matches existing report field mapping).
        for r in results:
            step = getattr(r, "step", None)
            if step:
                r.step = step.replace("alarm_panel/", "normalize/")

        failed = any(getattr(r, "status", "") == "FAIL" for r in results)
        log(f"→ {'FAIL' if failed else 'PASS'}")
        return StepResult(
            StepStatus.FAIL if failed else StepStatus.PASS,
            data={"verify_results": results},
        )
