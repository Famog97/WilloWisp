"""
core/services/run_coordinator.py  (M3.4)

Headless run orchestration in pure core/. First occupant: generate_points (the
grid/sequence click-point generator, relocated from baru) — pure geometry over a
monitor + zones, no UI/OS deps. SuiteRunner is relocated here in a following slice.
"""
from __future__ import annotations


def generate_points(mode, monitor: Monitor, spacing: int, zones: list):
    valid, all_pts = [], []
    if mode == "iscs": 
        return valid, all_pts
        
    if mode == "grid":
        has_include = any(z.zone_type == "include" for z in zones)
        for y in range(monitor.y + spacing, monitor.y + monitor.height, spacing):
            for x in range(monitor.x + spacing, monitor.x + monitor.width, spacing):
                all_pts.append((x, y))
                if any(z.contains(x, y) for z in zones if z.zone_type == "exclude"): continue
                if has_include and not any(z.contains(x, y) for z in zones if z.zone_type == "include"): continue
                valid.append({"x": x, "y": y, "label": "grid_pt", "zone": None})
    elif mode == "sequence":
        for i, z in enumerate([z for z in zones if z.zone_type == "target"]):
            valid.append({"x": z.cx, "y": z.cy, "label": f"Target_{i+1}", "zone": z})
            all_pts.append((z.cx, z.cy))
    return valid, all_pts
