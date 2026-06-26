# WilloWisp — Migration Plan (leaves-first, Hexagonal)

**Role:** Principal Engineer · **Phase:** 3 of 3 — **Migration**
**Approved design:** [`RESTRUCTURE_DESIGN.md`](RESTRUCTURE_DESIGN.md) (v3, Hexagonal) ·
**Gate audit:** [`RESTRUCTURE_MIGRATION_READINESS.md`](RESTRUCTURE_MIGRATION_READINESS.md)
**Date:** 2026-06-25 · **Status:** Ready to execute

> The ordered, shippable move list to transition WilloWisp to the approved Hexagonal
> architecture **without changing behavior**. Strategy: **bottom-up / leaves-first** — define
> the boundary (ports), migrate the hexagon-interior leaves, assemble the core behind the
> `WilloWispCoreAPI` facade, prove the boundary with a **headless CLI adapter**, then build the
> Tkinter adapter **on top of** the established core. This document specifies *what moves, in
> what order, behind what shim, and which gate proves it* — **no implementation code**.

## Operating rules (apply to every step)
- **Move, don't rewrite.** Logic is relocated and wrapped, not re-implemented (R1).
- **Strangler shims.** Old import paths (`baru`, `iscs_workflow`) keep working via re-export
  shims until the final cutover; `main` is never broken (R5).
- **Tests gate every step.** The full suite (259 today) must pass after each step; a step is
  not "done" until green (NR4). Each step is independently shippable + reversible.
- **Characterization before god methods (B7).** No god method moves until a snapshot test pins
  its current output.
- **One canonical run path (B2).** The legacy/duplicate run paths are not collapsed until an
  equivalence harness proves they match.
- **UI last; live path validated once.** The Tkinter adapter moves last; a single rig
  re-validation follows the run/perception relocation (NR5).
- **Mechanical guards tighten as code moves.** An import-cycle check and a "core imports no
  UI/OS-automation toolkit" check (B9) run in CI, scoped to migrated packages and widened each
  step.

---

## M0 — Preconditions (gate before Step 1)

> Not optional: the readiness audit makes these prerequisites. M0 changes **no behavior** and
> moves **no logic** — it builds the safety net.

| # | Action | Gate / Done-when | Closes |
|---|---|---|---|
| M0.1 | Add **characterization/snapshot tests** pinning current output of the god methods: `SuiteRunner.run` (run trace on a fake-port run), `verify_alarm_panel` (PASS/FAIL rows on fixture frames), `_write_html_report` (golden HTML), `auto_register_procedures` (generated flow). `normalize_results` golden already exists. | New tests green on **current** code | B7 |
| M0.2 | Add **mechanical guards** in CI: an import-cycle check and a "core-package may not import `tkinter`/`pyautogui`/`keyboard`/native hooks" check. Initially scoped to the (empty) new core package. | Checks run; pass (vacuously) | B9 |
| M0.3 | Create the **package skeleton + re-export shims**: the new core/adapter package roots exist; `baru`/`iscs_workflow` re-export from them. **No logic moves.** | Full suite green; app launches; `import baru` unchanged | R5 |
| M0.4 | Build the **run-path equivalence harness**: capture the legacy run path's offline-observable output vs the (future) `SuiteScheduler` path, to be asserted equal before any collapse. | Harness records a baseline | B2 |

**Exit M0 when:** characterization tests + mechanical guards are in CI, the skeleton + shims are
in place, and the full suite is green.

---

## M1 — Step 1: Define core interfaces (Ports)

> Leaves of the dependency graph. Pure interfaces + thin local adapters wrapping existing
> behavior. Lowest-risk step.

| # | Unit(s) | Action | Gate | Notes |
|---|---|---|---|---|
| M1.1 | `EventDispatcher` (port) | Define the abstract dispatch contract (ordering/threading guarantees). Provide a **synchronous** default impl for headless/tests. | Unit tests on the sync dispatcher | R-HEX-2 |
| M1.2 | `ScreenCapturePort`, `InputControlPort`, `OcrPort`, `FileSystemPort`, `ClockPort` | Define interfaces; implement **local desktop adapters** wrapping the current impls (ImageGrab/mss; pyautogui; `iscs_OCR`; stdlib). Behavior-neutral wrappers. | Per-port adapter tests (mock the underlying) | R-HEX driven ports |
| M1.3 | `ProtocolPort` | **Promote** the existing `BaseProtocol`/`ProtocolManager` to the port (already a registry). | Existing protocol tests green | R-EXT-2 |

**Exit M1 when:** all ports exist with local adapters + tests; nothing in the app imports them
yet; suite green.

---

## M2 — Step 2: Migrate low-level utilities & repositories (the leaves)

> Move the hexagon-interior leaves behind shims, **one unit per step**, each gated. These have
> no UI/engine dependencies. Decompose the leaf-level god methods here (with M0 tests as the
> net).

| # | Cluster | Units moved | Gate |
|---|---|---|---|
| M2.1 | **Domain value objects** | `Zone` (pure geometry), `Monitor`, `IOPoint`, `Procedure`/`IOGroup`/`ProcedureFlow` → core domain (shimmed) | Serialization + golden tests green |
| M2.2 | **Config & ambient** | `ConfigProvider`, `SeverityColorClassifier` (owns the matrix), `LoadManifest` (exists), capability `registry` (exists) → injected singletons; remove module-global source-of-truth | Manifest/registry tests; app launches |
| M2.3 | **Assets** | Split `AssetManager` → `{Text,Image,Region,FlowTemplate}Repository` · `IdSequencer` · `AssetPersistence` · `ImageFileStore` · `BindingResolutionService` · `AssetSearch` · `AssetLibrary` facade | Existing asset tests green (already strong) |
| M2.4 | **Perception** | From `ISCSVerifier`: `OcrReader`/`OcrPreprocessor`/`TextMatcher` · `ScreenCaptureService` (via port) · `ColorSampler`/`ColorComparator` · `BlinkAnalyzer` · `TimestampExtractor`/`ClockSyncEvaluator` · `FrameSampleCoordinator` · `StatePoller` · `EvidenceScreenshotWriter` · `EvidencePathManager` | `verify_alarm_panel` characterization (M0.1) green |
| M2.5 | **Reporting data** | Split `normalize_results` → `ResultNormalizer` (`ShapeRouter`+mappers+`FailureClassifier`+`AttemptAggregator`); **contract unchanged**. Decompose `_write_html_report` → `LegacyReportComposer` + section widgets over `ResultView` (the widget model already exists). | `normalize_results` golden + `_write_html_report` golden HTML green |
| M2.6 | **Evidence collector** | Split `FailureEvidenceCollector.collect` → per-artifact collectors + manifest builder | Evidence characterization green |

**Exit M2 when:** the leaves are relocated behind shims, the leaf god methods are decomposed,
the core-import guard (B9) passes for these packages, and the suite is green.

---

## M3 — Step 3: Implement the headless `WilloWispCoreAPI` facade + core services

> Assemble the application core. This is where the **engine/run/verify god methods** decompose
> and the **duplicate run path collapses** (after B2). All headless; gated by the M0 tests.

| # | Subsystem | Units | Gate |
|---|---|---|---|
| M3.1 | **Engine** | `StepDispatcher` · `StepLifecycle` · `DependencyGate` · `PointExecutor` · `FlowRunCoordinator` · `RunControl` · `LegacyExecutorAdapters` (quarantined) — from `ProcedureRunner` | Run-trace + dispatch tests green |
| M3.2 | **Verification orchestration** | `VerificationCoordinator` + `AlarmPanel/Normalization/List` policies (capture-then-decide) over the M2.4 perception units | `verify_alarm_panel` characterization green |
| M3.3 | **Default-flow** | `DefaultFlowBuilder` + per-step `*Rule`s (Specification, FR-21) — from `auto_register_procedures` | `auto_register` characterization green |
| M3.4 | **Run subsystem** | `SuiteExecutionThread` · `SuiteScheduler` (canonical) · `PointRunCoordinator` (owns `ExecContext`) · `RerunController` · `RunProgressReporter` (events, no UI handle) · `RecorderCoordinator`/`ReportTrigger` (exist) | **B2 equivalence harness asserts the new path == legacy**; legacy path kept but unused |
| M3.5 | **Application services** | `ImportService` · `WorkspaceSession` · `ReportService` | Service unit tests green |
| M3.6 | **Facade** | `WilloWispCoreAPI` assembling all services + ports behind the single inbound gate; catalogue methods (`list_step_types`/`get_param_schema`/…) | **Headless integration test**: drive author→run(fake ports)→report entirely through the facade |

**Exit M3 when:** the full author→run→report cycle runs **headlessly through the facade** with
fake/local ports, the new run path is proven equivalent to the legacy one, and the suite is
green. The legacy run path still exists (removed in M6).

---

## M4 — Step 4: Build the CLI adapter (proves B9 + B10)

> The swappability proof. A minimal driving adapter that imports **only** `WilloWispCoreAPI`.

| # | Action | Gate | Proves |
|---|---|---|---|
| M4.1 | **CLI composition root** — build the core, inject the **sync `EventDispatcher`** and **local (or fake) driven adapters**, bind to the facade. | CLI launches headless | R-HEX-1/3 startup |
| M4.2 | **CLI commands** mapping to facade methods (import IO list · build/edit flow · run suite · generate report). | A scripted end-to-end CLI run produces a report | R-HEX-1 |
| M4.3 | **B9 proof** — the core-import guard is widened to **all** core packages: no `tkinter`/`pyautogui`/`keyboard`/native hooks imported; the CLI drives author→run→report with **no GUI toolkit loaded**. | Import-ban check + headless e2e green | **B9** |
| M4.4 | **B10 proof** — **drop-in tests**: add a dummy capability (with `params_schema`), protocol, report widget, and binding resolver; assert **no existing file changed**, each feature works, and the capability's form is **schema-derivable** (a form-spec emitted from `get_param_schema`, no GUI). | Four drop-in tests green | **B10** |

**Exit M4 when:** the CLI runs the full cycle headlessly, the core toolkit-import ban passes,
and the four drop-in extensibility tests pass. **The UI is now provably swappable.**

---

## M5 — Step 5: Build the Tkinter adapter on top of the Core API

> The existing GUI is rebuilt as a **driving adapter** that holds only a `WilloWispCoreAPI`
> reference and a `TkEventDispatcher`. No business logic re-enters the UI.

| # | Adapter unit(s) | Action | Gate |
|---|---|---|---|
| M5.1 | `TkCompositionRoot` + `TkEventDispatcher` | Build the core; inject a dispatcher that marshals worker events via `root.after`. | App launches on the facade |
| M5.2 | `AppShell` + `StatsView`/`ExecutionStateView`/`LogSink` | Window/layout + event-rendering views (subscribe via dispatcher). | UI renders run events |
| M5.3 | Intent-forwarders | `RunControls`/`ImportView`/`ModeView`/`SettingsView`/`CardConfigView`/`DiagnosticsView`/`HotkeyAdapter` call the facade **only**. | No UI unit imports core collaborators |
| M5.4 | `SchemaFormRenderer` | One generic form builder from `params_schema`; **delete hand-coded per-step forms** in the flow editor (R-EXT-1). | Existing + new step types render generically |
| M5.5 | Overlay split | `ZoneCanvasView` + `DrawingInteractionAdapter` + `CanvasViewport` (adapter) over core `ZoneLayout`/`ZoneEditSession`/`CoordinateModel` (R-HEX-3). | Zone draw/save round-trips pure `Zone` data |
| M5.6 | Flow editor + suite panel adapters | `FlowTreeView`/`SuiteListView` etc. drive the facade; persistence via the core. | Editor/suite flows work on the facade |
| M5.7 | **Live rig re-validation (NR5)** | Run a real suite on the SCADA rig through the new Tk adapter: trigger→verify→reset→report, navigation, recording, all report templates. | **User-confirmed equivalent behavior on the rig** |

**Exit M5 when:** the Tkinter adapter runs entirely on `WilloWispCoreAPI`, the suite is green,
and the live suite is rig-validated. Two front-ends (Tk + CLI) now share one core.

---

## M6 — Cutover & cleanup

| # | Action | Gate |
|---|---|---|
| M6.1 | Remove the duplicate/legacy run path (`ISCS_Engine`/`_run_scenario_legacy_iscs`) — **only** now that the canonical path is rig-confirmed. | Suite green; rig spot-check |
| M6.2 | Remove the `ProcedureType`/legacy `_exec_*` fallback **only if** desired (it is the documented safety net — may be retained). | Coverage check still 19/19 |
| M6.3 | Remove compatibility shims; retire `baru.py`/`iscs_workflow.py` (the composition roots are the entry points). | `import baru` removed; app + CLI launch |
| M6.4 | Tighten mechanical guards to the whole tree: full Tk-ban on core, acyclic graph enforced. | CI guards green |
| M6.5 | Update `CLAUDE.md` / `SYSTEM_BLUEPRINT.md` to the new structure. | Docs match reality |

**Exit M6 (initiative done) when:** god-modules retired, core toolkit-free + acyclic, CLI
headless + Tk rig-validated, all public contracts intact, docs current.

---

## Master ordering & risk/blocker coverage

```
M0 preconditions ─► M1 ports ─► M2 leaves ─► M3 core+facade ─► M4 CLI ─► M5 Tk ─► M6 cutover
   (B7,B2 net)       (R-HEX     (decompose     (decompose god   (B9,B10  (UI last, (collapse
                      ports)     leaf methods)  methods; B2      proofs)   rig)      legacy)
                                                collapse)
```

| Phase | Retires / proves |
|---|---|
| M0 | B7 (characterization), B2 harness, B9 guard scaffolding |
| M1 | R-HEX driven ports defined |
| M2 | leaf god methods (`normalize_results`, `_write_html_report`, perception, `collect`); B9 guard widened |
| M3 | engine/run/verify god methods; **B2** equivalence; one canonical path |
| M4 | **B9** (headless, toolkit-free) + **B10** (drop-in extensibility) |
| M5 | UI-adapter swap; R-HEX-3 geometry split; R-EXT-1 schema forms; **NR5** rig re-validation |
| M6 | god-modules retired; legacy path removed; acyclic + toolkit-free enforced |

## Global Definition of Done
1. Full suite green **after every step** (not just at the end).
2. Core packages import **no** UI/OS-automation toolkit; import graph is **acyclic** (CI-checked).
3. **CLI adapter** drives author→run→report **headlessly**; the four **drop-in** extensibility
   tests pass.
4. **Tkinter adapter** runs only on `WilloWispCoreAPI`; live suite **rig-validated once**.
5. `baru.py` / `iscs_workflow.py` god-modules retired; single composition-root entry per UI.
6. All public contracts intact (step keys, persisted formats, plugin API, report output).
7. `CLAUDE.md` / `SYSTEM_BLUEPRINT.md` updated to the delivered structure.

> Execution note: M0–M2 are offline and low-risk (ship rapidly). M3 is the heaviest (god-method
> decomposition + path collapse) — keep one unit per PR. M4 is the swappability milestone. M5 is
> the only step needing the rig. M6 is reversible cleanup.
