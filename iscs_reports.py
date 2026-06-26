"""
iscs_reports.py — M2.5 compatibility shim.

The reporting module was relocated to ``core/services/report_service.py`` (the
Hexagonal core-services layer). This file re-exports its public surface so all
existing ``from iscs_reports import ReportManager`` imports keep working. Retired
in M6.
"""
from core.services.report_service import ReportManager, _size_label  # noqa: F401
