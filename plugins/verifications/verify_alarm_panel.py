"""
Verify Alarm Panel — first verification decomposed out of the engine (P3.2).

This capability owns the ORCHESTRATION previously in
ProcedureRunner._exec_verify_alarm_panel (skip check, run, interpret status,
pick a screenshot, log). The actual OCR/colour/datetime work stays in
ISCSVerifier — accessed here as a VerificationBackend (FR-13), so the heavy,
live-validated logic is unchanged and a different backend could be swapped in
later without touching this capability.

Registered with override=True so it supersedes the legacy "verify_alarm_panel"
adapter once discovered.
"""
from iscs_core import register, CapabilityMeta, StepResult, StepStatus


@register(override=True)
class VerifyAlarmPanelCapability:
    key = "verify_alarm_panel"
    meta = CapabilityMeta(
        name="Verify Alarm Panel",
        category="verification",
        description="OCR + colour check on the alarm panel zone after trigger.",
        requires=["verifier"],
    )

    def execute(self, ctx) -> StepResult:
        ec      = getattr(ctx, "exec", None)            # the ExecContext for this point
        log     = getattr(ctx, "log", None) or (lambda _m: None)
        runner  = getattr(ctx, "runner", None)
        backend = getattr(runner, "verifier", None) if runner is not None else None

        if ec is None or backend is None:
            log("SKIPPED: no verification backend / context available.")
            return StepResult(StepStatus.SKIP, message="No verifier/context available.")

        if not getattr(ec, "expected_alarm", None):
            log("SKIPPED: No expected point state loaded for verification.")
            return StepResult(StepStatus.SKIP)

        log(f"Checking TRIGGER state (v{getattr(ec, 'trigger_idx', '?')})…")
        results = backend.verify_alarm_panel(
            ec.expected_alarm, ec.sc_dir,
            point_idx    = ec.point_idx,
            trigger_time = ec.trigger_time,
            file_suffix  = "alarm_panel_trigger",
            sampler      = ec.sampler,
            trigger_ns   = ec.trigger_ns,
        )

        failed = any(getattr(r, "status", "") == "FAIL" for r in results)
        passed = sum(1 for r in results if getattr(r, "status", "") == "PASS")
        ss     = next((r.screenshot for r in results if getattr(r, "screenshot", "")), "")
        log(f"→ {'FAIL' if failed else 'PASS'}  ({passed}/{len(results)} checks passed)")

        return StepResult(
            StepStatus.FAIL if failed else StepStatus.PASS,
            screenshot=ss,
            data={"verify_results": results},
        )
