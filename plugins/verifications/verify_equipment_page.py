"""
Verify Equipment Page — verification capability (P3.2), ported from
_exec_verify_equip_page. Delegates to the backend's verify_inspector and prefixes
step names with "equipment/" for the report.
"""
from iscs_core import register, CapabilityMeta, StepResult, StepStatus


@register(override=True)
class VerifyEquipmentPageCapability:
    key = "verify_equipment_page"
    meta = CapabilityMeta(
        name="Verify Equipment Page",
        category="verification",
        description="OCR check on the equipment detail page.",
        requires=["verifier"],
    )

    def execute(self, ctx) -> StepResult:
        ec      = getattr(ctx, "exec", None)
        log     = getattr(ctx, "log", None) or (lambda _m: None)
        runner  = getattr(ctx, "runner", None)
        backend = getattr(runner, "verifier", None) if runner is not None else None

        if ec is None or backend is None:
            return StepResult(StepStatus.SKIP, message="No verifier/context available.")

        eq_zone = (getattr(ec, "zones_dict", {}) or {}).get("equipment_page")
        if not eq_zone:
            return StepResult(StepStatus.SKIP)

        results = backend.verify_inspector(
            ec.expected_alarm, eq_zone, ec.sc_dir, point_idx=ec.point_idx,
        )
        for r in results:
            step = getattr(r, "step", None)
            if step is not None:
                r.step = "equipment/" + step

        failed = any(getattr(r, "status", "") == "FAIL" for r in results)
        log(f"→ {'FAIL' if failed else 'PASS'}")
        return StepResult(StepStatus.FAIL if failed else StepStatus.PASS,
                          data={"verify_results": results})
