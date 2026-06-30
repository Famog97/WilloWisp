# WilloWisp — ISCS AutoClick Test Automation Framework

> Closed-loop, evidence-generating UI test automation for SCADA / HMI systems
> (Integrated Supervisory Control System — alarm panels, alarm/event lists, equipment pages).

A single Windows desktop application (`baru.py`) that triggers alarm points over an industrial
protocol (Modbus / SNMP), verifies what appears on the SCADA screen (OCR + colour + timestamp +
template matching), and produces screenshots, screen recordings, and consolidated HTML/Excel reports.

It replaces manual, alarm-by-alarm acceptance testing of hundreds-to-thousands of points with a
repeatable suite that leaves a full audit trail.

---

## Running the app

```bash
python baru.py
```

**Requirements** (all optional — features degrade gracefully if a dependency is missing):

| Dependency | Enables |
|---|---|
| `pyautogui`, `keyboard` | click / type / hotkey automation |
| `Pillow (PIL)` | screen capture, zone drawing |
| `screeninfo` | multi-monitor detection |
| `pandas`, `openpyxl` | Excel IO-list import + report export |
| Tesseract-OCR (path in `config.json`) | text verification |
| `opencv-python` | image / template matching, recording frames |
| `imageio` + `imageio-ffmpeg` | MP4 screen recording |
| `pymodbus`, `pysnmp` | protocol triggers |

Settings such as the Tesseract path and timing tolerances live in **`config.json`** (see bottom).

---

## Three operating modes

The app header (`baru.py`) describes itself as a *UI Testing, Closed-Loop Test Automation Framework*
with three modes:

1. **Targeted Sequence (RPA)** — record/replay a fixed click+type sequence.
2. **Grid Scan (Fuzzer)** — sweep a grid of click points across a region.
3. **Suite Runner (Modbus + OCR Closed-Loop)** — the main mode: trigger → verify → reset across an
   imported IO list, looping and reporting. **This is what the rest of this document covers.**

---

## Module map

| File | Lines | Responsibility |
|---|---:|---|
| `baru.py` | ~7400 | Main Tkinter app — UI, scenario cards, suite runner, monitor/zone management, Modbus/SNMP handlers, **IO-profile metadata store** |
| `iscs_workflow.py` | ~4350 | Procedure Flow engine — step types, per-IO flow tree, `ProcedureRunner`, flow-editor dialogs |
| `iscs_reports.py` | ~1590 | Result normalization, HTML dashboard, Excel export, evidence file tree |
| `iscs_assets.py` | ~1010 | Reusable text/image/region/template asset repository (`iscs_assets.json`) |
| `iscs_recorder.py` | ~480 | Background per-card MP4 screen recorder with overlays + hourly auto-split |
| `iscs_OCR.py` | ~170 | Tesseract wrapper with adaptive image preprocessing |
| `iscs_Sampler_Anchor.py` | — | *(optional)* Visual anchoring + frame sampling for shifting SCADA layouts. Loaded if present; the app sets `UPGRADES_AVAILABLE=False` and runs without it otherwise. |

Each module has one clear responsibility and communicates through plain dataclasses / JSON, which is
why subsystems (asset binding, metadata store) were added without rewriting the core.

---

## Core concepts

### 1. Monitors & Zones
The app detects connected monitors; on a chosen monitor the user draws rectangular **zones** that map
to screen areas. Zones are stored as pixel coordinates relative to the monitor and persist with the card:

- `alarm_panel` — the main alarm banner/strip
- `alarm_list` — the scrolling alarm list table
- `event_list` — the historical event log
- `equipment_page` — the equipment detail view
- `anchor` — a stable landmark used to re-resolve the other zones at runtime if the layout shifts

A drawn set of zones + navigation click points can be saved/loaded as a reusable **template**
(`iscs_template.json`).

### 2. IO List (Excel import) + Metadata Store
An Excel sheet defines the test data — one row per alarm point: `point_id`,
`equipment_description`, `attribute_description`, station/location, Modbus/SNMP address, and a
**states** table (`v0` = normal/reset, `v1` = alarm/trigger; trigger vs reset index is derived from
the states, never hardcoded).

Imported IO lists are cached in a local SQLite database **`iscs_metadata.db`** as named **profiles**
(tables `profiles` + `io_points`, keyed by file hash + sheet). The `MetadataBrowserDialog` lets the
user re-load a previously imported list without re-parsing the spreadsheet — import once, reuse across
runs and cards.

### 3. Scenario Cards & Suites
A **scenario card** bundles a monitor, a zone set, an IO list (or subset), a loop count, and an
execution flow. Multiple cards form a **Suite** that runs sequentially, with results aggregated into
one report.

### 4. Procedure Flow (the "how")
Rather than hardcoding the sequence, the system builds an ordered, editable **flow** of steps and
executes it generically (`auto_register_procedures()` inspects zones + IO list to build a sensible
default).

**Per-IO folders:** every IO point gets its own `IOGroup` folder holding a full copy of the step
sequence — so one point can be customized without affecting the other 1,999.

- **Action steps:** `TRIGGER_ALARM`, `RESET_ALARM`, `NAVIGATE_HOME`, `NAVIGATE_ALARM_LIST`,
  `NAVIGATE_EVENT_LIST`, `NAVIGATE_EQUIP_PAGE`, `CLICK`, `RIGHT_CLICK`, `HOTKEY`, `TYPE_TEXT`
- **Verify steps:** `VERIFY_ALARM_PANEL`, `VERIFY_NORMALIZE`, `VERIFY_ALARM_LIST`,
  `VERIFY_EVENT_LIST`, `VERIFY_EQUIP_PAGE`, `VERIFY_ALARM_PANEL_CUSTOM`, `VERIFY_CUSTOM`
- **Utility steps:** `DELAY`, `SCREENSHOT`

The Flow Editor (`ProcedureFlowDialog`) shows the IO-grouped tree with a context-sensitive toolbar
(add / edit / duplicate / delete / reorder / enable-disable), multi-select, right-click actions
including **Apply to All IOs**, and a live search filter.

---

## Verification engine

For each point, the alarm-panel check (`verify_alarm_panel`) runs a poll loop for up to
`detection_duration_sec`, grabbing the zone and evaluating:

- **OCR text** (`iscs_OCR.run` / `run_digits`) — identifier, description, value, with fuzzy matching.
  Adaptive preprocessing decides inversion/brightness/sharpen/binarize for SCADA fonts; PSM is chosen
  per layout mode (`tabular`, `block`, `single_line`, `sparse`).
- **Severity** — word-boundary match with a digit-cell fallback for an isolated `0`/`1`.
- **Colour + blink** — sampler frames checked against the expected RGB (red alarm / green normal).
- **Datetime** — SCADA on-screen clock vs trigger time, within `datetime_sync_limit_sec`.

Then **reset** the alarm and verify it normalizes; repeat for alarm/event/equipment zones if present.

### Asset binding (verify anything, no IO row needed)
`iscs_assets.py` provides a persistent repository (`iscs_assets.json`) of **Text** (`TXT_*`),
**Image** (`IMG_*`, crops in `assets/images/`), **Region** (`RGN_*`), and **Flow Template** (`TPL_*`)
assets. A `VERIFY_CUSTOM` step carries a `binding` (`TEXT` / `IMAGE` / `HYBRID`) that resolves a
region, grabs it, and checks an OCR substring and/or `cv2.matchTemplate` score against a threshold.
This lets a flow verify status icons, mode indicators, or button labels with **zero IO list and zero
drawn zones** — and reuse one asset across hundreds of steps.

---

## Recording (`iscs_recorder.py`)
Per-card MP4 capture: configurable FPS (1/5/10/15/24/30/60, default 5), wall-clock + point-identifier
overlay burned into frames, hourly auto-split, multi-monitor aware, written via `imageio-ffmpeg`
(H.264 `ultrafast`). A pre-flight check estimates file size and warns on low disk.

---

## Rerun system
Failed points can be retried `N` times or **until pass**, at the suite level. **Every attempt is
preserved** in the report (Attempt 0 FAIL → Attempt 1 PASS …) so an engineer can see exactly what
changed.

---

## Reporting (`iscs_reports.py`)
At the end, `ReportManager.generate_reports()` calls `normalize_results()` to consolidate every loop,
card, and rerun attempt, then writes a single **`Suite_Report.html`** (overall pass rate, loop→card
tree auto-expanding failures, per-point step trace, execution history, collapsible evidence file tree
with FAIL auto-expanded) plus a multi-sheet **Excel** workbook.

### Output layout
```
test_logs/
└── <title>_suite_<timestamp>/
    ├── Suite_Report.html
    ├── <suite>.xlsx
    ├── test_run.log
    └── loop_0001/
        └── 1_<CardName>/
            ├── 0000_<point>_alarm_panel_trigger_PASS.png
            ├── 0000_<point>_alarm_panel_normalize_FAIL.png
            ├── <CardName>_<ts>.mp4
            └── failures/
                └── 0000_<point>_<ts>/
                    ├── crop_zone_*.png
                    ├── expected_vs_actual_comparison.json
                    ├── alarm_metadata.json
                    └── timestamp_delta.json
```

---

## End-to-end flow (TL;DR)
> **Import IO list (cached as a profile) → pick monitor → draw zones (or load template) →
> auto-build a per-point Procedure Flow → SuiteRunner loops every point
> (trigger ▶ OCR/colour/time verify ▶ reset ▶ verify) capturing screenshots/video →
> reruns failures → emits one consolidated `Suite_Report.html` + Excel.**

```
Import IO List ─► Pick Monitor ─► Draw Zones / Load Template ─► Auto-gen Procedure Flow
      │                                                                    │
      └──────────────────────────────► RUN (SuiteRunner thread) ◄─────────┘
                                              │
                  loop cards × loop count ────┤
                                              ▼
                 per IO point: TRIGGER → verify(OCR+colour+time) → RESET → verify
                                              │
                       save screenshots / recording / diagnostics
                                              │
                     reruns for failed points → normalize → Report (HTML + Excel)
```

---

## Key configuration (`config.json`)

| Setting | Effect |
|---|---|
| `tesseract_cmd` / `tesseract_lang` | Path to `tesseract.exe` and OCR language |
| `modbus_port` | Modbus TCP port (default 502) |
| `detection_duration_sec` | How long to poll for the alarm to appear + observe colour/blink |
| `datetime_sync_limit_sec` | Max allowed SCADA-clock vs trigger-time gap before datetime FAILs |
| `nav_wait_sec` | Pause between navigation clicks |
| `sampler_interval_ms` / `sampler_duration_sec` | Colour/blink frame-grab rate and window |
| `scada_timeout_sec` | SCADA response timeout |
| `click_delay`, `mouse_drift_px`, `grid_spacing` | RPA / grid-scan timing & spacing |

---

## Related docs
- [`ISCS_AutoClick_Overview.md`](ISCS_AutoClick_Overview.md) — design rationale, comparison to
  commercial tools (Eggplant/TestComplete), limitations, and future vision.
- [`SUITE_RUNNER_FLOW.md`](SUITE_RUNNER_FLOW.md) — stage-by-stage suite-run flow with Mermaid
  diagrams and `file:line` references into the code.
- [`ARCHITECTURE_REQUIREMENTS.md`](ARCHITECTURE_REQUIREMENTS.md) — proposed plugin/registry
  modernization spec: functional & non-functional requirements (FR-1…30, NFR-1…13) and target
  architecture diagram.
- [`ARCHITECTURE_DESIGN.md`](ARCHITECTURE_DESIGN.md) — assessment, risks, abstraction layers &
  interfaces, design patterns, and the Strangler-Fig migration strategy for the modernization.

## Current limitations
Single-machine (captures the local display), desktop GUI required (no headless/CI), single-user. The
optional `iscs_Sampler_Anchor.py` upgrade module may be absent, in which case visual anchoring/frame
sampling is disabled.
