"""
Custom verification capabilities (P3.2):

  - verify_alarm_panel_custom : a standalone alarm-panel check whose expected
    values come from the step's own params (falling back to the IO point).
  - verify_custom             : the asset-binding check (TEXT / IMAGE / HYBRID)
    via iscs_assets.BindingExecutor.

Both read the step (ctx.proc) for their configuration, so they show the pattern
for capabilities that are parameterised by the step rather than the IO point.
"""
from types import SimpleNamespace

from iscs_core import register, CapabilityMeta, StepResult, StepStatus


@register(override=True)
class VerifyAlarmPanelCustomCapability:
    key = "verify_alarm_panel_custom"
    meta = CapabilityMeta(
        name="Verify Alarm Panel (Custom)",
        category="verification",
        description="Standalone alarm-panel check using step-provided expected values.",
        requires=["verifier"],
    )

    def execute(self, ctx) -> StepResult:
        ec      = getattr(ctx, "exec", None)
        proc    = getattr(ctx, "proc", None)
        log     = getattr(ctx, "log", None) or (lambda _m: None)
        runner  = getattr(ctx, "runner", None)
        backend = getattr(runner, "verifier", None) if runner is not None else None
        if ec is None or backend is None or proc is None:
            return StepResult(StepStatus.SKIP, message="No verifier/context available.")

        params = getattr(proc, "params", {}) or {}
        custom = {}
        for k, pk in (("color", "expected_color"), ("identifier", "expected_identifier"),
                      ("severity", "expected_severity")):
            if pk in params:
                custom[k] = params[pk]
        expected = custom if custom else ec.expected_alarm

        log("Standalone alarm panel check...")
        results = backend.verify_alarm_panel(
            expected, ec.sc_dir,
            point_idx    = ec.point_idx,
            trigger_time = None,
            file_suffix  = params.get("file_suffix", "alarm_panel_custom"),
            sampler      = None,
            trigger_ns   = None,
        )
        failed = any(getattr(r, "status", "") == "FAIL" for r in results)
        passed = sum(1 for r in results if getattr(r, "status", "") == "PASS")
        ss     = next((r.screenshot for r in results if getattr(r, "screenshot", "")), "")
        log(f"-> {'FAIL' if failed else 'PASS'}  ({passed}/{len(results)} checks passed)")
        return StepResult(StepStatus.FAIL if failed else StepStatus.PASS,
                          screenshot=ss, data={"verify_results": results})


@register(override=True)
class VerifyCustomCapability:
    key = "verify_custom"
    meta = CapabilityMeta(
        name="Verify Custom (Asset Binding)",
        category="verification",
        description="Asset-bound TEXT/IMAGE/HYBRID check via the binding system.",
        requires=["assets"],
    )

    def execute(self, ctx) -> StepResult:
        proc = getattr(ctx, "proc", None)
        log  = getattr(ctx, "log", None) or (lambda _m: None)

        try:
            from iscs_assets import BindingExecutor, StepBinding
        except Exception:
            log("SKIPPED: iscs_assets module not available")
            return StepResult(StepStatus.SKIP)

        binding_dict = getattr(proc, "binding", None) if proc is not None else None
        if not binding_dict:
            log("SKIPPED: step has no binding configured")
            return StepResult(StepStatus.SKIP)

        try:
            binding = StepBinding.from_dict(binding_dict)
        except Exception as e:
            log(f"SKIPPED: could not parse binding — {e}")
            return StepResult(StepStatus.SKIP)

        log(f"Executing asset binding [{binding.type}] "
            f"asset={binding.asset_id!r} region={binding.region_id!r}")
        result = BindingExecutor().execute(binding)

        status_str = result.get("status", "FAIL")
        msg        = result.get("message", "")
        expected   = result.get("expected", "")
        actual     = result.get("actual", "")
        score      = result.get("score", 0.0)

        log(f"-> {status_str}  {msg}")
        if expected or actual:
            log(f"   expected={expected!r}  actual={actual!r}  score={score:.3f}")

        vr = SimpleNamespace(status=status_str, step=getattr(proc, "name", "Custom Check"),
                             message=msg, expected=expected, actual=actual, screenshot="")

        if status_str == "SKIP" or binding.on_fail == "skip":
            status = StepStatus.SKIP
        elif status_str == "PASS":
            status = StepStatus.PASS
        else:
            status = StepStatus.FAIL
        return StepResult(status, message=msg, data={"verify_results": [vr]})
