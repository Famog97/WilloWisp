# WilloWisp — Decomposition Design (ownership all the way down)

**Role:** Principal Software Architect · **Phase:** 2 of 3 — **Design**
**Builds on:** [`RESTRUCTURE_PLANNING.md`](RESTRUCTURE_PLANNING.md) · **Date:** 2026-06-25
**Status:** Draft for review

> This is the **ownership-decomposition design**. For every **S1/S2 god class** found
> in Planning it: (1) lists responsibilities, (2) groups them, (3) assigns ownership,
> (4) designs replacement components, (5) shows a collaboration diagram, (6) shows the
> final class tree, (7) says why each class exists, and (8) says why each class does
> **not** own neighbouring responsibilities.
>
> Names here are **logical ownership units**, not a folder layout — physical packaging
> and the move sequence are the **Migration** phase. This document decomposes
> `ISCSVerifier`, `ProcedureRunner`, `SuiteRunner`/`ISCS_Engine`, `App`, `SuitePanel`,
> `ProcedureFlowDialog`, `OverlayWindow`, and `AssetManager` into **~55 single-reason
> units**.

## Design rule

```
Subsystem  owns  Modules
Module     owns  Components
Component  owns  Classes
Class      owns  Responsibilities
Method     owns  one action
```

**Do not stop decomposition when a responsibility reaches a module.** Continue until
**every unit has exactly one reason to change.** A class that names ≥2 concerns in its
"owns" line is not done.

**Recurring ownership pattern for UI god-classes** (View/Model/Controller split):
- a **View** owns *rendering + widget tree* (and nothing else),
- a **Model** owns *edited state + invariants*,
- one **Controller per workflow** owns *user-intent → model/service calls*,
- the original window shrinks to a **Shell** that owns *window lifecycle + composition*.

### Map of god classes → ownership units

| God class (severity, size) | # units | Owning concern after split |
|---|---:|---|
| `ISCSVerifier` (S1, 450/12) | 13 | perception vs decision vs evidence vs orchestration |
| `ProcedureRunner` (S1, 820/28) | 7 | step dispatch vs lifecycle vs point-loop vs legacy adapters |
| `SuiteRunner`+`ISCS_Engine` (S1+S2, 697+487) | 8 | one canonical run path: thread/schedule/rerun/evidence/progress |
| `App` (S1, 1136/53) | 12 | shell + composition root + one controller per workflow |
| `SuitePanel` (S2, 898/31) | 6 | suite view vs store vs run/record/report controllers |
| `ProcedureFlowDialog` (S2, 875/33) | 6 | flow tree view vs edit model vs edit/bulk/template controllers |
| `OverlayWindow` (S2, 570/32) | 6 | canvas view vs zone model vs interaction/toolbar/transform |
| `AssetManager` (S3*, 510/35) | 9 | per-entity repos vs persistence vs ids vs images vs binding |

\* included by explicit request; its size warrants the same treatment.

---

## 1. `ISCSVerifier` (S1) — the flagship decomposition

### 1.1 Responsibilities (from its 12 methods)
Screen capture (`_grab_zone`); zone→bbox resolution incl. visual anchoring
(`_get_zone_bbox`); OCR orchestration (`_ocr_image`, `_analyze_image`,
`_preprocess_for_ocr`); noise-tolerant text matching (delegates to module helpers);
colour-presence test (`_color_present`); blink detection (`_blink_color_present`,
`BLINK_GREY`); severity→colour naming (`_get_color_name` + severity matrix);
timestamp extraction + clock-sync evaluation (inside `verify_alarm_panel`); the
multi-frame **poll/sampler coordination**; the **pass/fail policy** for five
sub-checks + overall (inside `verify_alarm_panel`/`verify_list`); evidence screenshot
writing.

### 1.2 Grouping → 1.3 Ownership
| Group | Single reason to change | Owner |
|---|---|---|
| Capture | how we grab pixels of a zone | `ScreenCaptureService` |
| Zone resolution | how a zone name → bbox (incl. anchoring) | `ZoneResolver` |
| OCR read | how text is read from an image | `OcrReader` (wraps existing OCR) |
| Text match | how OCR noise is tolerated | `TextMatcher` |
| Colour sample/compare | how a colour is found within tolerance | `ColorSampler`, `ColorComparator` |
| Colour meaning | rgb ↔ severity name | `SeverityColorClassifier` |
| Blink | colour↔grey cycling | `BlinkAnalyzer` |
| Frame sampling | drive multi-frame/burst window | `FrameSampleCoordinator` |
| Timestamp | extract + sync-evaluate the SCADA clock | `TimestampExtractor`, `ClockSyncEvaluator` |
| Decision | compose sub-checks → pass/fail | `AlarmPanelVerificationPolicy`, `NormalizationVerificationPolicy`, `ListVerificationPolicy` |
| Evidence | write the labelled screenshot | `EvidenceScreenshotWriter` |
| Orchestration | sequence the above for one verification | `VerificationCoordinator` |

### 1.4 Replacement components / 1.6 Final class tree
```
verification (logical)
  perception/
    ScreenCaptureService       grab(bbox) -> frame
    ZoneResolver               resolve(zone_name) -> bbox  (anchor-aware)
    OcrReader                  read(frame, layout) -> text
    TextMatcher                contains / fuzzy / canonical
    ColorSampler               pixels(frame) -> samples
    ColorComparator            matches(samples, rgb, tol) -> bool
    SeverityColorClassifier    name(rgb) | color(severity)   (owns the matrix)
    BlinkAnalyzer              evaluate(frames) -> {target, blink}
    FrameSampleCoordinator     run(window) -> frames
    TimestampExtractor         find(text) -> datetime | None
    ClockSyncEvaluator         within(parsed, trigger, limit) -> bool
  decision/
    AlarmPanelVerificationPolicy     decide(perception_inputs) -> StepResult rows
    NormalizationVerificationPolicy  (same, normal-state rules)
    ListVerificationPolicy           (alarm/event list rules)
  evidence/
    EvidenceScreenshotWriter   write(frame, point, status) -> path
  orchestration/
    VerificationCoordinator    verify(kind, expected, ctx) -> result
```

### 1.5 Collaboration diagram (verify an alarm panel)
```
VerificationCoordinator
  ├─ ZoneResolver.resolve("alarm_panel") ───────────► bbox
  ├─ FrameSampleCoordinator.run(bbox, window) ──────► frames
  │     └─ uses ScreenCaptureService.grab(bbox)
  ├─ OcrReader.read(best_frame) ──► text ──► TextMatcher (id/desc/value/severity)
  ├─ ColorSampler+ColorComparator / BlinkAnalyzer ─► {colour, blink}
  ├─ TimestampExtractor + ClockSyncEvaluator ──────► datetime pass/fail
  ├─ AlarmPanelVerificationPolicy.decide(...) ─────► StepResult rows + overall
  └─ EvidenceScreenshotWriter.write(best_frame) ───► evidence path
```

### 1.7 Why each exists / 1.8 Why it does NOT own neighbours
- **VerificationCoordinator** — exists to *sequence* a verification. Does **not** own
  OCR, colour, blink, timestamp, or evidence: each is independently reusable and
  testable; mixing them is what made the 256-line method untestable.
- **AlarmPanelVerificationPolicy** — exists to hold *rules* (which sub-checks, how
  PASS/FAIL is decided). Does **not** own *perception*: rules must be testable with
  fixture inputs, with no screen.
- **ScreenCaptureService / OcrReader / ColorSampler** — exist so perception is mockable
  and reusable (the OCR monitor panel uses the same readers). They do **not** own
  *decision*: perception answers "what is on screen," never "did it pass."
- **SeverityColorClassifier** — exists as the *single* owner of the severity↔colour
  matrix. No other unit hard-codes colours.
- **EvidenceScreenshotWriter** — exists so "save proof" is one concern; does **not**
  own *decision* (it's told the status, it doesn't compute it).

> This mirrors the target the planning example sketched: perception, decision, and
> evidence become independent; the coordinator owns *only* orchestration.

---

## 2. `ProcedureRunner` (S1) — engine

### 2.1 Responsibilities (28 methods)
Per-point step loop (`_run_point`); single-step dispatch (`_execute_procedure`:
registry resolve → `execute` → `StepResult`→`ProcedureResult` mapping → event emit →
exception→`ERROR`); the 19 legacy `_exec_*` executors (now vestigial fallbacks);
run entry points (`run_scenario`, `run_standalone`); skip-result construction;
pause/sleep; event emission.

### 2.2–2.3 Grouping → ownership
| Group | Reason to change | Owner |
|---|---|---|
| One-step dispatch | how a step key → result (+ error wrap, status map) | `StepDispatcher` |
| Step lifecycle | cross-cutting timing/screenshot/event scaffolding | `StepLifecycle` (the `BaseCapability` template-method) |
| Point loop | order/enabled/depends_on iteration over a point's steps | `PointExecutor` |
| Dependency rule | evaluate `depends_on` gating | `DependencyGate` |
| Run entry | drive a flow for a scenario / standalone | `FlowRunCoordinator` |
| Legacy fallback | the vestigial `_exec_*` safety net | `LegacyExecutorAdapters` (isolated) |
| Pause/stop/sleep | run-control signals | `RunControl` |

### 2.5 Collaboration (run one point)
```
FlowRunCoordinator.run(flow, ctx)
  └─ PointExecutor.execute(io_group, ctx)
       for step in ordered/enabled:
         DependencyGate.passed(step, results)? ──no──► skip
         StepLifecycle.around(step):                 (timing, events, error→ERROR)
            StepDispatcher.dispatch(step.key, ctx) ─► registry.get(key).execute(ctx)
       └─ returns [ProcedureResult]
```

### 2.6 Class tree
```
engine (logical)
  StepDispatcher           resolve+execute one capability, map result, wrap errors
  StepLifecycle            timing/screenshot/event scaffolding (template-method)
  DependencyGate           depends_on evaluation
  PointExecutor            iterate one point's ordered steps
  FlowRunCoordinator       run_scenario / run_standalone entry
  RunControl               pause/resume/stop/sleep
  LegacyExecutorAdapters   the _exec_* fallback, quarantined
```

### 2.7–2.8 Why / why-not
- **StepDispatcher** exists to be the *one* place a key becomes a result. Does **not**
  own capability *logic* (that's the plugins) or *iteration* (that's `PointExecutor`).
- **PointExecutor** owns *sequencing within a point*. Does **not** own *what a step
  does* or *suite-level looping* (that's the suite layer).
- **StepLifecycle** owns the *cross-cutting* concerns that were smeared inside
  `_execute_procedure`; isolating it lets every capability share scaffolding without
  duplicating it.
- **LegacyExecutorAdapters** exists only as the documented safety net; quarantining it
  keeps the live path clean and makes its eventual removal a one-unit deletion.

---

## 3. `SuiteRunner` + `ISCS_Engine` (S1 + S2) — one canonical run path

> Planning candidate #12: these encode **overlapping run behavior** (`SuiteRunner.run`
> 167, `_run_scenario` 160, `_run_scenario_legacy_iscs` 232; `ISCS_Engine.run` 318).
> Design **collapses them into one** set of units; the duplicate paths disappear.

### 3.1 Responsibilities
Worker-thread lifecycle; card × loop × point iteration; rerun-on-fail; evidence
directory layout + screenshots; recorder coordination (already event-driven); report
handoff (emit `SuiteCompleted`); pause/stop; UI progress callbacks.

### 3.2–3.3 Grouping → ownership
| Group | Reason to change | Owner |
|---|---|---|
| Thread lifecycle | start/stop the background worker | `SuiteExecutionThread` |
| Scheduling | expand cards × loops × points → work items | `SuiteScheduler` |
| Per-point coordination | run one point via the engine, collect result | `PointRunCoordinator` |
| Rerun policy | which failed points re-run, how many times | `RerunController` |
| Evidence layout | suite/loop/point dirs + screenshot naming | `EvidencePathManager` |
| Progress | emit progress events (UI subscribes) | `RunProgressReporter` |
| Recording | start/stop per card via events | `RecorderCoordinator` (exists) |
| Reporting trigger | emit `SuiteCompleted` | `ReportTrigger` (exists, event) |

### 3.5 Collaboration
```
SuiteExecutionThread.run()
  └─ for work in SuiteScheduler.plan(suite):          # card,loop,point
       PointRunCoordinator.run(work) ──► engine.FlowRunCoordinator
       RunProgressReporter.emit(progress)             # UI subscribes; no UI handle
       if work.point failed: RerunController.consider(work)
  └─ ReportTrigger.emit(SuiteCompleted)               # reporting subscribes
EvidencePathManager supplies dirs/paths to coordinator + verifier evidence writer
```

### 3.6 Class tree
```
run (logical)
  SuiteExecutionThread     thread lifecycle only
  SuiteScheduler           card×loop×point planning (one path; legacy path removed)
  PointRunCoordinator      bridge a work item to the engine, gather result
  RerunController          rerun-on-fail policy
  EvidencePathManager      directory/file layout + naming
  RunProgressReporter      progress as events (replaces UI callbacks)
  (RecorderCoordinator, ReportTrigger — already event-driven)
```

### 3.7–3.8 Why / why-not
- **SuiteScheduler** exists to make "what runs, in what order, how many times" explicit
  and testable. Does **not** own *step execution* (engine) or *thread mechanics*.
- **RunProgressReporter** exists to **break the UI back-reference** (K3): the runner
  emits events; the UI renders them. The runner does **not** own the UI.
- **EvidencePathManager** owns the on-disk layout so both the coordinator and the
  verification evidence writer agree on paths without sharing a god object.
- Collapsing `ISCS_Engine` removes a parallel path (retires drift risk K7).

---

## 4. `App` (S1) — shell + composition root + one controller per workflow

### 4.1 Responsibilities (53 methods, ≥9 workflows)
Window/lifecycle/layout; service wiring; Excel/metadata IO import; monitor
enumeration/selection/thumbnails/minimap; zone overlay open/save/load; run-mode
selection; run start/stop/pause + execution state; global hotkeys; stats rendering;
help + OCR-monitor + preview panels; logging surface; profile-change notifications.

### 4.2–4.3 Grouping → ownership
| Group | Reason to change | Owner |
|---|---|---|
| Window/layout/taskbar | the app shell | `AppShell` |
| Service wiring | how subsystems are constructed/injected | `AppCompositionRoot` |
| IO import | Excel/metadata import flow | `ImportController` |
| Monitors | enumerate/select/thumbnail/minimap | `MonitorController` |
| Zones | overlay open + load/save zones | `ZoneController` |
| Mode | run-mode selection state | `ModeController` |
| Run | start/stop/pause/execution-state | `RunController` |
| Hotkeys | global hotkey binding | `HotkeyController` |
| Stats | stats + minimap rendering | `StatsView` |
| Diagnostics | help/OCR-monitor/preview | `DiagnosticsController` |
| Logging | the log surface | `LogSink` |
| Profiles | profile-change fan-out | `ProfileEventHub` |

### 4.5 Collaboration (run a test, abridged)
```
AppShell hosts views; AppCompositionRoot injects services.
RunController.start():
   reads ModeController + ZoneController + selected profile
   → constructs run via the run subsystem (SuiteExecutionThread)
   → subscribes StatsView + LogSink to progress/lifecycle events
ImportController.import() → MetadataStore → ProfileEventHub.publish(changed)
   → MonitorController / SuitePanel refresh via subscription
```

### 4.6 Class tree
```
app (logical)
  AppShell               window, layout, taskbar, resize
  AppCompositionRoot     build + inject subsystems (the wiring/bootstrap)
  controllers/
    ImportController  MonitorController  ZoneController  ModeController
    RunController     HotkeyController   DiagnosticsController
  views/
    StatsView  LogSink
  events/
    ProfileEventHub
```

### 4.7–4.8 Why / why-not
- **AppShell** exists to own *only* the window. It does **not** own any workflow —
  each is a controller — so adding a feature touches one controller, not a 1,136-line
  class.
- **AppCompositionRoot** exists so wiring lives in one place (testable, swappable for
  fakes). It does **not** own behavior; it only assembles owners.
- **Each controller** owns one user-facing workflow and does **not** reach into the
  others; they coordinate through `ProfileEventHub`/the event bus, not direct calls.
- **LogSink** exists so "where text goes" is one seam — services emit, the sink
  renders. Services do **not** call the UI log directly (breaks K3 coupling).

---

## 5. `SuitePanel` (S2)

**5.1 Responsibilities:** card-list view/reorder; suite save/load/serialize; suite run
start/stop/progress; per-card recording; report-picker; launch flow editor / card
config; add/rename/remove card.

**5.2–5.3 / 5.6 Class tree**
```
suite-ui (logical)
  SuiteListView          render cards, selection, reorder, scrolling   (View)
  SuiteDocumentStore     save/load/_json_safe serialization            (Model/IO)
  SuiteRunController      start/stop/progress bridge to the run subsystem
  RecordingController     toggle/start/stop recorder + settings
  ReportPickerController  the 📊 picker flow
  CardActionsController   add/rename/remove/edit-config/open-flow
```

**5.5 Collaboration:** `SuiteListView` raises intents → `CardActionsController` mutates
the suite document (`SuiteDocumentStore`); `SuiteRunController` starts the run subsystem
and subscribes the view to progress events; `RecordingController`/`ReportPickerController`
own their own flows.

**5.7–5.8 Why / why-not:** the **View** owns rendering and nothing else; the **Store**
owns persistence (so format/versioning is one place); each **Controller** owns one
workflow and does **not** own the runner, recorder, or report internals — it *invokes*
those subsystems. The panel no longer both *draws* and *runs* and *saves*.

---

## 6. `ProcedureFlowDialog` (S2)

**6.1 Responsibilities:** flow-tree rendering/selection/collapse; step CRUD
(add/insert/edit/duplicate/delete/enable/disable/move/summary/find); quick-add palette +
coordinate pick; bulk apply/delete across IO groups; template load/save +
save-step-as-check; launch asset/gallery sub-dialogs.

**6.6 Class tree**
```
flow-editor-ui (logical)
  FlowTreeView           tree render, selection, expand/collapse           (View)
  FlowEditModel          the in-memory flow being edited + invariants      (Model)
  StepEditController     single-step CRUD + move + summary
  QuickAddController     palette + _pick_point coordinate capture
  BulkEditController     apply-to-all / delete-from-all across groups
  TemplateController     load/save templates, save-step-as-check
```

**6.5 Collaboration:** `FlowTreeView` emits selection/intent → controllers operate on
`FlowEditModel` → view re-renders from the model. Sub-dialogs are launched by the
relevant controller, not the view.

**6.7–6.8 Why / why-not:** editing logic is separated from rendering so the **Model**
is unit-testable (add/move/bulk-apply) without Tk. Each controller owns one editing
mode and does **not** own the tree widget or the engine internals; today the dialog
reaches into engine/model internals directly (the engine↔editor coupling, K3).

---

## 7. `OverlayWindow` (S2)

**7.1 Responsibilities:** canvas drawing of zones/indicators; mouse interaction
(press/drag/release/right-click/hover, hit-testing, cursors); zone model ops
(create/resize/delete/clear/change-type/size-check); undo stack; toolbar (mode/type);
anchor linking; page change; canvas↔absolute coordinate transforms.

**7.6 Class tree**
```
zone-capture-ui (logical)
  ZoneCanvasView            draw zones/indicators, redraw, erase           (View)
  DrawingInteractionController  mouse → create/resize/select (hit-test)
  ZoneEditModel             zones + undo stack + invariants (size check)   (Model)
  ZoneToolbar               mode/type selection                           (View)
  CoordinateTransform       canvas ↔ absolute desktop space
  AnchorLinker              link a zone to a visual anchor
```

**7.5 Collaboration:** `DrawingInteractionController` turns gestures (via
`CoordinateTransform`) into `ZoneEditModel` mutations; `ZoneCanvasView` renders from the
model; `ZoneToolbar` sets the active mode; undo lives in the model.

**7.7–7.8 Why / why-not:** the **Model** (zones + undo) becomes testable without a
canvas; the **View** only draws; the **Controller** only interprets input. The
`CoordinateTransform` is isolated because off-by-one monitor-offset bugs are a single,
testable concern. None owns its neighbour.

---

## 8. `AssetManager` (S3, by request)

**8.1 Responsibilities:** CRUD for four entity types (text/image/region/template);
ID counters; JSON persistence + schema migration; image-file management; binding
resolution; search; stats; singleton lifecycle.

**8.2–8.3 / 8.6 Class tree**
```
assets (logical)
  repositories/
    TextAssetRepository  ImageAssetRepository  RegionRepository  FlowTemplateRepository
                          (each: create/update/delete/get/list for ONE entity)
  IdSequencer            per-category counters (TXT_/IMG_/RGN_/TPL_)
  AssetPersistence       _load/save/migrate the JSON document
  ImageFileStore         image bytes on disk (assets/images)
  BindingResolutionService  resolve_binding (region+asset → resolved inputs)
  AssetSearch            cross-entity search
  AssetLibrary           facade/singleton: composes the repos for callers
```

**8.5 Collaboration:** `AssetLibrary` holds the four repositories + `IdSequencer`;
mutations flow repo → `AssetPersistence.save`; `BindingResolutionService` reads repos +
`ImageFileStore` to resolve a binding; `AssetSearch` queries across repos.

**8.7–8.8 Why / why-not:** each **Repository** owns exactly one entity's lifecycle;
**AssetPersistence** owns the file format + versioning (one place), so a repo never
touches disk; **ImageFileStore** owns binary files separately from metadata;
**BindingResolutionService** owns resolution and does **not** own CRUD. The
`AssetLibrary` facade owns *composition*, not storage — preserving the module's
"standalone, no kernel dependency" property.

---

## 9. Cross-cutting design decisions (apply to all of the above)

- **Break UI back-references with events.** Runners/services **emit** lifecycle/progress
  events; views **subscribe**. No service holds a UI handle (retires K3). This reuses
  the existing event bus that already drives reporting/recording.
- **Perception ≠ decision ≠ evidence ≠ orchestration.** This separation (most visible
  in §1) is the template for the whole system: "what is true" vs "did it pass" vs
  "prove it" vs "sequence it."
- **One canonical run path.** `ISCS_Engine` and the legacy scenario path fold into the
  §2/§3 units; no parallel runners survive.
- **Ambient state becomes injected.** Configuration, the availability manifest, and the
  severity matrix are owned by explicit units (`SeverityColorClassifier`, a config
  provider, the existing load manifest) and **injected**, not read from module globals.
- **Stable contracts untouched.** Step keys, persisted formats, the plugin contract,
  registry keys, and report output do not change — every unit above is an *internal*
  ownership refactor.

## 10. Open design questions to confirm before Migration

- **Q-D1** Is `StepLifecycle` realized as a concrete base/template the capabilities opt
  into, or as a wrapper the dispatcher applies? (Affects plugin authors.)
- **Q-D2** Do verification **policies** consume a *pre-collected* perception bundle
  (capture once, decide), or call perception lazily? (Affects timing/sampler ownership.)
- **Q-D3** Is `EvidencePathManager` shared by the runner *and* the verification evidence
  writer via injection, or does the runner pass paths down? (Avoids a new shared global.)
- **Q-D4** How far do we push the `App` controller split now vs. leave some flows on the
  shell temporarily? (Value vs. churn — controllers are independently shippable.)
- **Q-D5** Does `AssetLibrary` stay a singleton facade (current behavior) or become an
  injected dependency? (Backward-compat vs. testability.)
- **Q-D6** For the report writer god-method (`_write_html_report`, S1, 1,128 lines): is
  it decomposed into the existing widget/template model now, or tracked as a parallel
  effort? (It is a *method* not a class, hence out of this class-level pass — flag it.)

> **Next:** on approval, the **Migration** phase orders these ~55 units into shippable,
> test-gated steps (leaves → UI last; one canonical run path; events before extraction),
> with per-step verification and a single rig re-validation after the run/perception move.
