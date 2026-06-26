# WilloWisp — Decomposition Design (ownership all the way down)

**Role:** Principal Software Architect · **Phase:** 2 of 3 — **Design (v2, readiness-hardened)**
**Builds on:** [`RESTRUCTURE_PLANNING.md`](RESTRUCTURE_PLANNING.md) ·
**Audited by:** [`RESTRUCTURE_MIGRATION_READINESS.md`](RESTRUCTURE_MIGRATION_READINESS.md)
**Date:** 2026-06-25 · **Status:** Draft for re-audit

> This revision closes the audit blockers **B1–B8**: every significant method now has an
> owner (no orphans), the god **methods** are decomposed to the action level, and
> lifecycle / thread / state ownership, startup ordering, and "must-not-own" guardrails
> are specified. Names are **logical ownership units**, not a folder layout; physical
> packaging and the move order are the **Migration** phase.

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

### 1.1 Lifecycle & thread-affinity model
Every unit declares an **instance scope** and a **thread affinity**. This is binding.

| Unit group | Instance scope | Thread affinity |
|---|---|---|
| `ConfigProvider`, `SeverityColorClassifier`, `ProtocolManager`, capability `registry`, `EventBus`, `LoadManifest`, `AssetLibrary` (+repos/persistence/file store) | **singleton (per-app)** | thread-safe / either |
| `OcrReader`, `OcrPreprocessor`, `TextMatcher`, `ScreenCaptureService`, `ColorSampler/Comparator`, `BlinkAnalyzer`, `TimestampExtractor`, `ClockSyncEvaluator`, `EvidenceScreenshotWriter`, `EvidencePathManager` | **singleton, stateless** (injected) | callable on **worker** thread (screen grab + OCR must be off the Tk loop) |
| `AppShell`, `AppCompositionRoot`, all `*Controller`/`*View`, `LogSink`, `ProfileEventHub`, `WorkspaceSession` | **per-app** | **Tk main thread only** |
| `SuiteExecutionThread` | **per-run** | **is** the worker thread |
| `SuiteScheduler`, `PointRunCoordinator`, `RerunController`, `RunProgressReporter`, `RecorderCoordinator`, `ReportTrigger` | **per-run** | worker (progress marshalled to UI via events) |
| `FlowRunCoordinator`, `PointExecutor`, `StepDispatcher`, `StepLifecycle`, `DependencyGate`, `RunControl` | **per-run** | worker |
| `VerificationCoordinator`, the verification **policies** | **per-point** | worker |
| `FrameSampleCoordinator` | **per-step** | worker, **timing-sensitive — may not cross a latency-adding boundary** |
| `ExecContext` | **per-point mutable state** | created on worker; not shared across points |

### 1.2 State ownership & injection (B4)
- **Per-point run state (`ExecContext`)** is **created and owned by `PointRunCoordinator`**,
  passed **by reference** into `FlowRunCoordinator` → capabilities. Capabilities mutate it
  through a **typed surface** (the existing context fields), never via globals. No unit other
  than the current point's coordinator holds a reference after the point completes.
- **Shared stateless services** (`ScreenCaptureService`, `EvidencePathManager`, perception
  units) are **constructed once by `AppCompositionRoot`** and **injected** into both the run
  subsystem and verification — never reconstructed, never global.
- **Ambient values become owned, injected singletons:** configuration → `ConfigProvider`;
  the severity↔colour matrix → `SeverityColorClassifier`; capability availability → the
  existing `LoadManifest`. **No module-level globals remain** as the source of truth.

### 1.3 Startup ordering (owned by `AppCompositionRoot`)
The composition root owns this exact order; nothing else triggers init-on-import:
```
1 load config            (ConfigProvider)
2 init OCR/Tesseract     (OcrReader.initialize)
3 register protocols     (ProtocolManager)
4 build registry → discover plugins → register legacy adapters → build LoadManifest
5 wire event subscribers (reporting, recorder)
6 build AppShell + controllers/views, inject services
7 enter Tk mainloop
```

### 1.4 Event-driven UI decoupling
Run/verify/report units **emit** lifecycle/progress events; **views subscribe**. No service
holds a UI handle. Cross-thread events from the worker are marshalled to the Tk main thread
by the subscribing view. This retires the UI↔logic back-reference (Planning K3).

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

### 5.2 Class tree
```
app: AppShell · AppCompositionRoot · WorkspaceSession · LogSink · ProfileEventHub
  controllers/ ImportController · MonitorController · ZoneController · ModeController ·
               RunController · SettingsController · HotkeyController · DiagnosticsController ·
               CardConfigController
  views/       StatsView · ExecutionStateView
```

### 5.3 Why / why-not + guardrails
- **AppShell** owns *the window*; **does NOT own** any workflow.
- **AppCompositionRoot** owns *wiring + startup order* (§1.3); **does NOT own** behaviour.
- **WorkspaceSession** owns the *current working set* (profile, monitor, zones, mode) and the
  *reset* broadcast — resolving the `_clear_workspace` orphan as one state owner.
- **RunController (was H-risk)** is now *intent-only*: start/stop/pause requests + reacting to
  run events. It **does NOT own** execution-state widget mutation (→ `ExecutionStateView`),
  scheduling, step logic, recording, or reporting. This guardrail defuses the audit's
  top aggregation risk.
- Each controller owns one workflow and coordinates others only via `ProfileEventHub`/the
  event bus — never direct cross-controller calls.

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

## 8. `OverlayWindow` (S2)
**Map:** canvas draw/redraw/erase/indicators → `ZoneCanvasView`; mouse handlers + hit-test +
cursor → `DrawingInteractionController`; zone ops + undo + size-check → `ZoneEditModel`;
toolbar/type/mode → `ZoneToolbar`; `_canvas_to_abs`/`_abs_to_canvas` → `CoordinateTransform`;
`_link_zone_to_anchor` → `AnchorLinker`; `_on_page_change` → `ZoneEditModel`.
```
zone-capture-ui: ZoneCanvasView(View) · DrawingInteractionController · ZoneEditModel(Model) ·
                 ZoneToolbar · CoordinateTransform · AnchorLinker
```
**Why/why-not:** the Model (zones + undo) is testable without a canvas; the View only draws;
`CoordinateTransform` isolates monitor-offset bugs as one testable concern. None owns its
neighbour.

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
| B8 must-not-own guardrails | §2.4, §3.4, §4.4, §5.3, §6, §9 (esp. `RunController` split in §5.3) |

> **Next:** on re-audit ≥ ~85, the **Migration** phase orders these ~65 units into shippable,
> test-gated steps (leaves → UI last; events before extraction; one rig re-validation after
> the run/perception move).
