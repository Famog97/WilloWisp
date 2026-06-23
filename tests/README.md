# Tests

Phase-0 unit/characterization tests for WilloWisp. These **lock in current
behavior** of the pure-logic, no-hardware parts of the framework, so the planned
plugin/registry migration (see [`../ARCHITECTURE_DESIGN.md`](../ARCHITECTURE_DESIGN.md))
can be verified to preserve behavior.

All tests run **without** a SCADA screen, Modbus/SNMP device, Tesseract, or a
Tkinter event loop.

## Running

Run from the project root (the folder that contains `pyproject.toml`, `tests/`,
and the `iscs_*` modules):

```bash
python -m pytest tests/
python -m pytest tests/ -k reports        # one area
python -m pytest tests/ --cov             # with coverage + the fail_under gate
```

`pyproject.toml` (pytest + coverage config) and `conftest.py` (puts the modules on
`sys.path`) both live at this root, so the suite is self-contained — copy the
folder anywhere and the commands above work unchanged.

**The `fail_under = 18` coverage gate is an anti-backsliding floor, not a quality
target.** The denominator is dominated by Tkinter dialogs and HTML generation that
can't be unit-tested without a display, so the absolute % is intentionally low.
Ratchet it up as the migration extracts pure logic out of the UI.

## What's covered

| File | Module under test | Contract locked in |
|---|---|---|
| `test_reports_normalize.py` | `iscs_reports.ReportManager.normalize_results` | The report **data contract**: result consolidation, rerun preservation, custom-check pass-through, failure categorization. (Future `ResultView`.) |
| `test_workflow_serialization.py` | `iscs_workflow` Procedure / IOGroup / ProcedureFlow | **Backward compatibility**: flow/template round-trip + graceful skip of unknown step types. |
| `test_assets_store.py` | `iscs_assets.AssetManager` | Asset ID generation, CRUD, JSON persistence, counter resumption across reload. |

## Conventions

- **Characterization first.** Assert *observed current* behavior, not idealized
  behavior — these are a safety net for refactoring, not a redesign.
- **Hermetic.** Anything that persists (assets) is pointed at a `tmp_path` and the
  singleton reset in a fixture; tests never touch real `iscs_assets.json`.
- When a test reveals a genuine bug, fix the bug and add a **regression test**
  named `test_..._does_not_crash` / describing the corrected behavior (see
  `test_flow_with_unknown_top_level_step_does_not_crash`).

## Good next targets (not yet covered)

- `iscs_workflow.auto_register_procedures` — default-flow generation from zones/IO.
- `ProtocolManager` registry behavior (needs decoupling from `baru.py`'s Tk import first).
- OCR string matching helpers (`_ocr_contains` / fuzzy) — pure, but currently live
  in `baru.py` alongside Tk imports.
