# CLAUDE.md — WilloWisp codebase guide

Orientation for anyone (human or agent) working in this repo. Companion docs:
[`ARCHITECTURE_DESIGN.md`](ARCHITECTURE_DESIGN.md) (north-star design),
[`ARCHITECTURE_REQUIREMENTS.md`](ARCHITECTURE_REQUIREMENTS.md) (FR/NFR),
[`MIGRATION_CHECKLIST.md`](MIGRATION_CHECKLIST.md) (status tracker),
[`LIVE_VALIDATION.md`](LIVE_VALIDATION.md) (rig-validation log),
[`plugins/README.md`](plugins/README.md) (how to extend).

---

## What this app is

**WilloWisp** (a.k.a. *ISCS AutoClick*) is a single-machine **Windows desktop
GUI tool** (Tkinter) that automates **closed-loop testing of SCADA / ISCS alarm
workflows**. For each IO point it:

1. **Triggers** an alarm via a protocol (Modbus today),
2. **Verifies** it appears on the SCADA screen (OCR text + colour/template checks
   on user-drawn zones),
3. **Resets / normalizes** the point,
4. **Verifies** it cleared,
5. captures **evidence** (screenshots, optional per-card MP4),
6. generates **consolidated reports** (HTML + Excel, plus on-demand PDF/JSON and
   audience templates).

User journey: *import IO list → pick monitor → draw zones / load template →
auto-build a flow → run a suite → review the report.*

- **Entry point:** `python baru.py` → `__main__` (baru.py:~7659) runs
  `_load_plugins()` → `_wire_subscribers()` → `App().mainloop()`.
- **Python 3.14**, Tkinter UI. Optional deps degrade gracefully (see below).

---

## Architecture in one picture

```
UI (Tkinter, baru.py)               authors flows by string key, never by class
        │
        ▼
Flow engine  ProcedureRunner._execute_procedure (iscs_workflow.py)
        │   iterates IOGroups/ordered steps; honours enabled/order/depends_on;
        │   wraps per-step exceptions → ERROR; NO per-type branching
        ▼
Capability registry (iscs_core.registry)   resolve(key) → capability.execute(ctx)
        │   19/19 step types are plugins; legacy adapters = vestigial safety net
        ▼
Shared exec context (LegacyExecContext bridge: ctx.proc/exec/runner/log/sampler_ok)
        ▼
Infra: ISCSVerifier (OCR/colour/template) · ProtocolManager/Modbus · screen
       capture · recorder · AssetManager · ReportManager · SQLite metadata
   ╎ cross-cutting: EventBus (iscs_core.events) · DI Container (iscs_core.container) ╎
```

The big idea (realized via a **Strangler-Fig** migration — now complete): every
step type is a **Capability** — `key`, `meta` (`CapabilityMeta`), and
`execute(ctx) -> StepResult` — discovered from `plugins/` at startup and resolved
by string key. **Adding a step type = drop a file in `plugins/`, no engine/enum/
UI/report edits.** See `plugins/README.md`.

---

## Module map

| File | ~LOC | Role |
|---|---|---|
| **`baru.py`** | 7.7k | The Tkinter app + most subsystems (a known god-module). Key classes: `App` (root window), `SuitePanel` (suite UI + 📊 report picker), **`SuiteRunner`** (worker thread that runs a suite — live screen + Modbus), `ISCS_Engine`/`ClickEngine` (other run modes), **`ISCSVerifier`** (OCR/colour/template verification — the `VerificationBackend`), **`ProtocolManager`** + `BaseProtocol`/`ModbusProtocol` (a working registry), `Scenario`/`Zone`/`Monitor` (domain), `FailureEvidenceCollector`, many dialogs/overlays. |
| **`iscs_workflow.py`** | 4.9k | Flow engine + data model. `ProcedureType` enum, `Procedure`/`IOGroup`/`ProcedureFlow` (composite tree), **`ProcedureRunner`** (`_execute_procedure` dispatch), `ExecContext`, `LegacyCapabilityAdapter`/`LegacyExecContext` (bridge to plugins), `auto_register_procedures` (default flow builder), flow **schema versioning**, and the flow-editor UI (`AddStepDialog`, `ProcedureFlowDialog`). |
| **`iscs_reports.py`** | 1.6k | `ReportManager`: **`normalize_results`** (the *stable result contract*), the legacy `Suite_Report.html` + Excel writers, evidence scanning, `suite_results.json` persistence, and `on_suite_completed` (EventBus subscriber). Standalone (no `iscs_core` import). |
| **`iscs_report_templates.py`** | 480 | Pluggable reporting: `ResultView` (data layer) + `ReportWidget` registry + composable `TEMPLATES` + format renderers (`render_legacy`/`render_pdf`/`render_json`). Backs the 📊 picker. |
| **`iscs_assets.py`** | 1.1k | `AssetManager` (text/image/region/template store; JSON-persisted; **schema-versioned**), `StepBinding`, `BindingExecutor` + **`BindingResolver`** registry (TEXT/IMAGE/HYBRID). Standalone (no `iscs_core` import). |
| **`iscs_OCR.py`** | 170 | Tesseract OCR wrapper (`run`, `initialize`). Optional. |
| **`iscs_recorder.py`** | 480 | Per-card screen recording (MP4) with burned-in overlay. Optional. |
| `iscs_Sampler_Anchor.py` | — | **Optional** upgrade module (`FrameSampler`, visual anchoring). Absent in this checkout; all uses are guarded. |

### `iscs_core/` — the modernization core (additive, framework-level)

| File | Provides |
|---|---|
| `registry.py` | `Capability` contract, `CapabilityRegistry`, `CapabilityMeta`, `StepResult`/`StepStatus`, `@register`, `using_registry`, global `registry`. |
| `events.py` | `EventBus` (isolated delivery) + lifecycle events (`Suite/Card/IOPoint/Step Started/Completed`, `Verification Passed/Failed`) + global `bus`. |
| `container.py` | `Container` — DI resolver with lifetimes (exists + tested; not wired into live construction — deferred, low value). |
| `discovery.py` | `discover_directory` / `discover_package` / `discover_entry_points` (plugin auto-discovery). |
| `backends.py` | `VerificationBackend` protocol (ISCSVerifier conforms structurally). |
| `manifest.py` | `LoadManifest` + dependency probes (`register_dependency`, `importable`, `evaluate_requirements`) — the startup “what loaded / unavailable / failed” diagnostic. |

### `plugins/` — drop-in capabilities (discovered at startup)

```
actions/        input.py (click/right_click/hotkey/type_text) · navigate.py ·
                protocol.py (trigger_alarm/reset_alarm) · example_action.py (reference)
utilities/      delay.py · screenshot.py
verifications/  verify_alarm_panel · verify_normalize · verify_lists
                (alarm_list+event_list) · verify_equipment_page · verify_custom
```
`baru._load_plugins()` runs `discover_directory` over `actions / verifications /
utilities` at launch; each file `@register(...)`s and supersedes its legacy
adapter by key.

---

## How a run works

1. **Author:** import IO list → pick monitor → draw zones / load a template →
   `auto_register_procedures` builds a default `ProcedureFlow` (per-IO `IOGroup`s
   of ordered `Procedure`s). Saved flows are JSON, schema-versioned.
2. **Execute:** `SuiteRunner` (thread) walks cards → loops → IO points. For each
   step, `ProcedureRunner._execute_procedure` resolves the capability by
   `proc_type.value` from the registry and calls `execute(ctx)`. It honours
   `enabled` / `order` / `depends_on` and converts any exception to `ERROR`.
3. **React:** lifecycle events are published on the `EventBus`; the report
   subsystem and recorder are **subscribers** (not called directly).
4. **Report:** on `SuiteCompleted`, `ReportManager` writes `Suite_Report.html` +
   Excel + `suite_results.json`. The 📊 picker re-renders any template
   (Legacy / Audit / Engineering / Management / PDF / JSON) offline from
   `suite_results.json` — no re-run.

---

## Dev workflow

```bash
python baru.py                 # run the app (Windows, needs a screen for a real suite)
python -m pytest -q            # 259 tests, run from the repo root
```

- **Tests** live in `tests/` (`testpaths = ["tests"]`); coverage gate
  `fail_under = 18` in `pyproject.toml`. Tests are hermetic — no live screen,
  Modbus, or Tk loop required (fakes/monkeypatch for pyautogui, handlers,
  samplers, fpdf2).
- **Add a capability:** copy a file in the right `plugins/<category>/`, set
  `key`/`meta`/`execute`, use `@register(override=True)` to supersede a built-in.
  Full extension guide (binding resolvers, report widgets/templates, dependency
  probes): [`plugins/README.md`](plugins/README.md).

---

## Conventions & gotchas

- **Stable string keys.** `ProcedureType` value == registry key == persisted flow
  `proc_type`. These are public; don't rename (breaks saved flows).
- **Optional-dependency guards everywhere** (`UPGRADES_AVAILABLE`,
  `PYAUTOGUI_AVAILABLE`, `PYMODBUS_AVAILABLE`, `RECORDER_AVAILABLE`, …). The P6.2
  **load manifest** summarizes capability availability at startup; a startup log
  also confirms *"registry covers all 19 step types (legacy fallback inactive)."*
- **Legacy `_exec_*` path is vestigial but retained** as a deliberate degradation
  safety net (used only if `iscs_core` is unavailable, or a plugin is missing —
  in which case `_execute_procedure` logs a ⚠ warning). Do **not** delete the
  enum/fallback: the enum still backs `auto_register`, the UI catalogue, and many
  `== ProcedureType.X` checks.
- **`iscs_assets.py` and `iscs_reports.py` stay standalone** (no `iscs_core`
  import) by design; `iscs_report_templates.py` imports `ReportManager` lazily.
- **`baru.py` is a god-module** (UI + verifier + protocols + suite runner). Its
  decomposition (NFR-3) is acknowledged future work, not yet done.
- **Persistence:** `iscs_assets.json`, `iscs_template.json` (schema-versioned with
  chained migrators), `iscs_metadata.db` (SQLite), evidence under
  `test_logs/<suite>/…`.

---

## Status (2026-06-25)

Plugin/registry modernization **complete and live-validated** on the SCADA rig:
**19/19 step types run from plugins**, event-driven reporting/recording, schema
versioning, pluggable report templates+widgets, optional-dependency manifest, and
the legacy dispatch path proven vestigial + instrumented. **259 tests pass.**
Remaining items are deferred by design (delete enum/fallback, DI live-wiring,
`is_applicable`) — see the DEFERRED table in `MIGRATION_CHECKLIST.md`.
