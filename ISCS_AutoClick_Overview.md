# ISCS AutoClick — Test Automation Framework

## Overview

ISCS AutoClick is a Windows desktop application for automating functional testing of SCADA/HMI systems — specifically Integrated Supervisory Control System (ISCS) alarm panels, alarm lists, event lists, and equipment detail screens. It was built to replace manual alarm-by-alarm verification (an engineer triggering thousands of points one at a time and eyeballing the screen) with a repeatable, evidence-generating automated suite.

The tool sits at the intersection of three things that don't usually meet in one package: industrial protocol automation (Modbus/SNMP), desktop UI automation (screen capture, OCR, click simulation), and test reporting (HTML dashboards, Excel exports, video evidence). Commercial equivalents — Eggplant Functional, TestComplete, Ranorex — solve pieces of this, but none are purpose-built for SCADA alarm verification workflows, and all carry licensing costs that don't fit every project budget.

---

## What Problem It Solves

A typical ISCS commissioning or factory acceptance test requires verifying hundreds to thousands of alarm points: trigger the alarm via the PLC, confirm it appears correctly on the alarm panel (correct identifier, description, severity colour, timestamp), confirm it propagates to the alarm list and event list, confirm the equipment detail page shows the right information, then trigger the reset and confirm everything clears. Doing this manually for 2,000 points is days of repetitive, error-prone work with no audit trail beyond a spreadsheet someone fills in by hand.

ISCS AutoClick automates the entire cycle per point and produces:
- A pass/fail result per point, per check (panel, list, event, equipment)
- Screenshots of every check, organized and linked
- Screen recordings of the whole test run, segmented by hour
- A single consolidated HTML report covering an entire suite (multiple loops, multiple scenario cards)
- An Excel workbook for stakeholders who want raw data

---

## System Architecture

The application is a single Tkinter desktop app (`baru.py`, ~7000 lines) supported by several focused modules. Each module has one clear responsibility, which keeps the system maintainable despite its size.

| Module | Responsibility |
|---|---|
| `baru.py` | Main application — UI, scenario cards, suite runner, monitor/zone management, Modbus/SNMP protocol handlers |
| `iscs_workflow.py` | Procedure Flow engine — defines step types, the IO-group flow tree, `ProcedureRunner` execution, and all flow-editor UI dialogs |
| `iscs_reports.py` | Result normalization, HTML dashboard generation, Excel export, evidence file tree |
| `iscs_recorder.py` | Background screen recorder — per-card MP4 capture with overlays, hourly auto-split |
| `iscs_OCR.py` | Tesseract wrapper with adaptive image preprocessing (contrast, inversion, brightness correction) |
| `iscs_Sampler_Anchor.py` | Anchor-based frame sampling for dynamic SCADA layouts (handles screens that shift/scroll) |
| `iscs_assets.py` | Global, persistent repository of reusable text/image assets, named regions, and flow templates |

### Why this structure works

Each module can be tested and reasoned about independently. `iscs_OCR.py` doesn't know anything about Modbus. `iscs_recorder.py` doesn't know what an "alarm" is — it just records screens with overlays. `iscs_assets.py` has zero dependency on Tkinter for its data layer, only the UI dialogs import `tkinter`. This separation is what allowed the asset-binding system to be added later without touching a single line of the core OCR/Modbus/reporting logic.

---

## Core Concepts

### 1. Monitors & Zones

The app detects all connected monitors and lets the user pick which one a scenario card targets. On that monitor, the user draws rectangular **zones** — pixel regions that map to meaningful areas of the SCADA display:

- `alarm_panel` — the main alarm banner/strip
- `alarm_list` — the scrolling alarm list table
- `event_list` — the historical event log
- `equipment_page` — the equipment detail view (opened via right-click)

Zones are stored as pixel coordinates relative to the selected monitor and persist with the scenario card.

### 2. IO List (Excel Import)

An Excel spreadsheet defines the test data — one row per alarm point:

- `point_id` — e.g. `BUCS-AMS-ACU-OCC-0008`
- `equipment_description` — e.g. `Medium Level Security Door`
- `attribute_description` — e.g. `Intrusion Alarm`
- Modbus/SNMP address for trigger and reset
- Expected severity, colour, identifier text

This is the "what to test" data — imported once, reused across every run.

### 3. Scenario Cards & Suites

A **scenario card** bundles: a monitor selection, a set of drawn zones, an imported IO list (or a subset of it), a loop count, and an execution flow. Multiple cards form a **Suite** — they run sequentially, optionally looping, with results aggregated into one report.

### 4. The Execution Flow (Procedure Flow System)

This is the heart of the automation. Rather than hardcoding "trigger → wait → screenshot → OCR → reset", the system generates a **flow** — an ordered, editable list of steps — and executes it generically.

#### Auto-generation

When zones and an IO list are present, `auto_register_procedures()` inspects what's configured and builds a sensible default flow automatically:

- IO list present → `Trigger Alarm` + `Reset Alarm` steps
- `alarm_panel` zone drawn → `Verify Alarm Panel` + `Verify Normalize` steps
- `alarm_list` zone + nav coordinates → `Navigate to Alarm List` + `Verify Alarm List`
- `event_list` zone + nav coordinates → `Navigate to Event List` + `Verify Event List`
- `equipment_page` zone + right-click coordinates → `Navigate to Equipment Page` + `Verify Equipment Page`

Steps missing required navigation coordinates are added but disabled, so the user sees what *could* run and can wire it up later.

#### IO Groups — per-point flow folders

As of the latest redesign, the flow is not a single flat list shared across all points. Instead, **every IO point gets its own folder (`IOGroup`)** containing a full copy of the step sequence:

```
▼ IO: BUCS-AMS-ACU-OCC-0008 — Medium Level Security Door: Intrusion Alarm
    ● Trigger Alarm
    ● Verify Alarm Panel
    ● Navigate to Alarm List
    ● Verify Alarm List

▼ IO: BUCS-AMS-ACU-OCC-0007 — Fire Door: Intrusion Alarm
    ● Trigger Alarm
    ● Verify Alarm Panel
    ...
```

This means a custom step can be inserted into *one specific point's* flow without affecting any other point — useful when one alarm has a quirky behaviour (extra navigation step, different verification) that the other 1,999 don't.

#### Step types

**Action steps**: `TRIGGER_ALARM`, `RESET_ALARM`, `NAVIGATE_HOME`, `NAVIGATE_ALARM_LIST`, `NAVIGATE_EVENT_LIST`, `NAVIGATE_EQUIP_PAGE`, `CLICK`, `RIGHT_CLICK`, `HOTKEY`, `TYPE_TEXT`

**Verification steps**: `VERIFY_ALARM_PANEL`, `VERIFY_NORMALIZE`, `VERIFY_ALARM_LIST`, `VERIFY_EVENT_LIST`, `VERIFY_EQUIP_PAGE`, `VERIFY_ALARM_PANEL_CUSTOM`, `VERIFY_CUSTOM`

**Utility steps**: `DELAY`, `SCREENSHOT`

Each step has `enabled`/`disabled`, an `order` (increments of 10, so steps can be inserted between existing ones), `depends_on` (skip if a prerequisite failed), and — new — `step_id` and an optional `binding`.

#### The Flow Editor UI

`ProcedureFlowDialog` presents the IO-grouped tree with a single context-sensitive toolbar: select an IO folder or a step, and the toolbar (`+ Add`, `✏ Edit`, `⧉ Duplicate`, `🗑 Delete`, `▲/▼ reorder`, `✓/✗ enable/disable`) acts on whatever is selected. Multi-select with Ctrl/Shift enables bulk operations. Right-click gives the same actions contextually, plus **Apply to All IOs** — clone a step into every IO folder at once. A search bar filters the tree live by step name, point ID, or label.

---

## Verification Engine

### OCR (`iscs_OCR.py`)

Wraps Tesseract with adaptive preprocessing:
- Samples pixel brightness/contrast to decide whether to invert colours (dark theme SCADA screens), adjust brightness, sharpen, or binarize
- Supports four layout modes (`tabular`, `block`, `single_line`, `sparse`) mapped to Tesseract PSM values
- Designed specifically for the inconsistent rendering of SCADA HMI fonts and colour schemes

### Colour Detection

Checks whether an expected severity colour (e.g. red for critical, amber for warning) is present within tolerance in a zone — used alongside OCR to confirm both the *text* and the *visual indicator* are correct.

### Datetime Verification

Compares the timestamp shown on the alarm panel against the system clock, with a configurable sync tolerance, to catch clock-drift or stale-data issues.

---

## Asset Binding System — Extending Beyond IO/Zones

This is the newest major subsystem, designed to let verification work **independently of the IO list and zone system** — opening the tool to any SCADA screen element, not just alarm points.

### The problem it solves

The legacy verification steps (`VERIFY_ALARM_PANEL` etc.) only work because they pull "what to expect" from the IO list row and "where to look" from a drawn zone. If you want to verify something that *isn't* an alarm point — a status icon, a mode indicator, a button label — there's no IO row to pull expected values from.

### The solution: Assets + Regions + Bindings

`iscs_assets.py` introduces a global, persistent repository (`iscs_assets.json`, stored beside the app) of three reusable entity types:

- **Text Assets** (`TXT_0001`, ...) — a named expected string, e.g. `"HIGH ALARM"`. Compared via OCR.
- **Image Assets** (`IMG_0001`, ...) — a named reference image crop, stored in `assets/images/`. Compared via OpenCV `matchTemplate`.
- **Regions** (`RGN_0001`, ...) — a named screen rectangle with coordinates and monitor index. Reusable across any step.
- **Flow Templates** (`TPL_0001`, ...) — a saved, reusable sequence of steps that can be merged into any card's flow.

A new step type, `VERIFY_CUSTOM`, carries an optional `binding`:

```json
{
  "type": "TEXT" | "IMAGE" | "HYBRID",
  "asset_id": "TXT_0001",
  "image_asset_id": "IMG_0001",   // HYBRID only
  "region_id": "RGN_0001",
  "threshold": 0.85,               // image match similarity
  "on_fail": "fail" | "skip" | "warn"
}
```

At execution time, `BindingExecutor`:
1. Resolves the region's coordinates and grabs that screen area
2. **TEXT** binding → runs `iscs_OCR.run()`, checks if the text asset's value appears in the result
3. **IMAGE** binding → runs `cv2.matchTemplate()` against the image asset, checks the similarity score against the threshold
4. **HYBRID** → both checks must pass

The result — status, expected value, actual value, match score, asset name — flows through `ExecutionTrace.flat_records()` as `custom_checks`, gets picked up by `normalize_results()`, and renders in the HTML report as a distinct "★ Custom Asset Verifications" card showing Expected vs Actual side-by-side.

### Why this matters

- A test flow can now be built **from scratch with zero IO list and zero zones** — pure click/type/verify-custom steps
- The same text/image asset can be reused across hundreds of steps across every scenario card — define `IMG_RED_BELL` once, bind it anywhere
- It bridges the gap toward the kind of "verify this icon/this label" testing that general-purpose tools like Eggplant do, but using infrastructure already proven in this codebase (OCR pipeline, OpenCV availability via the recorder's dependencies)

---

## Recording Subsystem (`iscs_recorder.py`)

Each scenario card can independently enable screen recording for its run:

- **FPS**: configurable (1, 5, 10, 15, 24, 30, 60), default 5 — chosen because SCADA screens change state slowly; 5fps is enough to capture alarm transitions without bloating file size
- **Overlay**: burns wall-clock timestamp and/or the current point's identifier + equipment/attribute description directly into the video frame — so scrubbing the recording tells you exactly which alarm was being tested at any moment
- **Auto-split**: recordings cut at the 1-hour mark and continue in a new file (`CardName_Part2_...mp4`) — keeps individual files manageable for long suite runs
- **Capture target**: defaults to the scenario card's assigned monitor (multi-monitor aware via `SM_XVIRTUALSCREEN` offset calculation), with an override dropdown for display + resolution
- **Storage**: `imageio` + `imageio-ffmpeg` (pure pip install, no manual ffmpeg binary needed) writing H.264 MP4 with `ultrafast` preset to minimize CPU overhead during the test
- **Pre-flight check**: estimates file size based on FPS/resolution/duration and warns if projected size exceeds available disk space

---

## Reporting System (`iscs_reports.py`)

### Suite-level consolidation

A single `Suite_Report.html` is generated at the suite root covering **every loop and every scenario card** in that run — not one report per card. The report shows:

- Overall pass rate, total/passed/failed counts
- A Loop → Card tree, auto-expanding any card with failures
- Per-point rows expandable to a full step-by-step trace, including rerun history (all attempts preserved, not just the final one)

### Evidence Files tree

Rather than a flat grid of screenshot thumbnails (which becomes unusable at hundreds of files), evidence is a collapsible tree:

```
Evidence Files (240)
▶ Loop 1
    ▶ TitleCard 1
        ▶ Screenshots (180)
            ▼ FAIL (4)     ← auto-expanded
            ▶ PASS (176)
        ▶ Recording (2)
        ▶ Data Files (3)
```

- FAIL screenshots auto-expand; PASS stays collapsed — failure investigation first
- Every file is a clickable link (opens in new tab) plus a "Copy path" button (browsers can't open Explorer directly, so the path is copied for manual navigation)
- Category-level "Copy Folder Path" for bulk navigation

### Excel export

A multi-sheet workbook for stakeholders who want raw tabular data — point ID, status, failure category, root cause message — suitable for pivot tables or import into other QA systems.

---

## Rerun System

Failed points can be automatically retried — either a fixed number of times or "until pass" — at the suite level (separate from per-card loop counts). The HUD shows `↺ RERUN #N` during reruns. Critically, **all attempts are preserved** in the report (a recent fix corrected a bug where reruns silently overwrote earlier failure data) — so a point that failed on attempt 1 with a specific OCR mismatch and passed on attempt 2 shows both records, letting an engineer see exactly what changed.

---

## How This Compares to Commercial Tools

| Capability | ISCS AutoClick | Eggplant Functional |
|---|---|---|
| OCR text verification | ✅ Tesseract + adaptive preprocessing | ✅ |
| Colour/severity detection | ✅ | ✅ (via image search) |
| Template/icon matching | ✅ (via asset binding) | ✅ |
| Confidence scores | ⚠️ Partial (image match score only) | ✅ Full |
| Visual flow editor | ✅ IO-grouped tree | ✅ SenseTalk-based |
| Reusable asset library | ✅ (new) | ✅ |
| Screen recording w/ overlay | ✅ | ⚠️ Limited |
| Remote SUT (VNC) | ❌ | ✅ |
| Headless/CI execution | ❌ | ✅ |
| Natural-language element finding | ❌ | ✅ (26.2+, vision LLM) |
| Cost | Free / internal | Commercial licence |

The gaps that remain — remote execution, headless/CI, natural-language targeting — are exactly the items in the future vision below.

---

## Current Limitations

- **Single-machine only**: `pyautogui`/`PIL.ImageGrab` capture the local display; the tool must run on the same Windows machine as the SCADA workstation
- **Desktop GUI required**: no headless mode — can't be triggered from a CI pipeline without a visible desktop session
- **Single-user**: no concept of shared test runs, user accounts, or remote dashboards
- **Image match confidence**: works but isn't surfaced with the same polish as OCR confidence (Tesseract `image_to_data()` per-word confidence isn't yet exposed)

---

## Future Vision

### 1. Studio / Agent Architecture

The long-discussed architectural goal: split the application into two roles communicating over WebSocket (LAN, VPN, or fully offline networks):

- **Studio** — runs on the engineer's machine. Configuration, flow editing, asset management, report viewing.
- **Agent** — runs on (or connects to) the SCADA/HMI workstation. Executes the flow, captures screens, returns results.

This immediately solves the single-machine constraint and opens the door to testing multiple SCADA workstations from one Studio instance.

### 2. Remote SUT via VNC

Rather than requiring an Agent install on every SCADA machine, a VNC-based capture backend (`vncdotool` or similar) would let Studio connect to any workstation's framebuffer directly — matching how Eggplant operates, with zero footprint on the System Under Test.

### 3. Headless / CI Execution

Extract the suite runner logic from the Tkinter `App` class into a standalone `run_suite(config, points)` callable from a script. Combined with the Agent architecture, this enables triggering ISCS regression suites from Jenkins/GitHub Actions on a schedule, with `Suite_Report.html` published as a build artifact.

### 4. Web Dashboard

A lightweight web server (FastAPI/Flask) serving the existing HTML reports plus a live view of in-progress suite runs — multiple engineers could watch a long-running overnight suite from their own machines without remote-desktopping into the test rig.

### 5. Natural-Language / Vision-LLM Element Finding

The asset-binding system's `IMAGE` and `TEXT` bindings are a stepping stone toward: describe what you want in plain English ("the high-priority alarm in the top-left panel"), send a screenshot to a vision-capable LLM, get back coordinates — no manual region drawing required. This is the single highest-impact addition for reducing setup time on new SCADA layouts.

### 6. Model-Based Test Generation & Coverage Analysis

With results already stored per point per run, a future module could: auto-generate suite ordering by severity tier, flag points never executed, suggest retest order based on historical failure rates, and produce coverage graphs — moving from "run everything every time" to risk-based testing.

### 7. Visual Regression / Screenshot Diffing

OpenCV `absdiff` between a "golden" reference screenshot and the current capture as a new step type — "assert this screen still looks like reference X" — catching unintended UI changes that no OCR or colour check would flag.

### 8. Multi-User / Shared Asset Library

Since `iscs_assets.json` is already a clean, JSON-based, file-based store, it's a short step to a shared network location (or small backend service) so multiple engineers across a project share the same text/image/region/template library — define `IMG_RED_BELL` once for the whole project, not once per laptop.

---

## Summary

ISCS AutoClick started as a focused Modbus-trigger + OCR-verify loop for ISCS alarm testing and has grown into a modular framework with its own flow-definition language (Procedure Flow + IO Groups), a reusable verification-asset system, integrated screen recording with audit-grade overlays, and consolidated suite-level reporting with full evidence traceability. The architecture — small, single-responsibility modules communicating through plain dataclasses and JSON — is what makes the ambitious items in the future vision (Studio/Agent split, remote execution, vision-LLM targeting) realistic extensions rather than rewrites.
