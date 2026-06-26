"""
Scenario-domain value objects.

Currently hosts ``Monitor`` (a physical display descriptor). ``Scenario`` and
``SuiteCard`` join here in a later M2.1 sub-step. Domain value objects: no UI
dependency. Relocated verbatim from ``baru`` (M2.1); ``baru`` re-exports them.
"""
from __future__ import annotations

import re

from core.domain.zone import Zone
from core.domain.flow import ProcedureFlow


class Monitor:
    def __init__(self, index, x, y, width, height, name=""):
        self.index, self.x, self.y, self.width, self.height = index, x, y, width, height
        self.name = name or f"Monitor {index + 1}"
        match = re.search(r'\d+', self.name)
        self.display_num = int(match.group()) if match else (index + 1)

    @property
    def label(self):
        primary = " ★" if self.x == 0 and self.y == 0 else ""
        return f"Display {self.display_num}{primary}  —  {self.width}×{self.height}  @ ({self.x}, {self.y})"


class Scenario:
    def __init__(self, name, mode, zones, monitor_info, grid_spacing, iscs_points=None):
        self.name         = name
        self.mode         = mode
        self.zones        = zones
        self.monitor_info = monitor_info
        self.grid_spacing = grid_spacing
        self.iscs_points  = iscs_points or []
        self.card_cfg     = {}
        self.card_loop    = 1      # per-card loop count
        self.card_infinite = False  # per-card infinite loop
        # Per-page zones for ISCS mode: {"Page Name": {"alarm_panel": Zone, ...}, ...}
        # "Global" key holds zones not tied to any specific page
        self.zones_per_page = {}
        # Configurable procedure flow — populated lazily by build_runner_from_scenario()
        # or loaded from suite JSON.  None = "use auto-registration on next run".
        self.procedure_flow = None

    def to_dict(self):
        zpp_serial = {}
        for page, zt_dict in self.zones_per_page.items():
            zpp_serial[page] = {zt: z.to_dict() for zt, z in zt_dict.items() if z is not None}
        d = {
            "name":           self.name,
            "mode":           self.mode,
            "monitor":        self.monitor_info,
            "grid_spacing":   self.grid_spacing,
            "zones":          [z.to_dict() for z in self.zones],
            "zones_per_page": zpp_serial,
            "iscs_points":    self.iscs_points,
            "card_cfg":       self.card_cfg,
            "card_loop":      self.card_loop,
            "card_infinite":  self.card_infinite,
        }
        # Persist the procedure flow if it has been customised
        if self.procedure_flow is not None:
            d["procedure_flow"] = self.procedure_flow.to_dict()
        return d

    @classmethod
    def from_dict(cls, d):
        zones = [Zone.from_dict(z) for z in d.get("zones", [])]
        # 40 = the built-in default grid spacing (DEFAULT_CONFIG); this fallback is
        # only hit if a saved scenario omits grid_spacing (real saves always include it).
        sc = cls(d["name"], d["mode"], zones, d["monitor"], d.get("grid_spacing", 40), d.get("iscs_points", []))
        sc.card_cfg = d.get("card_cfg", {})
        sc.card_loop = d.get("card_loop", 1)
        sc.card_infinite = d.get("card_infinite", False)
        zpp = {}
        for page, zt_dict in d.get("zones_per_page", {}).items():
            zpp[page] = {zt: Zone.from_dict(zd) for zt, zd in zt_dict.items()}
        sc.zones_per_page = zpp
        # Restore saved procedure flow if present
        if "procedure_flow" in d:
            try:
                sc.procedure_flow = ProcedureFlow.from_dict(d["procedure_flow"])
            except Exception:
                sc.procedure_flow = None
        return sc


class SuiteCard:
    """
    Lightweight config object that ISCS_Engine reads.
    Built from a Scenario's card_cfg dict so the engine stays decoupled from the UI.
    """
    def __init__(self, name: str, zones: list, protocol: str,
                 subsystem_tab_x: int = 0, subsystem_tab_y: int = 0,
                 left_nav_pages: list = None,
                 alarm_list_x: int = 0, alarm_list_y: int = 0,
                 event_list_x: int = 0, event_list_y: int = 0,
                 home_x: int = 0, home_y: int = 0,
                 zones_per_page: dict = None,
                 rightclick_row1_x: int = 0, rightclick_row1_y: int = 0,
                 rightclick_page_btn_x: int = 0, rightclick_page_btn_y: int = 0):
        self.name            = name
        self.zones           = zones or []
        self.protocol        = protocol or "MODBUS"
        self.subsystem_tab_x = subsystem_tab_x
        self.subsystem_tab_y = subsystem_tab_y
        self.left_nav_pages  = left_nav_pages or []
        self.alarm_list_x    = alarm_list_x
        self.alarm_list_y    = alarm_list_y
        self.event_list_x    = event_list_x
        self.event_list_y    = event_list_y
        self.home_x          = home_x
        self.home_y          = home_y
        self.zones_per_page  = zones_per_page or {}
        # Right-click navigation to equipment page
        self.rightclick_row1_x     = rightclick_row1_x
        self.rightclick_row1_y     = rightclick_row1_y
        self.rightclick_page_btn_x = rightclick_page_btn_x
        self.rightclick_page_btn_y = rightclick_page_btn_y

    @classmethod
    def from_card_cfg(cls, name: str, zones: list, card_cfg: dict, zones_per_page: dict = None) -> "SuiteCard":
        """Build a SuiteCard from the dict produced by SuiteCardConfigDialog._save()."""
        nav  = card_cfg.get("navigation", {})
        def _xy(key): return nav.get(key, {}).get("x", 0), nav.get(key, {}).get("y", 0)
        st_x, st_y  = _xy("subsystem_tab")
        al_x, al_y  = _xy("alarm_list_btn")
        ev_x, ev_y  = _xy("event_list_btn")
        hm_x, hm_y  = _xy("home_btn")
        rc1_x, rc1_y   = _xy("rightclick_row1")
        rcb_x, rcb_y   = _xy("rightclick_page_btn")
        proto = card_cfg.get("protocol", {}).get("type", "MODBUS")
        pages = nav.get("pages", [])
        return cls(
            name=name, zones=zones, protocol=proto,
            subsystem_tab_x=st_x, subsystem_tab_y=st_y,
            left_nav_pages=pages,
            alarm_list_x=al_x, alarm_list_y=al_y,
            event_list_x=ev_x, event_list_y=ev_y,
            home_x=hm_x, home_y=hm_y,
            zones_per_page=zones_per_page or {},
            rightclick_row1_x=rc1_x, rightclick_row1_y=rc1_y,
            rightclick_page_btn_x=rcb_x, rightclick_page_btn_y=rcb_y,
        )

    @classmethod
    def from_direct(cls, name: str, zones: list, protocol: str = "MODBUS", zones_per_page: dict = None) -> "SuiteCard":
        """Build a minimal SuiteCard when running directly (no suite card_cfg)."""
        return cls(name=name, zones=zones, protocol=protocol, zones_per_page=zones_per_page or {})
