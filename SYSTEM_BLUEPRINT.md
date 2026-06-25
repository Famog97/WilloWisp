# WilloWisp — System Blueprint (reconstruction spec)

A self-contained specification of **WilloWisp** (a.k.a. *ISCS AutoClick*) detailed
enough to **rebuild the application from scratch**. It describes purpose,
architecture, data models, file formats, algorithms, the step catalogue, the
plugin system, and every non-obvious rule. No other input is required.

> Conventions doc for contributors: [`CLAUDE.md`](CLAUDE.md). Design rationale:
> [`ARCHITECTURE_DESIGN.md`](ARCHITECTURE_DESIGN.md). Extension how-to:
> [`plugins/README.md`](plugins/README.md).

---

## 1. What the system is

A **single-machine Windows desktop GUI** (Python 3.x + Tkinter) that performs
**automated closed-loop testing of SCADA / ISCS alarm systems**. The machine
under test runs a SCADA HMI; WilloWisp drives it by:

1. **Triggering** a field alarm by writing to a Modbus register (WilloWisp *is*
   the Modbus TCP **server** the SCADA front-end polls),
2. **Watching the SCADA screen** (screen-grab + OCR + colour analysis on
   user-drawn zones) to confirm the alarm appears correctly,
3. **Resetting / normalizing** the point and confirming it clears,
4. capturing **evidence** (screenshots, optional per-card video),
5. producing **consolidated reports** (HTML dashboard + Excel, plus on-demand
   PDF/JSON and audience-specific templates).

It validates that a SCADA point shows the **right identifier, description, value,
severity, colour, blink behaviour, and timestamp** when alarmed, and returns to
normal when reset — across many IO points, looped, with automatic rerun-on-fail.

**Primary user flow:** import an IO list (Excel) → pick the monitor → draw zones /
configure navigation → auto-build a test flow → run a suite → review the report.

---

## 2. Tech stack & dependencies

- **Language/UI:** Python 3, Tkinter (desktop GUI; multi-window with overlays).
- **Required-ish:** none are hard — every dependency is import-guarded and the app
  degrades gracefully, disabling just the affected feature with a logged message.
- **Optional libraries** (feature → lib):
  - Screen control → `pyautogui` (`PYAUTOGUI_AVAILABLE`)
  - Screen capture / image → `Pillow` (`PIL_AVAILABLE`)
  - OCR → `pytesseract` + a **Tesseract** install (`TESSERACT_AVAILABLE`)
  - Template matching → `opencv-python` (`cv2`) + `numpy`
  - Modbus server → `pymodbus` (`PYMODBUS_AVAILABLE`)
  - Excel report → `pandas` + `openpyxl` (`PANDAS_AVAILABLE`)
  - Global hotkeys → `keyboard`
  - Monitor enumeration → `screeninfo`
  - PDF report → `fpdf2`
  - Video recording → recorder backend (`iscs_recorder`)
  - Frame sampling / visual anchoring → `iscs_Sampler_Anchor` (optional in-repo
    upgrade module; `UPGRADES_AVAILABLE`)
- **Tests:** `pytest` (hermetic — fakes/monkeypatch for screen/Modbus/OCR/Tk).

A startup **load manifest** prints what loaded / is unavailable / failed, and a
line confirming the capability registry covers all step types.

---

## 3. Entry point & startup sequence

`python baru.py` → `if __name__ == "__main__"`:

1. `_load_plugins()` — discover capability plugins from `plugins/{utilities,
   verifications,actions}` (each file self-registers); build the load manifest;
   log coverage.
2. `_wire_subscribers()` — subscribe the report subsystem (and recorder) to the
   `EventBus` (`SuiteCompleted` → generate reports).
3. `App().mainloop()` — the Tk root window.

At import time: load `config.json` over built-in `APP_CONFIG` defaults; initialize
Tesseract; register the Modbus protocol; auto-register legacy capability adapters
into the global registry (later superseded by plugins).

---

## 4. Domain glossary

| Term | Meaning |
|---|---|
| **IO point** | One SCADA field point under test: id, descriptions, Modbus payload, expected states. |
| **IO list / profile** | A set of IO points imported from an Excel sheet (column-mapped), stored in SQLite. |
| **Monitor** | A physical display (index, x, y, w, h) — coordinates are global across monitors. |
| **Zone** | A named rectangle on a monitor (`alarm_panel`, `alarm_list`, `event_list`, `equipment_page`; or grid `include`/`exclude`/`target`). |
| **Scenario** | A test definition: mode, zones, monitor, IO points, navigation config, optional flow. |
| **Suite / card** | A run unit. A *card* ≈ a configured scenario; a *suite* runs cards × loops. |
| **Procedure / step** | One action in a flow (trigger, verify, navigate, delay…), keyed by a string `proc_type`. |
| **ProcedureFlow** | An ordered tree: per-IO `IOGroup`s, each holding ordered `Procedure` steps. |
| **Capability** | The pluggable implementation of a step type (`key`, `meta`, `execute(ctx)->StepResult`). |
| **Asset / binding** | Reusable expected-text / reference-image / region; a `StepBinding` attaches them to a custom-verify step. |

---

## 5. Data models (exact fields)

### IO point (dict, also a SQLite row)
```
point_id, equipment_desc, location, attribute_desc, station_code, data_type,
alarm_list_desc,
payload : { fc, reg, bit }      # Modbus: function code, register, bit
states  : { <severity-or-state> : <value> }   # expected per-state values
```
At verify time an **expected** dict is derived: `{point_id, description, label,
severity, color}` where `color` comes from the **severity matrix**.

### Monitor
`index, x, y, width, height, name` (coords are absolute desktop space).

### Zone
`x1,y1,x2,y2` (normalized so x1<y2), `zone_type`, `label`, `monitor_index`.
Helpers: `width/height/cx/cy/contains(x,y)`. JSON: `{x1,y1,x2,y2,type,label,monitor_index}`.
**Named zone types** used by verification: `alarm_panel`, `alarm_list`,
`event_list`, `equipment_page`. **Grid zone types:** `include`, `exclude`, `target`.

### Scenario (a "card")
```
name, mode ("grid"|"sequence"|"iscs"), zones[Zone], monitor_info,
grid_spacing, iscs_points[IO point], card_cfg{}, card_loop(int), card_infinite(bool),
zones_per_page { "<Page>": { "<zone_type>": Zone } },   # per-page zones (iscs mode)
procedure_flow (ProcedureFlow | None)                    # None = auto-register on run
```

### SuiteCard (engine-facing view of `card_cfg`)
Navigation coordinates extracted from `card_cfg.navigation`: `subsystem_tab`,
`home_btn`, `alarm_list_btn`, `event_list_btn`, `rightclick_row1`,
`rightclick_page_btn`, plus `pages[]`; `protocol.type` (default "MODBUS");
`zones_per_page`.

### Procedure (one step)
```
proc_type(str key), category("action"|"verification"|"utility"), name,
enabled(bool, default True), order(int), params(dict), description,
depends_on[str names], step_id("STP_0001"), binding(StepBinding dict | None)
```

### IOGroup / ProcedureFlow
- `IOGroup`: `io_id("IO_0001")`, `point_id`, `label`, `steps[Procedure]`.
- `ProcedureFlow`: a flat `steps[]` template + `io_groups[]` (the per-point clones).
  Composite; serialized with a `schema_version` (chained migrators on load).

### ExecContext (per-point shared mutable state)
`point_id, pt(raw point), trigger_idx, reset_idx, expected_alarm, expected_norm,
trigger_ok, trigger_time, trigger_ns, reset_ok, reset_ns, sampler, norm_sampler,
resolved_bbox, anchor_mgr, zones_dict, sc_dir, point_idx, extra`.

### StepResult (capability return)
`status(PASS|FAIL|SKIP|ERROR), message, screenshot(path), data{}`. Verifications
put rows in `data["verify_results"]` (list of `VerifyResult`-shaped dicts:
`{step, status, msg, screenshot}`).

---

## 6. Persistence & file formats

All beside `baru.py` (the app dir), except evidence under `test_logs/`.

| File | Format | Contents |
|---|---|---|
| `config.json` | JSON | runtime config (see §16). Overrides `APP_CONFIG` defaults. `severity_matrix` is **never** loaded from JSON (tuples↔lists). |
| `iscs_assets.json` | JSON, schema-versioned | the asset library: `{schema_version, text_assets[], image_assets[], regions[], flow_templates[], counters}`. |
| `assets/images/` | files | reference images referenced by `ImageAsset.filename`. |
| `iscs_template.json` | JSON | saved suite/scenario definitions (cards, zones, flows). Schema-versioned. |
| `iscs_metadata.db` | SQLite | imported IO-list profiles + points (see schema below). |
| `test_logs/<suite_ts>/…` | dirs | evidence: per-loop/per-point screenshots, optional `card.mp4`, plus `Suite_Report.html`, the Excel workbook, and `suite_results.json`. |
| `suite_results.json` | JSON | the **raw** results list for one suite — re-renderable into any template offline (never re-run). A **list** of result dicts. |

### Asset dataclasses (in `iscs_assets.json`)
- `TextAsset{ id"TXT_0001", name, value(expected OCR text), description, created_at, updated_at }`
- `ImageAsset{ id"IMG_0001", name, filename, description, width, height, … }`
- `Region{ id"RGN_0001", name, x1,y1,x2,y2, monitor_index, description, … }`
- `FlowTemplate{ id"TPL_0001", name, description, steps[Procedure dicts], … }`
- IDs auto-increment per category, never reused.

### StepBinding (inside `Procedure.binding`)
`{ type:"TEXT"|"IMAGE"|"HYBRID", asset_id, image_asset_id(HYBRID), region_id,
threshold(0..1, default 0.85), on_fail:"fail"|"skip"|"warn" }`.

### SQLite schema (`iscs_metadata.db`)
```sql
profiles( id PK, name, source_file, sheet_name, file_hash, imported_at,
          point_count, column_map_json, UNIQUE(file_hash, sheet_name) )
io_points( id PK, profile_id FK→profiles ON DELETE CASCADE,
           point_id, equipment_desc, location, attribute_desc, station_code,
           data_type, alarm_list_desc, payload_json, states_json )
```
Columns are additively migrated (never dropped/renamed). `file_hash` = MD5 of the
source file, so re-importing the same sheet upserts.

### Result record (output of `ReportManager.normalize_results`)
Input = raw list (one dict per point-attempt). Output = one record per
`(loop_num, scenario_idx, point_id)`:
```
{ id, overall, loop_num, scenario_idx, scenario_name, screenshot,
  failure_category, failure_reason, steps[], sections[],
  failure_diagnostics, trigger_info, rerun_attempt,
  attempts[ {attempt, overall, screenshot, failure_category, failure_reason,
             steps[], failure_diagnostics, trigger_info} ] }
```
`steps[]` rows: `{name, status, message}` (+ custom-asset rows add
`expected, actual, asset_name, asset_id, is_custom:true}`). Raw is sorted ascending
by `rerun_attempt`, so later attempts overwrite top-level fields while **all**
attempts are retained.

**Failure categories:** `Custom Asset Mismatch`, `Color Miss`, `Timeout`,
`Datetime Out of Bounds`, `OCR Mismatch`, `Other`.

---

## 7. Step-type catalogue (19 built-ins)

Each is a Capability (`proc_type` value = registry key). Categories: **action**,
**verification**, **utility**. `params` are per-step.

| key | cat | params | behaviour |
|---|---|---|---|
| `trigger_alarm` | action | — | Modbus-write the point's alarm; record `trigger_time/ns`; start the frame sampler immediately. SKIP if no IO point. |
| `reset_alarm` | action | — | Modbus-write reset/normalize; record `reset_ns`; start the normalization sampler. |
| `navigate_home` | action | `home_x,home_y` | Click the Home button; wait `nav_wait_sec`. SKIP if coords 0. |
| `navigate_alarm_list` | action | `home_x/y, al_x/y` | Click Home (if set) then the Alarm-List button. |
| `navigate_event_list` | action | `home_x/y, ev_x/y` | Click Home then the Event-List button. |
| `navigate_equipment_page` | action | `home_x/y, rc_x/y, pg_x/y` | Click Home, **right-click** the alarm row, click the equipment-page button. |
| `verify_alarm_panel` | verification | — | Full alarm-panel verification (OCR id/desc/value/severity + colour/blink + datetime sync). See §10. depends_on Trigger. |
| `verify_normalize` | verification | — | Same as alarm-panel but for the cleared/normal state (re-tagged `normalize`). depends_on Reset. |
| `verify_alarm_list` | verification | — | OCR identifier + colour check on the `alarm_list` zone. |
| `verify_event_list` | verification | — | Same on the `event_list` zone. |
| `verify_equipment_page` | verification | — | OCR check on the `equipment_page` zone. |
| `delay` | utility | `delay_sec` | Interruptible sleep (Stop breaks it). |
| `screenshot` | utility | — | Grab + save a manual screenshot into the point's evidence dir. |
| `click` | action | `x,y,wait_after` | `pyautogui.click`. SKIP if no coords. |
| `right_click` | action | `x,y,wait_after` | `pyautogui.rightClick`. |
| `hotkey` | action | `keys` ("Ctrl+S"), `wait_after` | `pyautogui.hotkey(*parsed)`. |
| `type_text` | action | `text, click_first(bool), x, y, wait_after` | Type text; optionally click a field first (default off). |
| `verify_alarm_panel_custom` | verification | — | Alarm-panel verify variant for custom configs. |
| `verify_custom` | verification | `binding` | Asset-bound check via `BindingExecutor` (TEXT/IMAGE/HYBRID). See §11. |

Plugins may add **new** keys (a `_DynamicProcType`) without touching the enum; they
round-trip through save/load and run via the registry.

---

## 8. Execution model

```
SuiteRunner (worker thread)            # live screen + Modbus; one per run
  for each card:
    emit CardStarted (recorder starts)
    for loop in 1..card_loop (or ∞):
      for each IO point:
        ctx = ExecContext(point)
        ProcedureRunner.run_point(flow, ctx):
          for step in ordered, enabled steps honouring depends_on:
            _execute_procedure(step, ctx, sampler_ok):
              cap = registry.get(step.key)        # uniform contract
              result = cap.execute(LegacyExecContext(runner, step, ctx, sampler_ok, log))
              emit StepStarted/StepCompleted, Verification{Passed,Failed}
              # any exception → ERROR (per-step isolation)
        collect a raw result dict for the point-attempt
      if rerun-on-fail enabled and point FAILED: re-run the point (rerun_attempt++)
    emit CardCompleted (recorder stops)
  emit SuiteCompleted(results, dir, times) → ReportManager writes reports
```

Cross-step rules honoured by the runner: `enabled` (skip), `order` (sequence),
`depends_on` (skip a step whose named prerequisite didn't PASS), per-step
exception → `ERROR`. The registry is the **sole dispatch**; a vestigial legacy
`_exec_*` fallback exists only if `iscs_core` is unavailable (logs a ⚠ if hit).

**Run modes:** `SuiteRunner`/`ISCS_Engine` (the ISCS suite — trigger/verify/reset
loop, the primary mode), and `ClickEngine` (grid/sequence auto-click modes from
`generate_points`: `grid` = spaced points filtered by include/exclude zones;
`sequence` = centres of `target` zones).

**Events** (`iscs_core.events`, isolated delivery): `Suite/Card/IOPoint/Step
Started`+`Completed`, `Verification Passed/Failed`. Subscribers (reports, recorder,
future metrics/dashboard) react without the runner depending on them.

---

## 9. Protocol layer (Modbus)

WilloWisp runs a **pymodbus TCP server** (`ModbusProtocol`) bound to
`0.0.0.0:<modbus_port>` (default 502), `slave_id=1`, with `di/co/hr/ir` data
blocks of 10000 registers. The SCADA front-end connects as client and polls it.

Trigger/reset write the point's `payload {fc, reg, bit}` with value 1/0:
- `fc` 1 or 5 → set coil `reg` = bool(val)
- `fc` 2 → discrete input
- `fc` 4 → input register `reg` = val & 0xFFFF
- `fc` 3/6/16 (default) → **holding register bit-set/clear**: read `reg`, set/clear
  `bit`, write back masked to 16 bits.

`ProtocolManager` is a registry (`register_protocol("MODBUS", ModbusProtocol)`,
`get_protocol(name)` lazily instantiates + starts). New protocols (SNMP, …) plug
in the same way. `BaseProtocol` ABC: `start/stop/trigger_alarm/reset_alarm/check_health`.

---

## 10. Verification algorithms

### Severity matrix (state → display + colour)
```
"0": text "0", GREEN  (32,169,72)    # Normal
"1": text "1", RED    (255,0,0)      # Supercritical
"2": text "2", ORANGE (255,126,0)    # Critical
"3": text "3", YELLOW (255,255,0)    # Less critical
```
Blink "off" phase colour = **grey (189,189,189)**.

### `verify_alarm_panel(expected, …)` — the core check
1. **Poll** the `alarm_panel` zone (grab + OCR `block` layout, ~0.5s interval) up
   to `detection_duration_sec`, exiting early only when the **exact** identifier
   **and** value substrings are both on screen (avoids false early exits on noisy
   frames). Falls back to a final grab on timeout.
2. **Colour/blink:** if a frame `sampler` is available, `sampler.evaluate(target_rgb,
   trigger_ns, tolerance=35)` over the multi-frame buffer → `color_found`,
   `blink_detected`, and the first colour-positive frame as evidence. Without a
   sampler, take a short **burst** of grabs (`blink_burst_frames`≈8 over
   `blink_burst_sec`≈1s) and pass if the target colour appears in any frame (blink
   tolerant); keep the first colour-positive frame.
3. **Sub-checks** (each a `VerifyResult`, any FAIL fails the step):
   - **datetime:** regex a `DD/MM/YYYY HH:MM:SS`-style timestamp out of the OCR
     text; parse (several formats); compare to the trigger time; PASS if the
     SCADA-clock-vs-trigger delta ≤ `datetime_sync_limit_sec` (default 4s). Falls
     back to system clock if OCR found no timestamp.
   - **identifier:** `point_id` present (`_ocr_contains`, OCR-noise tolerant).
   - **description:** present via `_ocr_fuzzy_contains` (difflib ≥0.82), or SKIP if none.
   - **value/label:** present (`_ocr_contains`), or SKIP.
   - **severity:** for 1–2 char tokens use a word-boundary regex; if not found,
     re-OCR just the **right-hand cell** (crop right ~15%) with a **digit
     whitelist** (`run_digits`, psm 10) to read a lone digit reliably.
   - **colour:** `found_target` from step 2 (+ "blink detected" note if grey seen).
4. Save evidence `…_{file_suffix}_{PASS|FAIL}.png`; the first result row carries the
   screenshot path. `verify_normalize` reuses this with `file_suffix="normalize"`.

### `verify_list(list_type, …)` — alarm/event list zones
Grab the zone, OCR `tabular`; PASS identifier if `point_id` **or** `label` present;
colour via sampler or a single grab (`tolerance=35`). Saves a labelled screenshot.

### OCR pipeline (`iscs_OCR`)
- `analyze_image`: sample every 5th pixel; compute brightness/contrast/dark&white
  ratios + dark-red/blue ratios → decide invert / "totally dark".
- `preprocess`: adaptive — optional invert, grayscale, contrast/brightness enhance,
  light blur, and a binarize pass for high-contrast bright images.
- `run(img, layout)`: psm by layout — `single_line`=7, `tabular`=4, `sparse`=11,
  else 6; `--oem 3`.
- `run_digits`: upscale ×3, grayscale, `tessedit_char_whitelist=0123456789`,
  psm 10 (single char) / 7 (line).
- Text matching: `_ocr_canon` (lowercase; `o→0`, `l/i→1`, drop pipes & all
  non-alphanumerics); `_ocr_contains` = exact → case/space-insensitive →
  canonical substring; `_ocr_fuzzy_contains` = `_ocr_contains` then difflib whole
  string + sliding token window ≥ threshold (0.82).
- Colour match: `_color_present(img, rgb, tolerance)` scans colours (or sub-samples
  pixels) within per-channel tolerance (25 default, 35 for alarm colour).

`ISCSVerifier` is the verification backend (conforms to
`iscs_core.backends.VerificationBackend`); verification **capabilities** own the
orchestration (poll rules, step re-tags, status) and delegate pixel/OCR work to it.

---

## 11. Asset & custom-verify system

Reusable assets (text/image/region) live in `iscs_assets.json` via `AssetManager`
(singleton). A `verify_custom` step carries a `StepBinding` that links an expected
asset + a region. `BindingExecutor.execute(binding)`:
1. resolve region + asset(s); capture the region screenshot;
2. dispatch by `binding.type` to a registered **`BindingResolver`**:
   - **TEXT** — OCR the region (`sparse`); PASS if expected text ⊆ OCR (case-insensitive).
   - **IMAGE** — OpenCV template match (`matchTemplate TM_CCOEFF_NORMED`); when the
     template ≈ region size (degenerate), resize + whole-image normalized
     correlation instead; PASS if score ≥ `threshold`.
   - **HYBRID** — both TEXT and IMAGE must pass (composes the two registered resolvers).
3. returns `{status, message, expected, actual, score, asset_*}` → becomes a
   custom-check row in the report (`is_custom:true`).
`on_fail` controls FAIL vs SKIP on resolution/capture errors. New binding kinds =
register a resolver (no `BindingExecutor` edit).

---

## 12. Auto-flow generation

When a scenario has no saved `procedure_flow`, `auto_register_procedures(sc,
zones_dict, nav)` builds a default flow from what's configured (zones present + nav
coords set). Steps (order +10 each, so users can insert between):

1. **Trigger Alarm** — if there are IO points.
2. **Verify Alarm Panel** — if `alarm_panel` zone; depends_on Trigger.
3. **Navigate→Alarm List** — if home or alarm-list nav set (enabled only if its nav set).
4. **Verify Alarm List** — if `alarm_list` zone; depends_on nav.
5. **Navigate→Event List** / 6. **Verify Event List** — analogous.
7. **Navigate→Equipment Page** / 8. **Verify Equipment Page** — analogous (right-click nav).
9. **Return to Home** — if home set.
10. **Reset Alarm** — if IO points.
11. **Verify Normalize** — if `alarm_panel` zone; depends_on Reset.

Then each IO point gets a cloned copy of this step template (unique `step_id`s) in
its own `IOGroup`.

---

## 13. Reporting system (three layers + formats)

**Stable data layer:** `ReportManager.normalize_results(raw)` (§6) — the contract
every report binds to. `generate_reports()` writes the legacy `Suite_Report.html`,
an Excel workbook, and persists `suite_results.json`. It runs as a **subscriber**
to `SuiteCompleted` (with a safety-net fallback if no subscriber handled it).

**Pluggable layer (`iscs_report_templates.py`):**
- `ResultView{records, summary, meta}` — the immutable view (FR-30e).
- **Widgets** (`ReportWidget{key, consumes, render(view)}`, registry): `header`,
  `kpis`, `failures_by_category`, `failed_points`, `summary_line`, `audit_attempts`,
  `step_traces`. Self-rendering HTML fragments; enable/disable/reorder is config.
- **Templates** = an ordered `widgets` list per entry in `TEMPLATES`. Built-ins
  (picker order): **Legacy** (regenerates the original `Suite_Report.html`) → Audit →
  Engineering → Management → **Summary PDF** → **Results JSON**.
- **Format renderers:** HTML (widget compose), `render_pdf` (fpdf2; resets x to the
  left margin + `wrapmode=CHAR` to survive long tokens / many failed rows),
  `render_json`. Formats may differ in layout but draw from the same data (FR-30f).
- The **📊 picker** (`SuitePanel._open_report_picker`) renders any template from a
  run's `suite_results.json`, offline, no re-run. Non-list JSON input is rejected
  with a clear error.

**Failure summary** counts the categories from §6; HTML/Excel show per-point traces,
evidence thumbnails, the rerun history (all attempts), and KPIs.

---

## 14. Plugin / capability architecture (`iscs_core/`)

The execution core that makes step types pluggable:

- **`registry.py`** — `Capability` contract (`key`, `meta:CapabilityMeta`,
  `execute(ctx)->StepResult`), `CapabilityRegistry` (register/get/list/alias/
  manifest, duplicate-check), `@register(override=…)`, ambient `using_registry`,
  `StepResult`/`StepStatus`, global `registry`.
- **`discovery.py`** — `discover_directory/package/entry_points` import modules so
  their `@register` fires; optional `manifest=` records loaded/failed.
- **`events.py`** — `EventBus` (subscribe/publish, a failing subscriber never aborts
  a run) + the lifecycle event classes + global `bus`.
- **`container.py`** — `Container` DI resolver with lifetimes (exists + tested; not
  wired into live construction — deferred).
- **`backends.py`** — `VerificationBackend` protocol (ISCSVerifier conforms).
- **`manifest.py`** — `LoadManifest` (loaded/unavailable/failed + reason, `summary()`)
  + dependency probes (`register_dependency`, `importable`, `dependency_status`,
  `missing_requirements`) + `evaluate_requirements` (report, or `disable=True`).

**`CapabilityMeta`:** `name, category, params_schema{}, requires[], description,
addable(bool)`. `requires` are logical resources (`ocr`, `assets`, `verifier`, …)
checked against probes for graceful disable; `addable` shows the step in the UI
palette.

**Step contract (`ctx` passed to `execute`):** a `LegacyExecContext` bridge exposing
`ctx.proc` (the Procedure, `.params`), `ctx.exec` (the ExecContext: `.pt`,
`.resolved_bbox`, trigger/reset fields, samplers), `ctx.runner` (`.config`,
`.handler`, `.verifier`, `._sleep`), `ctx.log`, `ctx.sampler_ok`. Capabilities read
defensively (`getattr`) so they stay unit-testable.

**Extending:** drop a file in `plugins/<category>/` with `@register()`
(`override=True` to supersede a built-in). Plugins are discovered at startup. Full
guide incl. binding resolvers / report widgets / dependency probes:
`plugins/README.md`.

---

## 15. UI surfaces (functional)

Tkinter, dark theme, multi-window. Key surfaces (rebuild functionally, not
pixel-exact):

- **`App`** — root window; menus; opens panels; owns global config + protocol manager.
- **IO-list import** — `SheetSelectorDialog` (pick Excel sheet) → `ColumnMapperDialog`
  (map columns → point fields) → saved to `iscs_metadata.db`; `MetadataBrowserDialog`
  to browse/reuse profiles.
- **Monitor/zone capture** — `ScreenSelectorPanel` (pick display), `OverlayWindow`/
  `RegionPickerFrame`/`CoordinatePickOverlay` to draw zones and pick nav coordinates;
  `CrosshairOverlay`/`IdentifyOverlay` helpers.
- **Card config** — `SuiteCardConfigDialog`: per-card zones (per page), navigation
  coordinates (home/alarm-list/event-list/right-click), protocol, loops/infinite.
- **Flow editor** — `ProcedureFlowDialog` (the ⚡ editor): the IOGroup→steps tree, a
  "＋ Quick add" palette for simple steps, per-step parameter editors built from
  registry metadata; verifications via the "+ Add" dropdown; `AddStepDialog`.
- **Custom verify authoring** — `VerifyCustomWizard`, `BindingEditorDialog`,
  `AssetManagerDialog`, `CheckGalleryDialog`, asset/template pickers.
- **Suite panel** — `SuitePanel`: the suite list, run/stop, save/load (💾/📂), and the
  **📊 report picker**.
- **OCR/diagnostics** — `OcrMonitorPanel`/`OcrOverlay` (live OCR preview),
  `HelpInspectorPanel`, `HudOverlay`/`Toast`/`Tooltip`/`ConfirmDialog` feedback.

---

## 16. Configuration keys (`config.json` / `APP_CONFIG`)

| key | default | meaning |
|---|---|---|
| `modbus_port` | 502 | Modbus TCP server port. |
| `tesseract_cmd` | `C:\Program Files\Tesseract-OCR\tesseract.exe` | Tesseract exe (or on PATH). |
| `tesseract_lang` | `eng` | OCR language. |
| `grid_spacing` | 30–40 | grid-mode point spacing (px). |
| `click_delay` | 1.5 | delay after right-click during equipment nav. |
| `mouse_drift_px` | 15 | jitter for human-like clicks. |
| `nav_wait_sec` | 1.0–2.0 | wait after a navigation click. |
| `detection_duration_sec` | 6.0–8.0 | max OCR poll window for a state change. |
| `sampler_interval_ms` | 100 | frame-sampler interval. |
| `sampler_duration_sec` | 10.0 | frame-sampler total window. |
| `datetime_sync_limit_sec` | 4.0 | max SCADA-clock vs trigger delta to PASS datetime. |
| `scada_timeout_sec` | 8.0 | general SCADA wait budget. |
| `blink_burst_frames` / `blink_burst_sec` | 8 / 1.0 | no-sampler colour burst. |
| `severity_matrix` | built-in | state→{text,color,name}; **not** persisted to JSON. |

---

## 17. Invariants & gotchas (must preserve when rebuilding)

- **Stable string keys.** `proc_type` value == registry key == saved-flow key. Public
  and embedded in persisted data — never rename.
- **Coordinates are absolute** desktop space across monitors; screen grabs use
  `all_screens=True`. Zones carry their `monitor_index`.
- **Everything degrades gracefully.** Guard every optional import; disable just the
  feature; surface it in the load manifest, not a crash.
- **`severity_matrix` uses RGB tuples** — never round-trip it through JSON (tuples
  become lists).
- **Schema versioning** on flows and the asset store: missing version = current;
  newer-than-supported = clear refusal; chained migrators upgrade in sequence.
- **Per-step isolation:** a step exception becomes `ERROR`; a failing event
  subscriber never aborts a run; a faulty plugin is skipped + reported.
- **Rerun-on-fail** preserves *every* attempt in the report (`attempts[]`); top-level
  fields reflect the latest.
- **The live run path** (`SuiteRunner.run`) needs a real screen + Modbus and can't be
  unit-tested — it's validated manually (see `LIVE_VALIDATION.md`); everything else
  has hermetic tests.
- **`baru.py` is a god-module** (UI + verifier + protocol + suite runner + metadata
  store). Decomposing it is acknowledged future work.

---

## 18. Reconstruction build order

1. **Core contracts** — `iscs_core` (registry, StepResult/StepStatus, CapabilityMeta,
   EventBus, discovery, manifest, backends, container).
2. **Domain + persistence** — Monitor/Zone/Scenario, IO-point model + SQLite store,
   `AssetManager` (+ schema versioning), config loader, severity matrix.
3. **Protocol** — `ProtocolManager` + `ModbusProtocol` (pymodbus TCP server).
4. **OCR + verification** — `iscs_OCR` pipeline, `ISCSVerifier`, text/colour helpers.
5. **Flow model + engine** — `Procedure/IOGroup/ProcedureFlow`, `ExecContext`,
   `ProcedureRunner._execute_procedure` (registry dispatch), `auto_register_procedures`.
6. **Capabilities** — the 19 step plugins under `plugins/` (actions/verifications/
   utilities), each `@register`. Bind the verifier as the backend.
7. **Suite runner + events** — `SuiteRunner`/`ISCS_Engine`, lifecycle events,
   evidence capture, rerun-on-fail.
8. **Reporting** — `normalize_results` (the contract), legacy HTML+Excel,
   `ResultView`+widgets+templates+format renderers, `suite_results.json`.
9. **UI** — Tk app, IO import, zone/coord capture, card config, flow editor, suite
   panel + report picker, OCR diagnostics.
10. **Hardening** — load manifest, dependency probes, graceful degradation, schema
    migrators, hermetic test suite.

Build 1–8 headless-first (testable without a screen); add the UI (9) and live
behaviour last.
