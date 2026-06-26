# WilloWisp — Decomposition Design (ownership all the way down)

**Role:** Principal Software Architect · **Phase:** 2 of 3 — **Design (v3, Hexagonal / Ports & Adapters)**
**Builds on:** [`RESTRUCTURE_PLANNING.md`](RESTRUCTURE_PLANNING.md) ·
**Audited by:** [`RESTRUCTURE_MIGRATION_READINESS.md`](RESTRUCTURE_MIGRATION_READINESS.md)
**Date:** 2026-06-25 · **Status:** Draft for re-audit

> v2 closed the audit blockers **B1–B8** (every method owned, god methods decomposed,
> lifecycle/thread/state ownership, guardrails). **v3 imposes a strict Hexagonal
> (Ports & Adapters) boundary** so the UI is **100% swappable**: the Tkinter GUI can be
> replaced by a Web UI (FastAPI + React), PyQt, or a pure CLI **without changing any core
> business logic, perception, Modbus, or reporting code**. Names are **logical ownership
> units**, not a folder layout; packaging and move order remain the **Migration** phase.

### Hexagonal architecture rules (binding)
- **R-HEX-1 — One inbound gate.** The UI interacts with the core **only** through a single
  UI-agnostic facade, **`WilloWispCoreAPI`**. No UI component constructs engines, coordinates
  runs, or touches repositories directly.
- **R-HEX-2 — Abstract event marshalling.** The core emits events through an abstract
  **`EventDispatcher`** port. Each UI injects its own dispatcher (Tk `.after`, Qt signals,
  WebSocket/async, CLI sync). The core never imports a UI toolkit.
- **R-HEX-3 — Pure coordinate models.** The core understands only normalized,
  framework-agnostic geometry (absolute-desktop coordinates, zones, bboxes). All canvas
  drawing, coordinate-picking overlays, and drag physics live **only** in the UI adapter.
- **R-HEX-4 — Strict boundary reclassification.** Framework-agnostic logic (scheduling,
  verification, boundary checks, data/repos, reporting) is a **Core Service** inside the
  hexagon. Anything touching a window, widget, canvas, dialog, or OS input hook is a
  **UI Adapter** outside it. "Controllers" from v2 are reclassified accordingly (§1.0).

### Feature-isolation rules — zero blast-radius extensibility (binding)
Adding a feature must require **only new files or highly localized edits**, with zero spillover
into existing code. Four registries are the **only** extension points (all already live from
the plugin migration — see [`MIGRATION_CHECKLIST.md`](MIGRATION_CHECKLIST.md)); the design
formalizes them and adds schema-driven UI generation:
- **R-EXT-1 — Pluggable step types.** A new step type is **one file** in `plugins/` that
  `@register`s a capability. The Flow editor and its parameter forms are **generated from the
  capability's `params_schema`** (§1.7) — **zero edits to any GUI file**, for any UI.
- **R-EXT-2 — Pluggable protocols.** A new industrial protocol is a `BaseProtocol`
  implementation registered with `ProtocolManager`. The engine depends only on the interface,
  resolved by key from the injected `ProtocolPort` — **zero edits to `SuiteScheduler`,
  `PointRunCoordinator`, or any run unit**.
- **R-EXT-3 — Pluggable report widgets.** A new report section is one self-contained
  `ReportWidget` subclass + a `register_widget` call; templates are ordered widget lists —
  **zero edits to the page shell or other widgets**.
- **R-EXT-4 — Pluggable verification resolvers.** A new custom-verification method (e.g. an
  OCR alternative, a vision-LLM) is one `BindingResolver` + a `register_binding_resolver` call
  — **zero edits to the `verify_custom` capability or `BindingExecutor`**.

## Design rule

```
Subsystem  owns  Modules
Module     owns  Components
Component  owns  Classes
Class      owns  Responsibilities
Method     owns  one action
```
**Continue decomposition until every unit has exactly one reason to change.** A class (or
method) that names ≥2 concerns in its "owns" line is not done.

### What v2 adds over v1 (audit-driven)
- **B1/B6** — method-level submethod trees for all god methods, incl. `_write_html_report`.
- **B3** — owners for every prior orphan (`_settings_dialog`, `_clear_workspace`,
  `_sync_open_card_config`, `ISCSVerifier.verify`, `_make_skip_result`, capture/save splits,
  the flow-editor↔asset seam). New concerns: **Settings**, **Workspace session**, **Card
  config**, **Check authoring**.
- **B4** — shared-service injection + `ExecContext` state ownership (§1.2).
- **B5** — lifecycle/thread-affinity per unit + startup ordering (§1.1, §1.3).
- **B8** — explicit "must-not-own" guardrails on every Coordinator/Controller/Service/facade.
- **B2/B7** — recorded as **design preconditions** (§1.6): one canonical run path proven
  equivalent; characterization tests pin god methods *before* they move.

---

## 1. Cross-cutting design (applies to all units)

### 1.0 Hexagonal boundary (the one rule everything else serves)

```
        DRIVING (primary) ADAPTERS — interchangeable, never imported by the core
   ┌───────────────┬───────────────┬───────────────┬───────────────────────────┐
   │  Tkinter GUI  │   PyQt GUI    │  Web (FastAPI │   CLI (headless)          │
   │  adapter      │   adapter     │   + React)    │   adapter                 │
   └──────┬────────┴──────┬────────┴──────┬────────┴───────────┬───────────────┘
          │   calls       │  calls        │  calls             │ calls
          ▼               ▼               ▼                    ▼
   ╔══════════════════════════════ INBOUND PORT ══════════════════════════════╗
   ║                       WilloWispCoreAPI  (the only gate)                    ║
   ╠═══════════════════════════════════════════════════════════════════════════╣
   ║                       CORE (hexagon interior — UI-agnostic)                ║
   ║   Application services: ImportService · DefaultFlowBuilder · FlowAuthoring ║
   ║     SuiteScheduler · PointRunCoordinator · RerunController · engine        ║
   ║     VerificationCoordinator + policies · ReportService · WorkspaceSession  ║
   ║   Domain: Scenario · Zone(geometry) · Monitor · Procedure/IOGroup/Flow ·   ║
   ║     IOPoint · ResultView                                                   ║
   ║   Cross-cutting: ConfigProvider · SeverityColorClassifier · LoadManifest · ║
   ║     capability registry · EventBus                                         ║
   ╠═══════════════════════════════ OUTBOUND PORTS ════════════════════════════╣
   ║  EventDispatcher │ ScreenCapturePort │ InputControlPort │ ProtocolPort │   ║
   ║  OcrPort │ FileSystemPort │ ClockPort                                      ║
   ╚════════┬─────────────────┬─────────────────┬─────────────────┬────────────╝
            ▼                 ▼                 ▼                 ▼
   DRIVEN (secondary) ADAPTERS — interchangeable per environment
   UI-injected         local: ImageGrab/mss   pyautogui         pymodbus
   dispatcher          remote: capture agent   remote agent      ...
   (Tk/Qt/Web/CLI)     (web)                   (web)
```

**Reclassification of v2 "controllers" (R-HEX-4).** Each splits into a **Core Service**
(inside) and a thin **UI Adapter** (outside) that only forwards intents to the facade and
renders events:

| v2 unit | Core Service (inside hexagon) | UI Adapter (outside) |
|---|---|---|
| `ImportController` | `ImportService` (sheet/column-map parse, persist) | file-picker dialog |
| `MonitorController` | monitor list via `ScreenInfoPort`, selection state | minimap/thumbnail drawing |
| `ZoneController` | zone data + persistence (geometry) | overlay window (drawing) |
| `ModeController` | mode state on the scenario | mode buttons |
| `RunController` | *(none — it becomes intent-forwarding only)* | run/stop/pause buttons → facade |
| `SettingsController` | `ConfigProvider` read/write | settings dialog |
| `CardConfigController` | card-config data model | card-config dialog |
| `DiagnosticsController` | OCR-monitor uses core perception | help/preview windows |
| `HotkeyController` | — | OS hotkey adapter (driving) |
| `StatsView`/`ExecutionStateView`/`LogSink` | — | event-driven UI adapters |

> **Rule of thumb:** if removing Tkinter would break it, it is a **UI Adapter**. If it would
> still compile and pass tests headless, it is a **Core Service**.

### 1.1 Lifecycle & thread-affinity model (with `EventDispatcher`)

The core runs on background worker threads and **never** calls a UI toolkit. It hands every
outbound event to the injected **`EventDispatcher`**, whose adapter re-enters the UI's own
loop safely. The core is identical for all four UIs; only the dispatcher differs.

```
worker thread (core)                 EventDispatcher (port)         UI loop (adapter)
  emit(StepCompleted) ───────────►   dispatch(event) ──────────►   Tk:  root.after(0, ...)
                                                                   Qt:  pyqtSignal.emit(...)
                                                                   Web: asyncio queue → WS push
                                                                   CLI: synchronous handler
```

| Unit group | Instance scope | Thread affinity |
|---|---|---|
| `WilloWispCoreAPI` (the facade) | **singleton (per-app)** | call-from-any-thread; returns fast, runs work on workers |
| `EventDispatcher` (port; UI-supplied impl) | **per-app, injected at startup** | **owned by the UI**; marshals worker→UI-loop |
| `ConfigProvider`, `SeverityColorClassifier`, `ProtocolManager`, registry, `EventBus`, `LoadManifest`, `AssetLibrary` (+repos/persistence/file store) | singleton | thread-safe / either |
| Perception + evidence services + `ScreenCapturePort`/`InputControlPort`/`OcrPort` impls | singleton, stateless (injected) | **driven adapters**; invoked on the **worker** thread |
| Core application services (`ImportService`, `DefaultFlowBuilder`, `SuiteScheduler`, run/verify units, `ReportService`, `WorkspaceSession`) | per-app or per-run | **worker / pure** — no UI thread dependency |
| **UI Adapters** (`AppShell`, all views/dialogs/overlays, the thin intent-forwarding controllers, `LogSink`, hotkeys) | per-app | **the UI's own loop only** (Tk main / Qt / web request) |
| `SuiteExecutionThread` | per-run | **is** the worker thread |
| `FrameSampleCoordinator` | per-step | worker, **timing-sensitive — may not cross a latency-adding boundary** |
| `ExecContext` | per-point mutable state | worker; not shared across points |

> No core unit is bound to "the Tk main thread." Thread re-entry is **entirely** the
> `EventDispatcher` adapter's job — that is what makes the UI swappable.

### 1.2 State ownership, injection & the `WilloWispCoreAPI` facade (B4)

**The facade is the single inbound port (R-HEX-1).** It owns *no* logic itself; it exposes a
stable, UI-agnostic surface and delegates to the core services constructed by the composition
root. Illustrative method groups (contracts, not implementations):

```
WilloWispCoreAPI                      # constructed once; injected with all core services + ports
  # lifecycle / wiring
  set_event_dispatcher(dispatcher)    # UI injects its EventDispatcher (R-HEX-2)
  subscribe(event_type, handler)      # convenience over the EventBus
  shutdown()
  # IO list / profiles
  list_monitors() -> [MonitorInfo]    # via ScreenInfoPort (no GUI dependency)
  import_io_list(path, sheet, column_map) -> ProfileRef
  list_profiles() / load_profile(ref)
  # capability catalogue — drives schema-generated UI (R-EXT-1)
  list_step_types() -> [CapabilityMeta]          # key, name, category, params_schema, addable
  get_param_schema(step_key) -> JSONSchema        # the form contract; UI renders generically
  list_report_widgets() / list_binding_kinds() / list_protocols()
  # scenario authoring (pure data in/out — no widgets)
  get_scenario(id) / set_mode(id, mode)
  save_zones(id, [Zone]) / get_zones(id)         # Zone = pure geometry (R-HEX-3)
  build_default_flow(id) -> Flow
  get_flow(id) / save_flow(id, Flow) / edit_step(id, step) / apply_to_all(id, step)
  # assets
  assets() -> AssetLibrary façade (read/CRUD) ; resolve_binding(binding)
  # execution (returns immediately; progress arrives via EventDispatcher)
  start_suite(suite_config) -> RunHandle
  stop() / pause() / resume() / get_run_state() -> RunState
  # reporting (offline, from persisted results)
  list_templates() / generate_report(template_key, results_ref) -> path
  # config
  get_config() / update_config(patch)
```

- **Per-point run state (`ExecContext`)** is created and owned by `PointRunCoordinator`
  (inside the core), passed by reference into the engine; capabilities mutate it through its
  typed surface, never via globals. It never escapes the core to a UI.
- **Driven ports are injected, not imported.** `ScreenCapturePort`, `InputControlPort`,
  `ProtocolPort`, `OcrPort`, `FileSystemPort`, `ClockPort` are interfaces; the composition
  root binds an environment-specific adapter (local desktop vs remote capture agent for web).
- **Ambient values are owned, injected singletons** (`ConfigProvider`,
  `SeverityColorClassifier`, `LoadManifest`); **no module-level globals** as source of truth.

### 1.3 Startup ordering (owned by `AppCompositionRoot`, per UI)
Each UI ships its own composition root that builds the **same** core and injects **its own**
adapters:
```
1 load config                         (ConfigProvider)
2 bind driven adapters to ports       (ScreenCapture/Input/Protocol/Ocr per environment)
3 init OCR                            (OcrPort impl)
4 build registry → discover plugins → register legacy adapters → LoadManifest
5 construct core services + WilloWispCoreAPI (inject services + ports)
6 inject the UI's EventDispatcher; wire event subscribers (reporting, recorder)
7 build the UI adapter (Tk/Qt/Web/CLI) bound ONLY to WilloWispCoreAPI
8 enter the UI's own loop
```
Steps 1–6 are identical across UIs; only 2, 7, 8 differ — the proof of swappability.

### 1.4 Event-driven decoupling via the dispatcher
Core run/verify/report units **emit** lifecycle/progress events to the `EventBus`; the
`EventDispatcher` adapter delivers them onto the UI's loop; UI adapters render them. **No core
unit holds a UI handle or calls a UI toolkit** (retires Planning K3 and enforces R-HEX-2).

### 1.5 Guardrail rule (B8)
Every `*Coordinator`/`*Controller`/`*Service`/facade **must** declare an explicit
**"does NOT own"** list (below). A unit found owning a forbidden concern fails review. The
highest-risk unit, `RunController`, is split so it cannot accrete (see §5).

### 1.6 Design preconditions inherited from the audit
- **B2 — one canonical run path.** `SuiteScheduler` is declared canonical. The legacy
  `_run_scenario_legacy_iscs` / `ISCS_Engine.run` paths are **removed only after** a one-time
  behavioural-equivalence check; until then they remain untouched behind the new path.
- **B7 — characterization first.** Before any god method moves, a snapshot/characterization
  test must pin its current output: `SuiteRunner.run` (run trace), `verify_alarm_panel`
  (PASS/FAIL rows on fixture frames), `_write_html_report` (golden HTML), and
  `auto_register_procedures` (the generated flow). These are gates, not part of this design.

### 1.7 Extension points (zero blast radius) and schema-driven UI

The **only** sanctioned way to extend behaviour is to register into one of four registries —
all already live. Each is reached by the UI **only** through the facade catalogue methods
(§1.2), so a new plugin is visible to **every** UI without GUI edits.

| Extension | Registry / interface | Add a feature by | Untouched by construction |
|---|---|---|---|
| Step type (capability) | capability `registry` + `@register`, `CapabilityMeta` | one file in `plugins/` | engine, enum, dispatcher, **all GUI files** |
| Protocol | `ProtocolManager` + `BaseProtocol` (`ProtocolPort`) | implement + register | `SuiteScheduler`, `PointRunCoordinator`, run units |
| Report widget | `register_widget` + `ReportWidget` | one widget subclass | page shell, other widgets, templates |
| Verification resolver | `register_binding_resolver` + `BindingResolver` | one resolver | `verify_custom`, `BindingExecutor` |

**Schema-driven forms (R-EXT-1).** A capability declares `meta.params_schema` (a JSON schema:
field name → {type, default, label, choices, …}). The facade exposes it via
`get_param_schema(step_key)`. Each UI ships **one** generic **`SchemaFormRenderer`** (a UI
adapter) that builds a form from any schema — so dropping in a plugin with new params yields a
working editor with **zero GUI edits**, and the **same schema** renders as a Tk form, a Qt
form, or an HTML form. This is the intersection of R-HEX (UI-agnostic contract) and R-EXT
(zero blast radius): the parameter schema is the contract; the renderer is per-UI and generic.

> **Guardrail:** no UI file may contain a per-step-type form. A hand-coded form for a specific
> capability is an R-EXT-1 violation; the only permitted form code is the generic
> `SchemaFormRenderer`.

---

## 2. `ISCSVerifier` (S1) — perception vs decision vs evidence vs orchestration

### 2.1 Complete method → owner map (no orphans)
| Method | Lines | Owner |
|---|---:|---|
| `verify_alarm_panel` | 256 | `VerificationCoordinator` (orchestration) → see §2.3 split |
| `verify_list` | 59 | `ListVerificationPolicy` (+coordinator) |
| `verify` | 23 | **superseded** by the policies — kept only until callers confirmed gone, then deleted (precondition check) |
| `_color_present` | 28 | `ColorComparator` (+`ColorSampler`) |
| `_blink_color_present` | 21 | `BlinkAnalyzer` |
| `_get_zone_bbox` | 14 | `ZoneResolver` |
| `_grab_zone` | 12 | **split:** `ScreenCaptureService.grab` + `EvidenceScreenshotWriter.write` |
| `_get_color_name` | 6 | `SeverityColorClassifier` |
| `_ocr_image` | 4 | `OcrReader` |
| `_analyze_image`/`_preprocess_for_ocr` | 2/2 | `OcrPreprocessor` |
| `__init__` | 9 | `VerificationCoordinator` (injected collaborators) |

### 2.2 Class tree
```
verification (logical)
  perception/  ScreenCaptureService · ZoneResolver · OcrReader · OcrPreprocessor ·
               TextMatcher · ColorSampler · ColorComparator · SeverityColorClassifier ·
               BlinkAnalyzer · FrameSampleCoordinator · TimestampExtractor · ClockSyncEvaluator ·
               StatePoller
  decision/    AlarmPanelVerificationPolicy · NormalizationVerificationPolicy · ListVerificationPolicy
  evidence/    EvidenceScreenshotWriter
  orchestration/ VerificationCoordinator
```

### 2.3 God-method split — `verify_alarm_panel` (256 → actions)
```
VerificationCoordinator.verify_alarm_panel(expected, ctx)
 ├─ ZoneResolver.resolve("alarm_panel")              -> bbox
 ├─ StatePoller.poll(bbox, id, value, duration)      -> best_frame, text   (the poll loop)
 ├─ FrameSampleCoordinator.window(bbox)              -> frames
 │     └─ ColorComparator / BlinkAnalyzer            -> {colour, blink}
 ├─ TimestampExtractor.find(text) + ClockSyncEvaluator.within(...)  -> dt pass/fail
 ├─ AlarmPanelVerificationPolicy.decide(id,desc,value,severity,colour,dt) -> rows, overall
 └─ EvidenceScreenshotWriter.write(best_frame, point, overall)     -> path
```
`StatePoller` is the previously-buried poll loop, now its own action. The policy receives a
**pre-collected perception bundle** (resolves Q-D2 in favour of *capture-then-decide*).

### 2.4 Why / why-not (guardrails)
- **VerificationCoordinator** owns *sequencing only*. **Does NOT own** OCR, colour, blink,
  timestamp, decision, or evidence.
- **AlarmPanelVerificationPolicy** owns *rules*. **Does NOT own** perception or screen access
  (must be testable from a fixture bundle).
- **SeverityColorClassifier** is the **single** owner of the colour matrix.

---

## 3. `ProcedureRunner` (S1) — engine

### 3.1 Method → owner map
| Method | Owner |
|---|---|
| `_run_point` (112) | `PointExecutor` → §3.3 |
| `_execute_procedure` (89) | split `StepLifecycle` + `StepDispatcher` → §3.3 |
| `run_scenario` (88) / `run_standalone` (44) | `FlowRunCoordinator` |
| `_exec_*` (19) | `LegacyExecutorAdapters` (quarantined) |
| `_make_skip_result` (11) | **`PointExecutor`** (skip is produced during iteration) |
| `_emit` (9) | injected event emitter |
| `_sleep`/`_check_pause` | `RunControl` |
| `__init__` | `FlowRunCoordinator` |

### 3.2 Class tree
```
engine: FlowRunCoordinator · PointExecutor · DependencyGate · StepLifecycle ·
        StepDispatcher · RunControl · LegacyExecutorAdapters
```

### 3.3 God-method splits
```
PointExecutor.execute(io_group, ctx)                 # was _run_point (112)
 ├─ order_enabled(steps)                              -> ordered list
 ├─ for step:
 │    DependencyGate.passed(step, results)? --no--> PointExecutor.make_skip_result(step)
 │    else: StepLifecycle.run(step, ctx)
 └─ return [ProcedureResult]

StepLifecycle.run(step, ctx)                          # cross-cutting half of _execute_procedure
 ├─ emit StepStarted
 ├─ try:  result = StepDispatcher.dispatch(step, ctx)
 ├─ except: result = ERROR(...)
 ├─ emit StepCompleted / Verification{Passed,Failed}
 └─ return result

StepDispatcher.dispatch(step, ctx)                    # dispatch half of _execute_procedure
 ├─ cap = registry.get(step.key)
 ├─ sr  = cap.execute(ctx)                             # StepResult
 └─ map sr -> (status, verify_results, screenshot)     # ProcedureResult fields
```

### 3.4 Why / why-not
- **StepDispatcher** owns *key→result*; **does NOT own** iteration, lifecycle, or capability
  logic. **StepLifecycle** owns *scaffolding* (timing/events/error). **PointExecutor** owns
  *sequencing within a point*; **does NOT own** suite looping.

---

## 4. `SuiteRunner` + `ISCS_Engine` (S1+S2) — one canonical run path

### 4.1 Method → owner map
| Method | Owner |
|---|---|
| `run` (167) | `SuiteExecutionThread` + `SuiteScheduler` + `PointRunCoordinator` → §4.3 |
| `_run_scenario` (160) | collapses into the above |
| `_run_scenario_legacy_iscs` (232) / `ISCS_Engine.run` (318) | **removed after equivalence proof** (B2) |
| `_take_screenshot` (30) | `ScreenCaptureService` + `EvidencePathManager` |
| `_collect_failed_point_ids` (17) | `RerunController` |
| `_on_event_card_started/completed` | `RecorderCoordinator` |
| `_emit`/`stop`/`_sleep`/pause/resume | `RunControl` |
| `__init__` | `SuiteExecutionThread` |

### 4.2 Class tree
```
run: SuiteExecutionThread · SuiteScheduler · PointRunCoordinator · RerunController ·
     EvidencePathManager · RunProgressReporter · (RecorderCoordinator, ReportTrigger)
```

### 4.3 God-method split — the run loop
```
SuiteExecutionThread.run()
 ├─ for work in SuiteScheduler.plan(suite):           # card × loop × point (canonical)
 │     ctx = PointRunCoordinator.build_context(work)   # owns ExecContext (§1.2)
 │     PointRunCoordinator.run(ctx) -> FlowRunCoordinator (engine)
 │     EvidencePathManager.point_dir(work)             # dirs + naming
 │     RunProgressReporter.emit(progress)              # UI subscribes; no UI handle
 │     if failed: RerunController.enqueue(work)
 ├─ for rework in RerunController.drain(): ...          # rerun-on-fail policy
 └─ ReportTrigger.emit(SuiteCompleted)                  # reporting subscribes
```

### 4.4 Why / why-not
- **SuiteScheduler** owns *what runs and in what order/count*; **does NOT own** execution or
  rerun decisions. **RerunController** owns *rerun policy* only. **RunProgressReporter** owns
  *outbound progress* and **breaks the UI back-reference** (K3). **EvidencePathManager** owns
  the on-disk layout, injected so the verification evidence writer agrees on paths.

---

## 5. `App` (S1) — shell + composition root + one controller per workflow

### 5.1 Complete method → owner map (every prior orphan now owned)
| Method(s) | Owner |
|---|---|
| `_build_ui`(136), `_on_resize`, `_shake_window`, `_set_taskbar_icon`, `destroy` | `AppShell` (window/layout) |
| `__init__`(61) wiring | `AppCompositionRoot` |
| `_settings_dialog`(124) | **`SettingsController`** (new) — edits via `ConfigProvider` |
| `_excel_file_loaded`/`_load_excel`/`_excel_load_failed`/`_load_profile_from_metadata`/`_open_metadata_browser` | `ImportController` |
| `_draw_minimap`/`_capture_monitor_thumbnail`/`_refresh_monitors`/`_on_screen_selected`/`_find_monitor_by_info` | `MonitorController` (minimap render → `StatsView`) |
| `_open_overlay`/`_overlay_done`/`_load_zones`/`_save_zones`/`_update_overlay_btn` | `ZoneController` |
| `_set_mode`/`_on_mode_change`/`_update_mode_buttons` | `ModeController` |
| `_run_test`/`_stop_test`/`_test_finished`/`_toggle_pause`/`_toggle_suite`/`_cb_*`/`_on_auto_paused` | `RunController` |
| `set_execution_state`(45) | **`ExecutionStateView`** (new) — view-only enable/disable; `RunController` *requests* it |
| `_register_hotkeys`/`_unregister_hotkeys`/`_hk_*` | `HotkeyController` |
| `_update_stats`/`_refresh_stats_only` | `StatsView` |
| `_build_help_content`/`_init_help_panel`/`_open_ocr_monitor`/`_open_preview`/`_close_preview`/`_toggle_preview` | `DiagnosticsController` |
| `_log` | `LogSink` |
| `_notify_profile_listeners` | `ProfileEventHub` |
| `_clear_workspace`(12) | **`WorkspaceSession.reset()`** (new) — broadcasts; controllers subscribe |
| `_sync_open_card_config`(12) | **`CardConfigController`** (new, owns `SuiteCardConfigDialog`) |

### 5.2 Class tree — split across the hexagon boundary
The v2 `App` god class splits into a **core half** (behind `WilloWispCoreAPI`) and a **UI-adapter
half** (replaceable per framework). The UI half holds **no business logic** — it forwards
intents to the facade and renders events from the dispatcher.

```
CORE (inside hexagon, behind WilloWispCoreAPI)
  WorkspaceSession        current working set (profile/monitor/zones/mode) + reset broadcast
  ImportService           sheet/column-map parse + persist
  (run/verify/report/asset/config services live in §2–§4, §9, §10)

UI ADAPTER (outside — Tkinter today; swappable)
  AppShell                window, layout, taskbar, resize         (Tk-only)
  TkCompositionRoot       builds core + injects TkEventDispatcher  (per-UI, §1.3)
  TkEventDispatcher       marshals worker events via root.after    (the port impl)
  views/   StatsView · ExecutionStateView · LogSink   (render events only)
  intent-forwarders (thin):
    ImportView      → WilloWispCoreAPI.import_io_list / list_profiles
    MonitorView     → list_monitors / select; draws minimap
    ZoneView        → save_zones / get_zones; hosts the overlay adapter (§8)
    ModeView        → set_mode
    RunControls     → start_suite / stop / pause / resume   (NO widget logic beyond enable/disable)
    SettingsView    → get_config / update_config
    CardConfigView  → card-config get/save
    DiagnosticsView → help/preview; OCR-monitor reads core perception
    HotkeyAdapter   → maps OS hotkeys to facade calls
```

### 5.3 Why / why-not + guardrails
- **AppShell / TkCompositionRoot / TkEventDispatcher** are **UI Adapters** — replacing them
  with `QtShell`/`WebApp` + their own dispatcher swaps the entire UI with **zero core change**.
- **WorkspaceSession** (core) owns the *current working set* and the *reset* broadcast,
  resolving the `_clear_workspace` orphan; the UI subscribes to the reset event.
- **`RunControls` (was the H-risk `RunController`)** is now a **dumb intent-forwarder**: it
  calls `WilloWispCoreAPI.start_suite/stop/pause/resume` and toggles its own enabled/disabled
  state from `RunState` events. It **does NOT own** scheduling, step logic, recording,
  reporting, or any other view's widgets. This both defuses the audit's top aggregation risk
  **and** is the proof of R-HEX-1: a Web "Run" button calls the identical facade method.
- **No UI adapter imports the core's collaborators**; it holds only a reference to
  `WilloWispCoreAPI` and the `EventDispatcher`. **No core service imports `tkinter`.**

---

## 6. `SuitePanel` (S2)
**Map:** list/reorder/scroll → `SuiteListView`; `_save_suite`/`_load_suite`/`_json_safe` →
`SuiteDocumentStore`; `_run_suite`/`_run_flow`/`_cb_*`/`_finish`/`_on_rerun_toggle` →
`SuiteRunController`; recording methods → `RecordingController`; `_open_report_picker` →
`ReportPickerController`; `_add_current`/`_ask_name`/`_rename_scenario`/`_remove`/`_move`/
`_open_flow_dialog`/`_edit_card_cfg`/`_rebuild_cards` → `CardActionsController`.
```
suite-ui: SuiteListView(View) · SuiteDocumentStore(Model/IO) · SuiteRunController ·
          RecordingController · ReportPickerController · CardActionsController
```
**Why/why-not:** the View renders only; the Store owns format/versioning; each Controller owns
one workflow and **does NOT own** runner/recorder/report internals — it invokes those
subsystems. `_edit_card_cfg` delegates to the App's `CardConfigController` (single card-config
owner across the app).

## 7. `ProcedureFlowDialog` (S2)
**Map:** tree render/selection → `FlowTreeView`; step CRUD/move/find/summary →
`StepEditController` on `FlowEditModel`; `_quick_add`/`_pick_point` → `QuickAddController`;
`_apply_to_all`/`_delete_from_all`/`_resolve_selected_groups`/`_sel_iids` →
`BulkEditController`; `_load_template`/`_save_template` → `TemplateController`;
`_save_step_as_check_card`/`_open_assets`/`_open_check_gallery` → **`CheckAuthoringController`**
(new — owns the flow-editor↔asset/check-gallery seam the audit flagged); `_step_value_summary`
→ `FlowEditModel` (pure formatting of a step), rendered by the View; `_toast` → `FlowTreeView`.
```
flow-editor-ui: FlowTreeView(View) · FlowEditModel(Model) · StepEditController ·
                QuickAddController · BulkEditController · TemplateController · CheckAuthoringController
```
**Why/why-not:** editing logic separated from rendering → `FlowEditModel` is unit-testable
(add/move/bulk-apply) with no Tk. `CheckAuthoringController` is the **single** owner of the
cross-subsystem seam; the dialog no longer reaches into engine/asset internals directly.
**Per-step parameter forms are NOT owned here:** the step editor delegates to the generic
`SchemaFormRenderer` (§1.7), which builds the form from the capability's `params_schema` fetched
via the facade. There is **no per-step-type form code** in the flow editor (R-EXT-1) — adding a
plugin adds its editor for free, in any UI.

## 8. `OverlayWindow` (S2) — pure geometry (core) vs canvas (UI adapter)

This is the sharpest test of R-HEX-3: zone capture must work the same whether the user draws
on a Tk `Canvas`, an HTML `<canvas>`, or a Qt `QGraphicsScene`. So the **geometry is pure
core data** and the **drawing/interaction is a replaceable adapter** that produces and consumes
that data through the facade.

### 8.1 Split across the boundary
```
CORE (pure geometry — no toolkit)
  Zone / Region            normalized, absolute-desktop coordinates (domain value objects)
  ZoneLayout               the set of zones for a scenario/page + invariants (size-check, overlap)
  ZoneEditSession          add/move/delete/change-type/undo over ZoneLayout (pure state machine)
  CoordinateModel          normalization math: absolute-desktop ↔ normalized fractions
                           (NO canvas/pixel/widget concept)

UI ADAPTER (Tkinter today; swappable)
  ZoneCanvasView           draw/redraw/erase zones + saved indicators        (Tk Canvas)
  DrawingInteractionAdapter mouse press/drag/release/hover, hit-test, cursor (drag physics)
  CanvasViewport           canvas-pixel ↔ absolute-desktop mapping (knows the widget/zoom/pan)
  ZoneToolbarView          type/mode buttons
```

### 8.2 Collaboration (draw a zone, then persist)
```
DrawingInteractionAdapter (gesture in canvas pixels)
  └─ CanvasViewport.to_absolute(px,py) ──► absolute coords        (adapter-side, widget-aware)
       └─ ZoneEditSession.add(Zone(absolute…)) ──► ZoneLayout     (core, pure)
            └─ ZoneCanvasView.render(ZoneLayout via CanvasViewport.to_canvas)  (adapter)
On "save": UI calls WilloWispCoreAPI.save_zones(scenario_id, ZoneLayout.zones)  (pure geometry)
```

### 8.3 Why / why-not
- **`CoordinateModel` (core) vs `CanvasViewport` (adapter)** is the key distinction: the core
  does *normalization math* with no notion of a canvas; the adapter does *pixel↔desktop*
  mapping because only it knows the widget, zoom, and pan. A Web overlay supplies its own
  `CanvasViewport`; the core math is untouched.
- **`ZoneEditSession` + `ZoneLayout` (core)** make zone editing + undo + size/overlap checks
  unit-testable with **no canvas** — and reusable by any UI.
- **`ZoneCanvasView` / `DrawingInteractionAdapter` (adapter)** own all Tk drawing and drag
  physics; replacing them does not touch a line of core geometry. They **do NOT own** the zone
  data — they emit edits into `ZoneEditSession` and render its `ZoneLayout`.
- The facade only ever exchanges **`Zone` value objects** with the UI (R-HEX-3) — never canvas
  items or widget coordinates.

## 9. `AssetManager` (S3, by request)
**Map:** per-entity CRUD → `TextAssetRepository`/`ImageAssetRepository`/`RegionRepository`/
`FlowTemplateRepository`; **image create splits** metadata→repo + bytes→`ImageFileStore`;
`_next_id`/`_bump_counter` → `IdSequencer`; `_load`/`save`/`_json_path`/`_migrate_assets_dict`
→ `AssetPersistence`; `get_image_path`/`images_dir` → `ImageFileStore`; `resolve_binding` →
`BindingResolutionService`; `search` → `AssetSearch`; `instance`/`reset`/`stats`/`__repr__` →
`AssetLibrary` (facade).
```
assets: AssetLibrary(facade) · {Text,Image,Region,FlowTemplate}Repository · IdSequencer ·
        AssetPersistence · ImageFileStore · BindingResolutionService · AssetSearch
```
**Why/why-not + guardrail:** each Repository owns one entity; `AssetPersistence` owns the file
format+versioning (a repo never touches disk); `ImageFileStore` owns binary files only.
`AssetLibrary` owns **composition only** and **does NOT own** CRUD/IO/IDs — preserving the
module's standalone (no-kernel-dependency) property. Lifetime: singleton today; whether it
stays a singleton facade or becomes injected is confirmed in Migration (it does not block).

---

## 10. Supporting god-method decompositions (methods, not classes)

These were flagged by the audit (B1/B6) and are decomposed here even though their hosts were
not in the original nine.

### 10.1 `_write_html_report` (1,128) → reuse the widget/template model
```
LegacyReportComposer (a registered template, FR-30a)
 ├─ ResultViewBuilder.build(raw)            -> ResultView   (the stable data contract)
 ├─ ReportPageShell.open()                  -> page + legacy CSS
 ├─ widgets, each rendering from ResultView:
 │    SummaryHeaderWidget · KpiPanelWidget · FailureCategoryWidget ·
 │    PerPointTraceWidget · EvidenceGalleryWidget · RerunHistoryWidget
 └─ ReportPageShell.close()
```
The 1,128-line method becomes a composer + ~6 single-section widgets over the existing
`ResultView`. **Owner of layout:** the widgets; **owner of data shape:** `ResultViewBuilder`;
neither owns the other. (Gated by a golden-HTML characterization test, §1.6.)

### 10.2 `auto_register_procedures` (205) → rule-per-step (Specification)
```
DefaultFlowBuilder.build(sc, zones, nav)
 ├─ ApplicabilityFacts.collect(sc, zones, nav)        # has_points, has_alarm_panel, nav coords…
 ├─ for rule in [TriggerRule, VerifyAlarmPanelRule, NavigateAlarmListRule, VerifyAlarmListRule,
 │               NavigateEventListRule, VerifyEventListRule, NavigateEquipRule, VerifyEquipRule,
 │               ReturnHomeRule, ResetRule, VerifyNormalizeRule]:
 │     if rule.applies(facts): steps.append(rule.make_step(order))
 └─ FlowAssembler.clone_per_io_group(steps, sc.points)
```
Each `*Rule` owns *one step's applicability + construction* (realizes FR-21). `DefaultFlowBuilder`
owns *assembly only*.

### 10.3 `FailureEvidenceCollector.collect` (220) → per-artifact collectors
```
EvidenceCollector.collect(point)
 ├─ ScreenshotArtifactCollector
 ├─ CroppedZoneArtifactCollector
 ├─ DiagnosticsArtifactCollector
 └─ ArtifactManifestBuilder   -> manifest
```

### 10.4 `normalize_results` (213) → router + mappers (stable contract preserved)
```
ResultNormalizer.normalize(raw)
 ├─ sort_by_attempt(raw)
 ├─ for item: ShapeRouter -> {WorkflowStepsMapper | LegacyFieldsMapper} ; CustomCheckMapper
 ├─ FailureClassifier.categorize(reason) -> category
 └─ AttemptAggregator.merge(by_point) -> records   # output shape UNCHANGED
```
The output contract is unchanged (already golden-tested); only the internal transform is split.

---

## 11. Readiness traceability

| Audit blocker | Closed by |
|---|---|
| B1 god-method decomposition | §2.3, §3.3, §4.3, §10.1–10.4 |
| B2 duplicate run-path | §1.6 + §4.1 (canonical = `SuiteScheduler`; legacy removed post-proof) |
| B3 orphans | §2.1 (`verify`, `_grab_zone`), §3.1 (`_make_skip_result`), §5.1 (settings/workspace/card-config), §7 (check-authoring seam) |
| B4 shared-service & state | §1.2 |
| B5 lifecycle/thread/startup | §1.1, §1.3 |
| B6 `_write_html_report` | §10.1 |
| B7 characterization-first | §1.6 (precondition) |
| B8 must-not-own guardrails | §2.4, §3.4, §4.4, §5.3, §6, §9 (esp. `RunControls` intent-only split in §5.3) |
| **B9 strict UI boundary decoupling** | §1.0 (hexagon + reclassification), §1.1 (dispatcher thread model), §1.2 (facade + ports), §5.2–5.3 (App split), §8 (geometry vs canvas) |

| Hexagonal rule | Realized by |
|---|---|
| R-HEX-1 one inbound gate | `WilloWispCoreAPI` facade — §1.2; the only thing UI adapters import (§5.2) |
| R-HEX-2 abstract event marshalling | `EventDispatcher` port, UI-injected — §1.1, §1.4 |
| R-HEX-3 pure coordinate models | `Zone`/`ZoneLayout`/`CoordinateModel` core vs `CanvasViewport`/canvas adapter — §8 |
| R-HEX-4 boundary reclassification | Core-Service vs UI-Adapter table — §1.0 |
| R-EXT-1 pluggable step types + schema UI | capability registry + `SchemaFormRenderer` — §1.7, §7 |
| R-EXT-2 pluggable protocols | `ProtocolManager`/`BaseProtocol` behind `ProtocolPort` — §1.7, §4.4 |
| R-EXT-3 pluggable report widgets | `register_widget`/`ReportWidget` — §1.7, §10.1 |
| R-EXT-4 pluggable verification resolvers | `register_binding_resolver`/`BindingResolver` — §1.7, §9 |

> **Next:** on re-audit ≥ ~85 (now including **B9**), the **Migration** phase orders these
> units into shippable, test-gated steps (driven ports + core services first; the Tkinter
> adapter built last on top of `WilloWispCoreAPI`; a CLI adapter built to **prove headless
> execution**; one rig re-validation after the run/perception move).
