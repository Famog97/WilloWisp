# WilloWisp — Migration Readiness Audit

**Role:** Principal Engineer (final architecture review before migration approval)
**Inputs:** [`RESTRUCTURE_PLANNING.md`](RESTRUCTURE_PLANNING.md) (complete),
[`RESTRUCTURE_DESIGN.md`](RESTRUCTURE_DESIGN.md) (complete). **Migration: not started.**
**Date:** 2026-06-25 · **Status:** Review

> Goal: decide whether the design is **specific enough to migrate safely**. This is a
> gate review — not a redesign, not migration steps, not code. It maps every
> significant method of each S1 class to a destination, validates god-method
> decompositions, scores future-aggregation risk, lists ambiguities/blockers, and
> issues a readiness verdict.

Legend — Risk: **L/M/H**. Mapping status: **✓ clear · ⚠ ambiguous · ✗ orphan (no owner)**.

---

## Part 1 — Ownership Mapping (S1 classes)

Method sizes are measured (AST). Trivial getters/pass-throughs (≤2 lines) are folded
into their obvious owner and omitted. **Orphans/ambiguities are called out explicitly.**

### 1.1 `ISCSVerifier` (12 methods)
| Method | Lines | Responsibility | Target owner | Target class | St |
|---|---:|---|---|---|:--:|
| `verify_alarm_panel` | 256 | poll + colour/blink + datetime + 5 sub-checks + evidence | **spans many** | Coordinator+Policy+perception+evidence | ⚠ |
| `verify_list` | 59 | list OCR + colour + evidence | decision | `ListVerificationPolicy` | ✓ |
| `verify` | 23 | older single-shot severity verify | — | **none identified** | ✗ |
| `_color_present` | 28 | colour within tolerance | perception | `ColorComparator` (+`ColorSampler`) | ✓ |
| `_blink_color_present` | 21 | colour↔grey cycling | perception | `BlinkAnalyzer` | ✓ |
| `_get_zone_bbox` | 14 | zone→bbox (+anchor) | perception | `ZoneResolver` | ✓ |
| `_grab_zone` | 12 | grab **and** save a zone | **two owners** | `ScreenCaptureService`+`EvidenceScreenshotWriter` | ⚠ |
| `_get_color_name` | 6 | rgb→severity name | perception | `SeverityColorClassifier` | ✓ |
| `_ocr_image` | 4 | OCR a frame | perception | `OcrReader` | ✓ |
| `_analyze_image`/`_preprocess_for_ocr` | 2/2 | preprocessing | perception | `OcrPreprocessor` | ✓ |
| `__init__` | 9 | hold zones/config/anchor | orchestration | `VerificationCoordinator` | ✓ |
**Findings:** `verify` (23) has **no destination** — likely a legacy/duplicate path
(keep/kill decision needed). `_grab_zone` fuses capture+save (split). `verify_alarm_panel`
maps at the *concern* level but its **internal seams are drawn only in Part 2**.

### 1.2 `ProcedureRunner` (28 methods)
| Method | Lines | Responsibility | Target class | St |
|---|---:|---|---|:--:|
| `_run_point` | 112 | iterate a point's steps (order/enable/depends_on) | `PointExecutor` | ⚠(god) |
| `_execute_procedure` | 89 | resolve+execute+map+events+error-wrap | `StepDispatcher`+`StepLifecycle` | ⚠(god) |
| `run_scenario` | 88 | drive a flow over points | `FlowRunCoordinator` | ⚠(god) |
| `run_standalone` | 44 | drive a flow once | `FlowRunCoordinator` | ✓ |
| `_exec_*` (19 methods) | 5–53 | legacy executors (vestigial) | `LegacyExecutorAdapters` | ✓ |
| `_make_skip_result` | 11 | build a SKIP result | `PointExecutor`? `DependencyGate`? | ⚠ |
| `_emit` | 9 | publish events | event emitter (cross-cutting) | ✓ |
| `_sleep`/`_check_pause` | 6/5 | run-control signals | `RunControl` | ✓ |
| `__init__` | 22 | wire collaborators | `FlowRunCoordinator` | ✓ |
**Findings:** the three largest (`_run_point`, `_execute_procedure`, `run_scenario`) are
**god methods mapped to a class but not yet split into actions** (Part 2). `_make_skip_result`
owner is ambiguous (gate vs executor).

### 1.3 `SuiteRunner` (14 methods)
| Method | Lines | Responsibility | Target class | St |
|---|---:|---|---|:--:|
| `_run_scenario_legacy_iscs` | 232 | parallel legacy run path | **to be removed** | ⚠ |
| `run` | 167 | thread + card/loop/point + handoff | `SuiteExecutionThread`+`SuiteScheduler`+`PointRunCoordinator` | ⚠(god) |
| `_run_scenario` | 160 | overlapping run path | collapse into the above | ⚠ |
| `_take_screenshot` | 30 | capture + path | `ScreenCaptureService`+`EvidencePathManager` | ⚠ |
| `_collect_failed_point_ids` | 17 | failed-point set | `RerunController` | ✓ |
| `_on_event_card_started/completed` | 14/12 | recorder hooks | `RecorderCoordinator` | ✓ |
| `_emit`/`stop`/`_sleep`/pause/resume | 9/7/7/1/1 | run-control/events | `RunControl` | ✓ |
| `__init__` | 21 | wire | `SuiteExecutionThread` | ✓ |
**Findings:** **three overlapping run methods** (232+167+160) must be proven
behaviour-equivalent before collapse — unproven today. `_take_screenshot` capture must
share one capture service with verification (injection undefined).

### 1.4 `App` (53 methods) — abridged to significant; orphans flagged
| Method(s) | Lines | Target class | St |
|---|---:|---|:--:|
| `_build_ui` | 136 | `AppShell` (builds *all* views → see ambiguity) | ⚠ |
| `_settings_dialog` | 124 | **none — no settings/config owner in design** | ✗ |
| `_excel_file_loaded`/`_load_excel`/`_excel_load_failed`/`_load_profile_from_metadata`/`_open_metadata_browser` | 116/29/3/13/15 | `ImportController` | ✓ |
| `_draw_minimap`/`_capture_monitor_thumbnail`/`_refresh_monitors`/`_on_screen_selected`/`_find_monitor_by_info` | 42/17/8/12/2 | `MonitorController` (+`StatsView` for minimap) | ⚠ |
| `_open_overlay`/`_overlay_done`/`_load_zones`/`_save_zones`/`_update_overlay_btn` | 14/14/15/14/8 | `ZoneController` | ✓ |
| `_set_mode`/`_on_mode_change`/`_update_mode_buttons` | 7/22/23 | `ModeController` | ✓ |
| `_run_test`/`_stop_test`/`_test_finished`/`set_execution_state`/`_toggle_pause`/`_toggle_suite`/`_cb_*`/`_on_auto_paused` | 50/9/13/45/14/12/2–18/5 | `RunController` | ⚠ |
| `_register_hotkeys`/`_unregister_hotkeys`/`_hk_*` | 8/5/1–5 | `HotkeyController` | ✓ |
| `_update_stats`/`_refresh_stats_only`/`_update_overlay_btn` | 19/6/8 | `StatsView` | ✓ |
| `_build_help_content`/`_init_help_panel`/`_open_ocr_monitor`/`_open_preview`/`_close_preview`/`_toggle_preview` | 55/6/8/4/4/3 | `DiagnosticsController` | ✓ |
| `_log` | 7 | `LogSink` | ✓ |
| `_notify_profile_listeners` | 10 | `ProfileEventHub` | ✓ |
| `__init__`/`destroy`/`_set_taskbar_icon`/`_shake_window`/`_on_resize` | 61/8/12/10/6 | `AppShell`/`AppCompositionRoot` | ⚠ |
| `_sync_open_card_config` | 12 | **cross-controller — unclear** | ✗ |
| `_clear_workspace` | 12 | **reset across many owners — unclear** | ✗ |
**Findings (4 orphans/ambiguities):** `_settings_dialog` (124) has **no owner** (the design
omits a settings/config-editing concern); `_sync_open_card_config` and `_clear_workspace`
are cross-controller with no single owner; `set_execution_state` (45) mutates widgets across
several views → spans `AppShell`+`RunController`. `_build_ui`/`__init__` blur `AppShell`
(layout) vs `AppCompositionRoot` (wiring).

### 1.5 `AssetManager` (35 methods)
| Method group | Target class | St |
|---|---|:--:|
| text create/update/delete/get/list | `TextAssetRepository` | ✓ |
| image create/update/delete/get/list | `ImageAssetRepository` | ✓ |
| `create_image_asset`/`_from_bytes` (writes a file) | **+`ImageFileStore`** (metadata+file split) | ⚠ |
| region/template CRUD | `RegionRepository`/`FlowTemplateRepository` | ✓ |
| `_next_id`/`_bump_counter` | `IdSequencer` | ✓ |
| `_load`/`save`/`_json_path`/`_migrate_assets_dict` | `AssetPersistence` | ✓ |
| `get_image_path`/`images_dir` | `ImageFileStore` | ✓ |
| `resolve_binding` | `BindingResolutionService` | ✓ |
| `search` | `AssetSearch` | ✓ |
| `instance`/`reset`/`stats`/`__repr__` | `AssetLibrary` (facade) | ✓ |
**Findings:** cleanest of the six. Only nuance: image creation spans metadata repo + file
store (intended split — confirm).

### 1.6 `ProcedureFlowDialog` (33 methods) — significant + orphans
| Method(s) | Target class | St |
|---|---|:--:|
| `_build`/`_refresh_tree`/`_toggle_collapse_all`/`_on_select`/`_on_tree_click`/`_on_tree_double_click`/`_on_right_click` | `FlowTreeView` | ✓ |
| `_add_step`/`_ins_step`/`_edit_step`/`_duplicate`/`_delete`/`_enable`/`_disable`/`_move_up`/`_move_down`/`_find_step`/`_find_group` | `StepEditController` (on `FlowEditModel`) | ✓ |
| `_quick_add`/`_pick_point` | `QuickAddController` | ✓ |
| `_apply_to_all`/`_delete_from_all`/`_resolve_selected_groups`/`_sel_iids` | `BulkEditController` | ✓ |
| `_load_template`/`_save_template` | `TemplateController` | ✓ |
| `_save_step_as_check_card` | **TemplateController? or asset/gallery — unclear** | ⚠ |
| `_open_assets`/`_open_check_gallery` | **which controller launches these? unclear** | ⚠ |
| `_step_value_summary` | `FlowTreeView`? `FlowEditModel`? | ⚠ |
| `_toast` | `FlowTreeView` (feedback) | ✓ |
**Findings:** core CRUD/bulk/template all map; **3 ambiguities** at the boundary to the
asset/check-gallery subsystem (`_save_step_as_check_card`, `_open_assets`,
`_open_check_gallery`) — a cross-subsystem seam not yet owned.

> **Part 1 verdict:** ~85% of significant methods have a clear owner. **Unresolved: 4
> App orphans, 3 flow-dialog cross-subsystem ambiguities, `ISCSVerifier.verify`
> (keep/kill), `_grab_zone`/`_take_screenshot`/image-create splits, and `_make_skip_result`
> ownership.**

---

## Part 2 — Method Decomposition Validation (god methods from Planning)

For each god method: current size, fused responsibilities, and whether the design draws
its **method-level** decomposition. **This is the weakest area of the current design.**

| God method | Lines | Fused responsibilities | Method-level decomposition in design? |
|---|---:|---|---|
| `_write_html_report` | **1,128** | data-shape + layout + inline CSS + templating + evidence embed | **✗ UNDEFINED** (explicitly deferred, Q-D6) |
| `ISCS_Engine.run` / `SuiteRunner.run` | 318 / 167 | thread + iterate + rerun + evidence + handoff + UI | **✗ UNDEFINED** (classes named; submethods not drawn) |
| `verify_alarm_panel` | 256 | poll + colour/blink + datetime + 5 checks + evidence | **△ PARTIAL** (units named; the *poll loop* + *sub-check sequence* not split into actions) |
| `_run_scenario_legacy_iscs` | 232 | duplicate run path | **✗ UNDEFINED** (slated for removal, not decomposed) |
| `FailureEvidenceCollector.collect` | 220 | gather many artifact types | **✗ UNDEFINED** (collector not decomposed in Design — was S2 method, not in the 9 classes) |
| `normalize_results` | 213 | multi-shape raw→normalized transform | **△ PARTIAL** (a stable contract exists + is tested; per-shape mappers not drawn) |
| `auto_register_procedures` | 205 | zone/nav→11-step derivation | **✗ UNDEFINED** (named as a candidate; rule-per-step split not drawn) |
| `_run_point` | 112 | step iteration | **△ PARTIAL** (`PointExecutor` named; loop body actions not drawn) |
| `_execute_procedure` | 89 | dispatch+lifecycle | **△ PARTIAL** (`StepDispatcher`/`StepLifecycle` named; the boundary line not drawn) |

**Decomposition still undefined (method level):** `_write_html_report`, `run`/`ISCS_Engine.run`,
`_run_scenario_legacy_iscs`, `collect`, `auto_register_procedures`. **Partial:**
`verify_alarm_panel`, `normalize_results`, `_run_point`, `_execute_procedure`.

**Conclusion:** the design decomposed **classes**, not **methods**. Six god methods (≈2,300
lines combined) have **no method-level target** — they cannot be migrated safely as-is.

---

## Part 3 — Future God-Class Risk

Proposed classes whose name/role invites re-aggregation. Risk = likelihood it becomes a
new dumping ground.

| Proposed class | Owns (intended) | Must NOT own | Risk | Recommendation |
|---|---|---|:--:|---|
| `RunController` (App) | start/stop/pause intent + execution-state view sync | run scheduling, step logic, recording, reporting | **H** | Already attracts `set_execution_state`(45)+8 callbacks. Cap responsibilities; split "execution-state view sync" out. |
| `VerificationCoordinator` | sequence perception→policy→evidence | OCR/colour/blink/datetime/decision/evidence | **M** | Enforce "calls but never computes." Add a no-perception-logic test. |
| `FlowRunCoordinator` | run-entry (scenario/standalone) | iteration, dispatch, scheduling | **M** | Keep entry-only; iteration lives in `PointExecutor`. |
| `SuiteScheduler` | card×loop×point planning | execution, rerun decisions | **M** | Planning ≠ running; rerun stays in `RerunController`. |
| `AppCompositionRoot` | construct + inject subsystems | any behaviour | **M** | Wiring grows with the app; acceptable if it has *zero* logic. |
| `AssetLibrary` (facade) | compose repos | storage, ids, files, resolution | **M** | Facades accrete; forbid any CRUD/IO in the facade itself. |
| `DiagnosticsController` (App) | help + OCR-monitor + preview | run/import/zones | **M** | Grab-bag risk; acceptable but watch growth. |
| `BindingResolutionService` | resolve a binding | asset CRUD, OCR/template internals | **L** | Scoped; low risk. |
| `ScreenCaptureService`/`OcrReader`/`ColorSampler` | one perception primitive each | decision/evidence | **L** | Naturally small. |
| `PointExecutor` | iterate one point | step internals, suite loop | **M** | The old `_run_point` was 112 lines; keep the loop thin, push work to dispatch/gate. |

**Highest concern: `RunController`** (H) — run/execution-state is intrinsically complex and
already shows aggregation symptoms. Four `*Coordinator`/`*Service`/facade classes are **M**
and need an explicit "must-not-own" guardrail in the Design before migration.

**Effect of the Hexagonal boundary on aggregation risk.** Enforcing a single inbound
`WilloWispCoreAPI` gate and the Core-Service / UI-Adapter reclassification **structurally
caps** the worst offenders: `App` cannot re-accrete because UI adapters may hold *only* a
facade reference (no engines, repos, or sibling controllers), and `RunController` collapses to
a dumb intent-forwarder (start/stop/pause → facade), removing its execution-state and
widget-mutation responsibilities by construction. A toolkit-import ban in the core (B9 below)
makes "logic leaking into the UI" a mechanically detectable violation rather than a review
judgement. Net: the boundary converts several **M/H** aggregation risks from "watch it" to
"prevented by contract."

---

## Part 4 — Migration Ambiguities & Blockers

### Ownership ambiguities
- `App._settings_dialog`, `_sync_open_card_config`, `_clear_workspace` — no owner.
- `ISCSVerifier.verify` — keep/kill undecided (possible dead/duplicate path).
- `ProcedureRunner._make_skip_result` — gate vs executor.
- Flow-dialog ↔ asset/check-gallery seam (`_save_step_as_check_card`, `_open_assets`,
  `_open_check_gallery`).

### Dependency ambiguities
- **Shared perception/evidence**: `ScreenCaptureService` and `EvidencePathManager` are used
  by *both* the run subsystem and verification. Who constructs and injects them? (Q-D3
  open.)
- **Editor ↔ engine**: the flow dialog mutates flow/model internals today; the new
  `FlowEditModel` ↔ engine contract is unspecified.

### Lifecycle ambiguities
- **Instance scope undefined** for nearly every new unit: singleton vs per-run vs per-step
  (e.g., `AssetLibrary` singleton vs injected — Q-D5; `VerificationCoordinator` per-card vs
  per-point; `FrameSampleCoordinator` per-step).
- **Startup ordering** of side effects (config load, OCR init, protocol registration,
  plugin discovery, legacy-adapter registration) is owned by `AppCompositionRoot` in name
  only — the required order is not captured.

### State-ownership ambiguities
- **`ExecContext` mutation** (`trigger_time`, `trigger_ns`, `sampler`, …) is written by
  capabilities and read by verification/policy. After the split, **who owns this per-point
  mutable state**, and is it passed by reference or via a typed boundary? (Q-D2 open.)
- **Thread affinity** is unspecified: which units must run on the Tk main thread vs the
  worker thread? Critical because the sampler is timing-sensitive and the UI is
  single-threaded.

### Test-net gap
- The highest-risk god methods (`run`, `verify_alarm_panel`, `_write_html_report`,
  `auto_register_procedures`) are **not characterized by tests today**. Migrating them
  without a behavioural net violates the project's own gate (K9/NR4).

### Migration blockers (must resolve before migration begins)
- **B1 — Method-level decomposition undefined** for 6 god methods (~2,300 lines): the HTML
  writer, the run loop(s), the legacy ISCS run path, evidence `collect`, and
  `auto_register_procedures`. (Part 2)
- **B2 — Duplicate run-path equivalence unproven** (`run` / `_run_scenario` /
  `_run_scenario_legacy_iscs` / `ISCS_Engine.run`): cannot collapse safely until proven
  equivalent. (Planning K7)
- **B3 — Orphan/ambiguous methods** with no single owner (4 in `App`, 3 in the flow dialog,
  `verify`, `_make_skip_result`, the capture/save splits).
- **B4 — Shared-service & state ownership** undefined: injection of capture/evidence
  services and ownership of `ExecContext` per-point state (Q-D2/Q-D3).
- **B5 — Lifecycle & thread-affinity** of new units unspecified (singleton/per-run/per-step;
  main-thread vs worker), plus startup-ordering capture.
- **B6 — `_write_html_report` (1,128-line S1 method)** has no decomposition target; it is a
  method, so it fell outside the class-level Design pass (Q-D6).
- **B7 — No characterization tests** around the worst god methods before they move (the
  required safety net).
- **B8 — "Must-not-own" guardrails** not yet stated for the H/M risk classes in Part 3
  (esp. `RunController`).
- **B9 — Strict UI boundary decoupling (Hexagonal).** No core unit may import a UI/OS
  framework (`tkinter`, `pyautogui` window/native hooks, `keyboard`, canvas/widget types) or
  call a toolkit threading API (`root.after`, Qt signals). All UI access must go through the
  single `WilloWispCoreAPI` gate; all worker→UI events through the abstract `EventDispatcher`;
  all native capabilities (screen capture, input, hotkeys) through **driven ports** bound per
  environment. **Verification:** a mechanical import check (core packages must not import any
  UI/OS-automation module) **and** a passing **headless CLI** drive of author→run→report with
  no GUI toolkit loaded.

---

## Part 5 — Migration Approval

**Migration Readiness Score: 72 / 100.**

Rationale: the **class-level** ownership design is sound, well-grounded in measured method
inventories, traces cleanly to Planning, and maps ~85% of significant methods. It is held
back from approval by **method-level** under-specification (B1/B6), an unproven duplicate
run-path (B2), a cluster of orphan/ambiguous methods (B3), and undefined
state/lifecycle/thread ownership (B4/B5) — all of which are *correctness-sensitive* on the
untestable live path.

**Status: APPROVED WITH CONDITIONS.** The architecture is approved; migration may **not**
begin until the blockers below are closed (most via a focused Design addendum, not a
redesign).

**Conditions to clear before migration starts:**
1. **B1/B6** — draw the method-level decomposition for the 6 undefined god methods
   (submethod trees), including a target for `_write_html_report`.
2. **B2** — prove (or document the differences of) the overlapping run paths before any
   collapse; decide the canonical path.
3. **B3** — assign owners for every orphan/ambiguous method (settings, workspace reset,
   card-config sync, `verify` keep/kill, capture/save splits, asset-gallery seam).
4. **B4** — specify injection of shared capture/evidence services and ownership/passing of
   `ExecContext` per-point state.
5. **B5** — specify instance lifetime and thread affinity for each new unit, and capture the
   required startup ordering.
6. **B7** — add characterization/snapshot tests around `run`, `verify_alarm_panel`,
   `_write_html_report`, and `auto_register_procedures` *before* they move.
7. **B8** — add explicit "must-not-own" guardrails for the Part 3 H/M classes
   (especially `RunController`).
8. **B9** — establish the strict Hexagonal UI boundary: a single `WilloWispCoreAPI` gate, an
   abstract `EventDispatcher`, pure coordinate models, driven ports for native capabilities,
   a core toolkit-import ban, and a headless CLI drive as proof.

Once 1–8 are resolved, re-audit is expected to reach an approvable score (≥ ~85) and the
Migration phase can be authored.

> **Note (post-audit):** Design **v3** (`RESTRUCTURE_DESIGN.md`) was revised to address
> B1–B9 — including the Hexagonal boundary (§1.0–1.2), the App core/adapter split (§5), and
> the geometry-vs-canvas split (§8). A re-audit against v3 is the next gate.

> No implementation, migration steps, or redesign produced — this audit only determines
> readiness.
