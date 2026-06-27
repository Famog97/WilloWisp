"""
core/services/import_service.py  (M3.3 — relocated from iscs_workflow)

Default-flow generation: builds a smart default ProcedureFlow from a scenario's
zones + navigation coords + IO list. Pure — uses only the core flow domain model.
No UI/engine dependency. iscs_workflow re-exports auto_register_procedures as a shim.
"""
from __future__ import annotations

import copy

from core.domain.flow import (
    Procedure, ProcedureType, ProcedureCategory, IOGroup, ProcedureFlow,
    _next_io_id, _next_step_id,
)


def auto_register_procedures(sc, zones_dict: dict, nav: dict) -> ProcedureFlow:
    """
    Build a smart default ProcedureFlow from a scenario's existing config.

    This is called once per scenario run when no saved flow is available, or
    can be called to regenerate defaults after a scenario config change.

    Parameters
    ----------
    sc          : Scenario-like object (has .iscs_points, .card_cfg, etc.)
    zones_dict  : dict[str, Zone]  – merged zones for the scenario
    nav         : dict             – navigation coordinates from card_cfg

    Returns
    -------
    ProcedureFlow with sensible default steps pre-populated.
    """
    procs: List[Procedure] = []
    order = 10  # step counter (increments by 10 so users can insert between)

    def _xy(key: str) -> Tuple[int, int]:
        return nav.get(key, {}).get("x", 0), nav.get(key, {}).get("y", 0)

    has_points      = bool(getattr(sc, "iscs_points", []))
    has_alarm_panel = "alarm_panel"    in zones_dict
    has_alarm_list  = "alarm_list"     in zones_dict
    has_event_list  = "event_list"     in zones_dict
    has_equip_page  = "equipment_page" in zones_dict
    hm_x, hm_y     = _xy("home_btn")
    al_x, al_y     = _xy("alarm_list_btn")
    ev_x, ev_y     = _xy("event_list_btn")
    rc_x, rc_y     = _xy("rightclick_row1")
    pg_x, pg_y     = _xy("rightclick_page_btn")
    has_home        = (hm_x != 0 or hm_y != 0)
    has_al_nav      = (al_x != 0 or al_y != 0)
    has_ev_nav      = (ev_x != 0 or ev_y != 0)
    has_equip_nav   = (rc_x != 0 and rc_y != 0 and pg_x != 0 and pg_y != 0)

    # ── 1. Trigger Alarm ─────────────────────────────────────────────────────
    if has_points:
        procs.append(Procedure(
            proc_type   = ProcedureType.TRIGGER_ALARM,
            category    = ProcedureCategory.ACTION,
            name        = "Trigger Alarm",
            order       = order,
            description = "Send alarm signal via configured protocol (Modbus/SNMP).",
        ))
        order += 10

    # ── 2. Verify Alarm Panel ────────────────────────────────────────────────
    if has_alarm_panel:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_ALARM_PANEL,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Alarm Panel",
            order       = order,
            description = "OCR + color check on the alarm panel zone after trigger.",
            depends_on  = ["Trigger Alarm"],
        ))
        order += 10

    # ── 3. Navigate → Alarm List ─────────────────────────────────────────────
    if has_home or has_al_nav:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_ALARM_LIST,
            category    = ProcedureCategory.ACTION,
            name        = "Navigate to Alarm List",
            order       = order,
            enabled     = has_al_nav,
            params      = {"home_x": hm_x, "home_y": hm_y,
                           "al_x": al_x,   "al_y": al_y},
            description = "Click Home then Alarm List nav button.",
        ))
        order += 10

    # ── 4. Verify Alarm List ─────────────────────────────────────────────────
    if has_alarm_list:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_ALARM_LIST,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Alarm List",
            order       = order,
            enabled     = has_al_nav,
            description = "OCR + color check on the alarm list zone.",
            depends_on  = ["Navigate to Alarm List"],
        ))
        order += 10

    # ── 5. Navigate → Event List ─────────────────────────────────────────────
    if has_home or has_ev_nav:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_EVENT_LIST,
            category    = ProcedureCategory.ACTION,
            name        = "Navigate to Event List",
            order       = order,
            enabled     = has_ev_nav,
            params      = {"home_x": hm_x, "home_y": hm_y,
                           "ev_x": ev_x,   "ev_y": ev_y},
            description = "Click Home then Event List nav button.",
        ))
        order += 10

    # ── 6. Verify Event List ─────────────────────────────────────────────────
    if has_event_list:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_EVENT_LIST,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Event List",
            order       = order,
            enabled     = has_ev_nav,
            description = "OCR + color check on the event list zone.",
            depends_on  = ["Navigate to Event List"],
        ))
        order += 10

    # ── 7. Navigate → Equipment Page ─────────────────────────────────────────
    if has_equip_nav or has_equip_page:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_EQUIP_PAGE,
            category    = ProcedureCategory.ACTION,
            name        = "Navigate to Equipment Page",
            order       = order,
            enabled     = has_equip_nav,
            params      = {"home_x": hm_x, "home_y": hm_y,
                           "rc_x": rc_x,   "rc_y": rc_y,
                           "pg_x": pg_x,   "pg_y": pg_y},
            description = "Click Home, right-click alarm row, open equipment page.",
        ))
        order += 10

    # ── 8. Verify Equipment Page ─────────────────────────────────────────────
    if has_equip_page:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_EQUIP_PAGE,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Equipment Page",
            order       = order,
            enabled     = has_equip_nav,
            description = "OCR check on the equipment detail page.",
            depends_on  = ["Navigate to Equipment Page"],
        ))
        order += 10

    # ── 9. Navigate Home (pre-reset) ─────────────────────────────────────────
    if has_home:
        procs.append(Procedure(
            proc_type   = ProcedureType.NAVIGATE_HOME,
            category    = ProcedureCategory.ACTION,
            name        = "Return to Home",
            order       = order,
            description = "Click Home button to return to main view before reset.",
            params      = {"home_x": hm_x, "home_y": hm_y},
        ))
        order += 10

    # ── 10. Reset Alarm ──────────────────────────────────────────────────────
    if has_points:
        procs.append(Procedure(
            proc_type   = ProcedureType.RESET_ALARM,
            category    = ProcedureCategory.ACTION,
            name        = "Reset Alarm",
            order       = order,
            description = "Send reset/normalize signal via configured protocol.",
        ))
        order += 10

    # ── 11. Verify Normalized State ──────────────────────────────────────────
    if has_alarm_panel:
        procs.append(Procedure(
            proc_type   = ProcedureType.VERIFY_NORMALIZE,
            category    = ProcedureCategory.VERIFICATION,
            name        = "Verify Normalize State",
            order       = order,
            description = "OCR + color check that the alarm panel returned to normal.",
            depends_on  = ["Reset Alarm"],
        ))
        order += 10

    flow = ProcedureFlow(procs)

    # ── Build IO group tree from imported points ──────────────────────────
    points = getattr(sc, "iscs_points", []) or []
    if points:
        step_counter = [0]
        for pt in points:
            pid   = pt.get("point_id", "")
            equip = pt.get("equipment_description", pt.get("equip_desc", ""))
            attr  = pt.get("attribute_description",  pt.get("attr_desc",  ""))
            lbl   = f"{equip}: {attr}".strip(": ") if (equip or attr) else pid

            group = IOGroup(
                io_id    = _next_io_id(),
                point_id = pid,
                label    = lbl,
            )
            # Clone the shared procs template into this IO group
            # Each step gets a unique step_id for stable referencing
            import copy
            for p in procs:
                clone = copy.deepcopy(p)
                clone.step_id = _next_step_id()
                group.steps.append(clone)
            flow.add_io_group(group)

    return flow
