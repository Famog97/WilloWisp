"""
Verification backend contract (FR-13).

A verification *capability* owns the orchestration (when to run, how to interpret
the outcome); a *backend* owns the actual primitive — OCR + colour + datetime
checks on a screen region. Splitting them lets a capability swap backends (today
the screen-grab + Tesseract verifier; tomorrow a vision-LLM) without rewriting the
capability.

This is a structural Protocol: the existing baru.ISCSVerifier already satisfies it
(its `verify_alarm_panel` has this exact signature), so no change is needed there —
the capability simply treats `runner.verifier` as a VerificationBackend.
"""
from __future__ import annotations

from typing import Any, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class VerificationBackend(Protocol):
    def verify_alarm_panel(
        self,
        expected: dict,
        sc_dir: Any,
        *,
        point_idx: int = 0,
        trigger_time: Optional[Any] = None,
        file_suffix: str = "",
        sampler: Any = None,
        trigger_ns: Optional[int] = None,
    ) -> List[Any]:
        """Verify a panel region against `expected`, saving evidence under
        `sc_dir`. Returns a list of per-check result objects, each with at least
        `.status` ("PASS"/"FAIL"/"SKIP") and an optional `.screenshot` path."""
        ...

    def verify_list(self, list_type: str, expected: dict, zone: Any, sc_dir: Any,
                    *, point_idx: int = 0, sampler: Any = None,
                    trigger_ns: Optional[int] = None) -> List[Any]:
        """Verify a scrolling list region (alarm_list / event_list)."""
        ...

    def verify_inspector(self, expected: dict, zone: Any, sc_dir: Any,
                         *, point_idx: int = 0) -> List[Any]:
        """Verify the equipment/inspector detail page."""
        ...
