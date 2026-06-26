"""
Result-domain value objects.

Currently hosts ``VerifyResult`` (one verification sub-check outcome). The flow
result types (``ProcedureResult``, ``ExecutionTrace``) join here in a later M2.1
sub-step. Domain value objects: no UI dependency. Relocated verbatim from ``baru``
(M2.1); ``baru`` re-exports it as a shim.
"""
from __future__ import annotations


class VerifyResult:
    """Holds the result of one verification step (alarm panel, list, inspector)."""

    def __init__(self, step: str, status: str, msg: str = "", screenshot: str = ""):
        self.step = step
        self.status = status
        self.msg = msg
        self.screenshot = screenshot

    def to_dict(self):
        return {"step": self.step, "status": self.status, "msg": self.msg,
                "screenshot": self.screenshot}
