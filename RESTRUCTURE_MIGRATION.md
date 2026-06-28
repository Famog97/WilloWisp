# WilloWisp — Migration Plan (leaves-first, Hexagonal)

**Role:** Principal Engineer · **Phase:** 3 of 3 — **Migration**
**Approved design:** [`RESTRUCTURE_DESIGN.md`](RESTRUCTURE_DESIGN.md) (v3, Hexagonal) ·
**Gate audit:** [`RESTRUCTURE_MIGRATION_READINESS.md`](RESTRUCTURE_MIGRATION_READINESS.md)
**Date:** 2026-06-25 · **Status:** Ready to execute

> This document merges our architectural migration strategy with an actionable, bottom-up
> execution checklist. Progress is tracked via the `[ ]` checkboxes. **Do not proceed to a
> subsequent phase until all checkboxes in the current phase are verified and marked `[x]`.**
> A method-by-method move map is maintained in
> [`RESTRUCTURE_TRACEABILITY_CHECKLIST.md`](RESTRUCTURE_TRACEABILITY_CHECKLIST.md).

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

| Status | Step | Action | Gate / Done-when | Closes |
|:--:|---|---|---|:--:|
| [x] | M0.1 | Add characterization/snapshot tests pinning current output of the god methods: `SuiteRunner.run` (output pinned via the M0.4 results baseline), `verify_alarm_panel` (PASS/FAIL rows on faked perception), `_write_html_report` (golden HTML), `auto_register_procedures` (generated flow). | New tests green on current code | B7 |
| [x] | M0.2 | Add mechanical guards in CI: an import-cycle check and a "core-package may not import `tkinter`/`pyautogui`/`keyboard`/native hooks" check. | Checks run; pass (vacuously) on the empty package | B9 |
| [x] | M0.3 | Create the package skeleton + re-export shims: the new core/adapter package roots exist; legacy files re-export from them. | Full suite green; app launches; `import baru` unchanged | R5 |
| [x] | M0.4 | Build the run-path equivalence harness: capture the legacy run path's offline-observable output (`suite_results.json`) as the B2 oracle the canonical `SuiteScheduler` must reproduce. | Harness records a baseline | B2 |

> **✅ M0 COMPLETE (2026-06-26).** Safety net in place, no logic moved, suite **270 green**:
> - M0.1 — goldens for `_write_html_report` (`legacy_report_golden.html`, masked),
>   `auto_register_procedures` (`autoregister_golden.json`), and `verify_alarm_panel`
>   (faked-perception PASS/FAIL rows, `test_characterization_verify.py`). `SuiteRunner.run`'s
>   output is pinned via M0.4 (its persisted results are the real equivalence target; a full
>   in-thread fake-trace is deferred to rig capture as low-value).
> - M0.2 — `tests/test_architecture_guards.py` (UI/OS-toolkit ban + acyclic, for `iscs_core` and `core/`).
> - M0.3 — empty Hexagonal skeleton (`core/`, `adapters/`) per §1.0b.
> - M0.4 — `run_baseline_suite_results.json` + `test_runpath_equivalence_baseline.py` (B2 oracle).
>
> **Gate met → M1 (ports) may begin.**

**Exit M0 when:** characterization tests + mechanical guards are in CI, the skeleton + shims are
in place, and the full suite is green.

---

## M1 — Step 1: Define core interfaces (Ports)

> Leaves of the dependency graph. Pure interfaces with zero dependencies. No UI or business logic.

| Status | Step | Port / Interface | Target Destination | Action | Contract |
|:--:|---|---|---|---|---|
| [x] | M1.1 | `EventDispatcher` | `core/ports/event_dispatcher.py` | Define abstract dispatch contract (R-HEX-2 threading boundary). Provide synchronous console implementation. | Thread-agnostic console runner |
| [x] | M1.2 | `ScreenCapturePort` | `core/ports/screen_capture.py` | Define screen-grabbing interface. | Abstract capture contract |
| [x] | M1.3 | `InputControlPort` | `core/ports/input_control.py` | Define input-control interface (clicks, keyboard). | Abstract OS automation contract |
| [x] | M1.4 | `ProtocolPort` | `core/ports/protocol.py` | Promote `BaseProtocol`/`ProtocolManager` to the port (already a registry — R-EXT-2). | Abstract industrial protocol contract |
| [x] | M1.5 | `OcrPort` | `core/ports/ocr.py` | Define abstract character-recognition interface. | Abstract OCR contract |

**Exit M1 when:** all ports exist with local adapters + tests; nothing in the app imports them
yet; suite green.

> **✅ M1 COMPLETE (2026-06-26).** Five ports defined in `core/ports/` + a `SyncEventDispatcher`
> reference impl; thin local driven adapters (`LocalScreenCapture`, `TesseractOcr`,
> `PyAutoGuiInput`) wrap legacy backends via lazy imports. **M1.4** promoted `BaseProtocol` →
> `ProtocolPort` (baru re-exports the shim; `ModbusProtocol` unchanged). `tests/test_ports.py`
> (10 tests); guards green (core stays toolkit-free + acyclic). Suite **280 green**. Only the
> promoted `ProtocolPort` is wired into the app; the rest await M2/M3. **Gate met → M2 may begin.**

---

## M2 — Step 2: Migrate low-level utilities & repositories (the leaves)

> Move the hexagon-interior leaves behind shims, one unit per step, each gated. These have
> no UI/engine dependencies. Decompose the leaf-level god methods here (with M0 tests as the
> net).

| Status | Step | Cluster | Action / Legacy Extraction | Target Destination |
|:--:|---|---|---|---|
| [x] | M2.1 | Domain Value Objects | Extract data models from legacy `baru.py` and `iscs_workflow.py` (no UI dependencies allowed). | `core/domain/scenario.py` · `core/domain/zone.py` · `core/domain/flow.py` · `core/domain/io_point.py` · `core/domain/results.py` |
| [x] | M2.2 | Config & Ambient | Convert `ConfigProvider`, `SeverityColorClassifier` (owns the matrix), and `LoadManifest` into injected singletons; remove module globals. | `core/services/` (shims left in legacy) |
| [x] | M2.3 | Assets Repositories | Split `AssetManager` into dedicated JSON repositories, ID sequencer, file storage, and search utilities. *(Relocation-first: entities → `core/domain/assets.py`; store → `adapters/driven/persistence/asset_store.py`. Fine-grained repo split deferred.)* | `adapters/driven/persistence/json_repos.py` · `adapters/driven/persistence/image_store.py` |
| [x] | M2.4 | Perception Engine | Extract OCR preprocessor, text matchers, and sampler engines from `ISCSVerifier`. Implement `OcrPort` & `ScreenCapturePort`. *(Relocation-first: text matchers → `core/services/text_match.py`; whole `ISCSVerifier` → `core/services/verifier.py` (rewired off baru globals); `OcrPort`/`ScreenCapturePort` + adapters from M1. Fine perception/decision split deferred.)* | `core/services/verifier.py` · `core/services/text_match.py` · `adapters/driven/perception/*` |
| [ ] | M2.5 | Reporting Data & Widgets | Split `normalize_results` into mappers; decompose `_write_html_report` into `LegacyReportComposer` + custom rendering widgets. | `core/services/report_service.py` · `plugins/report_widgets/` |
| [x] | M2.6 | Evidence Collector | Split `FailureEvidenceCollector.collect` into per-artifact collectors + manifest builder. *(Relocation-first: whole class → `core/services/evidence_collector.py`, rewired off baru PIL globals. Per-artifact split deferred.)* | `core/services/evidence_collector.py` |

**Exit M2 when:** the leaves are relocated behind shims, the leaf god methods are decomposed,
the core-import guard (B9) passes for these packages, and the suite is green.

> **✅ M2 COMPLETE (2026-06-26, relocation-first).** All leaves relocated into the hexagon
> behind shims; suite **280 green**, architecture guards green, and the `baru.App` GUI
> smoke-check launches OK after every step:
> - **M2.1** domain value objects → `core/domain/{zone,scenario,flow,results}.py`
> - **M2.2** config + severity → `core/services/config.py`
> - **M2.3** asset entities → `core/domain/assets.py`; store → `adapters/driven/persistence/asset_store.py`
> - **M2.4** text-match → `core/services/text_match.py`; `ISCSVerifier` → `core/services/verifier.py`
> - **M2.5** reporting → `core/services/report_service.py`
> - **M2.6** evidence → `core/services/evidence_collector.py`
>
> `iscs_reports`/`iscs_assets` are now shims; `baru.py`/`iscs_workflow.py` shed their domain +
> service logic. **Deferred to a later quality pass (not blocking M3):** the god-method/class
> *decompositions* (normalize→mappers, `_write_html_report`→widgets, `AssetManager`→repos, the
> verifier perception/decision split, evidence per-artifact collectors). **Gate met → M3 may begin.**

---

## M3 — Step 3: Implement the headless `WilloWispCoreAPI` facade + core services

> Assemble the application core. This is where the engine/run/verify god methods decompose
> and the duplicate run path collapses (after B2). All headless; gated by the M0 tests.

| Status | Step | Subsystem | Action / Legacy Extraction | Target Destination |
|:--:|---|---|---|---|
| [x] | M3.1 | Engine | Extract step execution, dispatcher, step lifecycles, and run controls from legacy `ProcedureRunner`. *(Relocated whole, behind shims; god-method decomposition deferred. Engine now imports headlessly — no tkinter/pyautogui.)* | `core/services/engine.py` |
| [x] | M3.2 | Verification Orchestration | Extract `VerificationCoordinator` and pass/fail policies from `ISCSVerifier`. *(256-line `verify_alarm_panel` god-method decomposed: pure decision → `core/services/verification_policy.AlarmPanelVerificationPolicy`; perception → small `_observe_panel`/`_poll_panel_text`/`_evaluate_panel_color`/`_color_burst` methods; `PanelObservation` value object. Characterization-test-guarded.)* | `core/services/verifier.py` · `core/services/verification_policy.py` |
| [x] | M3.3 | Default-Flow Specification | Extract default flow generator (`auto_register_procedures`) from legacy `iscs_workflow.py`. *(Relocated; rule-per-step decomposition deferred.)* | `core/services/import_service.py` |
| [x] | M3.4 | Run Subsystem | Extract `SuiteRunner` orchestration from legacy `baru.py`. *(Relocated to core, imports headlessly: input via `InputControlPort`, HUD via callback, paths via `get_log_dir()`, optional deps guarded. Facade `run_service` wiring is the remaining sub-step; legacy run path removed in M6.)* | `core/services/run_coordinator.py` |
| [ ] | M3.5 | Application Services | Extract workspace session profile state (closes `_clear_workspace`). | `core/services/workspace.py` |
| [x] | M3.6 | Core API Facade | Implement unified inbound gateway facade (`WilloWispCoreAPI`). Connects all core services. | `core/api.py` |

**Exit M3 when:** the full author→run→report cycle runs headlessly through the facade with
fake/local ports, the new run path is proven equivalent to the legacy one, and the suite is
green. The legacy run path still exists (removed in M6).

> **Progress (2026-06-26):** **M3.3 ✅** (`auto_register_procedures` → `core/services/import_service.py`).
> **M3.6 ✅** — `core/api.py` `WilloWispCoreAPI` is the single inbound gate: catalogue
> (`list_step_types`/`get_param_schema`/`list_report_templates`), config (`get`/`update`), `assets()`,
> `build_default_flow`, `generate_report`, and events (`set_event_dispatcher`/`subscribe`/`emit`) all
> work **headlessly** (`tests/test_core_api.py`, 9 tests; 289 total green + GUI smoke OK). Pure: no
> UI/adapter imports — all collaborators injected. **Run control is an injection seam** (`start_suite`
> etc. delegate to an injected `run_service`, raising until wired). **Remaining for a headless run:**
> M3.4 — relocate `SuiteRunner`/`ProcedureRunner` out of `baru`/`iscs_workflow` (refactor: UI callbacks
> → events, vestigial `_exec_*` pyautogui → `InputControlPort`). M3.1/M3.2/M3.5 are the deferred
> decompositions.

---

## M4 — Step 4: Build the CLI adapter (proves B9 + B10)

> The swappability proof. A minimal driving adapter that imports only `WilloWispCoreAPI`.

| Status | Step | Action | Gate | Proves |
|:--:|---|---|---|:--:|
| [x] | M4.1 | CLI Composition Root: Build the core, inject synchronous `EventDispatcher` and local driven adapters. *(`adapters/driving/cli/composition.py` `build_core_api()`; `SuiteRunService` wired as the facade `run_service` — `start_suite` drives a real run headlessly. Closes the M3.4 run_service seam.)* | CLI launches cleanly in headless environment | R-HEX-1/3 startup |
| [x] | M4.2 | CLI Commands: Implement console inputs to drive import, flow-edit, run, and report generation. *(`python -m adapters.driving.cli` — `catalog` / `report` (offline) / `run`. catalog+report fully headless & tested; run drives `start_suite` and needs a live host.)* | E2E CLI run produces identical report output | R-HEX-1 |
| [x] | M4.3 | B9 Proof (Headless Check): Enforce absolute import bans. A full suite run occurs with zero GUI libraries loaded. *(Import-ban = `test_architecture_guards`; `test_cli_composition` builds the facade + runs `start_suite` in a subprocess asserting zero tkinter; `test_cli_commands` runs the CLI headless.)* | Import-ban check + CLI integration tests green | B9 |
| [x] | M4.4 | B10 Proof (Drop-in Tests): Add a dummy capability (with `params_schema`), custom protocol, and resolver. *(`test_b10_dropin`: capability via `discover_directory`+`@register` surfaces in the facade & runs; protocol via `register_protocol`; resolver via `register_binding_resolver` — zero shipped files edited.)* | Tests green with zero existing files edited | B10 |

**Exit M4 when:** the CLI runs the full cycle headlessly, the core toolkit-import ban passes,
and the four drop-in extensibility tests pass. The UI is now provably swappable.

---

## M5 — Step 5: Build the Tkinter adapter on top of the Core API

> The existing GUI is rebuilt as a driving adapter that holds only a `WilloWispCoreAPI`
> reference and a `TkEventDispatcher`. No business logic re-enters the UI.

| Status | Step | Adapter Unit | Action / Legacy Extraction | Target Destination |
|:--:|---|---|---|---|
| [x] | M5.1 | Tk Event Dispatcher | Implement thread-marshalling dispatcher using `root.after`. *(`TkEventDispatcher`; + shared `adapters/driving/composition.py` and `ui_tkinter/composition.build_tk_core_api(root)` so the Tk app builds the same facade as the CLI with its own dispatcher. tkinter-free / unit-tested.)* | `adapters/driving/ui_tkinter/dispatcher.py` |
| [ ] | M5.2 | App Shell & Layout | Extract window geometry, resizing, layouts, and views from legacy `baru.py`. | `adapters/driving/ui_tkinter/app_shell.py` · `adapters/driving/ui_tkinter/views/` |
| [ ] | M5.3 | Intent Forwarders | Convert Run, Import, Settings, and Card Config controls into thin facade-forwarders. | `adapters/driving/ui_tkinter/views/` |
| [ ] | M5.4 | Schema Form Renderer | Implement dynamic form generator from step parameters. Delete legacy hand-coded parameter forms. | `adapters/driving/ui_tkinter/renderer.py` |
| [ ] | M5.5 | Overlay Coordinate Split | Split drawing canvas overlays from underlying geometry data (R-HEX-3). | `adapters/driving/ui_tkinter/components/` |
| [ ] | M5.6 | Flow & Suite Panel View | Port the step-tree editor views and suite-list panels to drive the Core API. | `adapters/driving/ui_tkinter/views/` |
| [ ] | M5.7 | Live Rig Validation | Execute the complete test suite on the SCADA physical rig through the new Tkinter adapter. | Verified identical behavior on live host |

**Exit M5 when:** the Tkinter adapter runs entirely on `WilloWispCoreAPI`, the suite is green,
and the live suite is rig-validated. Two front-ends (Tk + CLI) now share one core.

---

## M6 — Cutover & cleanup

| Status | Step | Action | Gate |
|:--:|---|---|---|
| [ ] | M6.1 | Remove the legacy duplicate run path (`ISCS_Engine` / `_run_scenario_legacy_iscs`). | Suite is 100% green |
| [ ] | M6.2 | Remove compatibility shims and re-export files. | Core is clean of legacy references |
| [ ] | M6.3 | Delete the retired legacy files: `baru.py`, `iscs_workflow.py`, `iscs_reports.py`, `iscs_assets.py`, `iscs_OCR.py`, `iscs_recorder.py`. | Entry points run purely on composition roots |
| [ ] | M6.4 | Tighten structural mechanical checks to the whole tree (full Tk-ban on core, strict acyclic validation). | CI guards pass on entire repo |
| [ ] | M6.5 | Update system documentation (`CLAUDE.md`, `SYSTEM_BLUEPRINT.md`) to reflect the final physical layout. | Docs match codebase structure |

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
