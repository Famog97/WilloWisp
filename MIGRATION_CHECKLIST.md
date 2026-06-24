# WilloWisp Modernization — Migration Checklist

Task-by-task breakdown of the Strangler-Fig migration in
[`ARCHITECTURE_DESIGN.md`](ARCHITECTURE_DESIGN.md) §6. Each phase is shippable and
reversible. **Phases 1–6 (the abstraction) are GATED** on Phase 0 completion and the
agreed trigger (regression tests exist / `_exec_*` duplication becomes painful) — see
the deferral decision. Phase 0 is active now.

Legend: `[x]` done · `[~]` in progress · `[ ]` todo · `[gated]` deferred until gate met.

> **`ARCHITECTURE_DESIGN.md` is the full target (north star); THIS file is the status tracker;
> `LIVE_VALIDATION.md` is only the run-required subset.** We built the foundation + proved the
> pattern end-to-end live, but intentionally did NOT mechanically complete every phase.

## Remaining work (what's NOT done yet, and why)

**Done & validated:** registry dispatch · plugin discovery + supersession (DELAY) · event-driven
report + recorder · schema versioning (flows + assets) · report templates (Management/Audit) ·
core infra (registry / EventBus / DI container / discovery).

**Not done — deferred (low value / awkward fit):**
- P2.1 DI wiring into live construction — verifier/runner are per-card with runtime args; protocols
  already a registry. Container exists + tested; wiring adds indirection for little gain.

**Not done — need-driven (do when you next touch that code):**
- ~~P3.4 formalize `BindingResolver` for TEXT/IMAGE/HYBRID~~ — **DONE** (TEXT/IMAGE/HYBRID are now
  registered `BindingResolver` strategies in `iscs_assets`; `BindingExecutor` dispatches by key, no
  if/elif. A new kind = register a resolver, no executor edit. Self-contained — no `iscs_core` dep.
  10 tests; behavior-neutral, offline-validated).
- Port `trigger_alarm` / `reset_alarm` to plugins — **intentionally deferred** (protocol + sampler
  timing critical; the 2 of 19 step types still on legacy adapters).
- ~~P3.1 port actions~~ / ~~P3.2 decompose `ISCSVerifier`~~ — **DONE** (17/19 step types are plugins;
  all 7 verifications + all input/nav/screenshot actions; OCR/colour logic untouched in ISCSVerifier).

**Not done — run-required (need the app at the SCADA rig to verify):**
- P4.2 `auto_register` via `is_applicable` (low value). Phase 5(rest): UI template picker · Engineering
  template · PDF/JSON renderers · widget split (P5.1). (P4.1 palette = DONE, live palette unchanged.)

**Not done — cleanup, only after the above:**
- P6.2 optional-dependency manifest · P6.3 remove legacy dispatch fallback + delete enum members.

**Design patterns still unrealized:** rich `ExecutionContext` facade (currently the `LegacyExecContext`
bridge) · `VerificationBackend` · report *widgets* (have templates, not widgets) ·
`BaseCapability` template-method · `is_applicable` Specification.

---

## Phase 0 — Safety net (ACTIVE)
Goal: regression coverage of current behavior so later phases can prove equivalence.

- [x] **P0.1** pytest harness + `conftest.py` + confirm modules import without Tkinter
- [x] **P0.2** Characterization tests: `ReportManager.normalize_results` (report data contract)
- [x] **P0.3** Characterization tests: Procedure/IOGroup/ProcedureFlow serialization
      - [x] Fix latent bug: `ProcedureFlow.from_dict` crash on unknown top-level step type
- [x] **P0.4** Characterization tests: `AssetManager` CRUD + persistence + ID counters
- [x] **P0.5** Golden-snapshot test: freeze `normalize_results` output for a realistic
      multi-point, multi-loop, rerun raw result set (committed JSON snapshot)
- [x] **P0.6** Tests for `auto_register_procedures` default-flow generation (zones/IO → steps)
- [x] **P0.7** Pure OCR text-match helpers (`_ocr_contains` / `_ocr_canon` / fuzzy) — tested
      directly via `import baru` (imports cleanly, no Tk window); extraction deferred as unneeded
- [x] **P0.8** Coverage gate (`fail_under = 18`, anti-backsliding) + CI note in tests/README.md

## Phase 1 — Contracts & registry (additive) — COMPLETE ✅
- [x] **P1.1** Add `Capability` + `CapabilityRegistry` + `StepResult`/`CapabilityMeta`,
      `EventBus`, `Container` skeletons → new **`iscs_core/`** package (additive, nothing in
      the app imports it yet) + 27 unit tests. (ExecutionContext deferred to P2/P3 wiring.)
- [x] **P1.2** Wrap existing 19 `_exec_*` as `LegacyCapabilityAdapter`, auto-registered by enum-value
      key (`iscs_workflow`). Added single-source `_LEGACY_METHOD_MAP` (drives both runtime dispatch &
      adapter registration), `LegacyExecContext`, guarded `iscs_core` import. Behavior-neutral; 15 tests.
- [x] **P1.3** Route `_execute_procedure` through `core_registry.get(key).execute(ctx)` with fallback
      to the direct legacy method when registry/key is unavailable. StepResult→legacy-tuple conversion
      by status name. 5 tests (routing, fallback, error round-trip).
- [x] **P1.4** Golden tests pass unchanged (behavior identical) — full suite green, `baru` imports OK

## Phase 2 — Centralize wiring & events (in progress)
> ⚠️ **Verification wall:** `SuiteRunner.run()` is a live worker thread (real screen capture + Modbus
> I/O). It cannot be regression-tested offline, so the *removal* of working direct calls and the
> rewiring of live construction are **run-required** steps — deferred until the app can be run on a
> SCADA workstation. Additive event emission (safe) is done now.
- [ ] **P2.1** Introduce `Container`; move scattered `ISCSVerifier(...)`/`ProcedureRunner(...)`/`ProtocolManager(...)` construction behind `resolve()`
      — **DEFERRED (run-required):** routing live per-card construction can't be verified offline.
- [x] **P2.2** Emit lifecycle events from the runner — concrete events + global `bus` in
      `iscs_core.events`; `ProcedureRunner` takes an optional `event_bus` (defaults to global bus) and
      publishes `StepStarted`/`StepCompleted`/`Verification{Passed,Failed}` from `_execute_procedure`.
      Additive, isolated delivery, no behavior change without subscribers. 7 tests.
- [~] **P2.3** Recorder + report as event subscribers — split:
      - [x] **emit** `SuiteStarted`/`CardStarted`/`CardCompleted`/`SuiteCompleted` from `SuiteRunner`
            (additive; existing recorder callbacks + `generate_reports` call left intact). 5 tests.
      - [~] **cutover** drive recorder/report from subscribers:
            - [x] **B2 report** (LIVE-CONFIRMED — one report, correct content): `SuiteCompleted` enriched with
                  results/dir/times/on_log; `ReportManager.on_suite_completed` subscribed at startup
                  (`baru._wire_subscribers`); `SuiteRunner.run()` emits the event instead of calling
                  `generate_reports`. **Safety net:** event carries `report_generated`; if no subscriber
                  handles it, the runner falls back to the direct call (reports never lost). 6 tests.
            - [x] **B3 recorder** (code done, awaiting live confirm): recorder start/stop driven by
                  `CardStarted`/`CardCompleted`. Handler methods on `SuiteRunner` subscribe to its bus
                  for the run (unsubscribed in `finally` — no leak), set `self._active_rec` so per-point
                  overlay updates still work, and set `recorder_handled`. Same fallback-if-unhandled
                  pattern (inline start/stop). 5 tests.

## Phase 3 — Migrate capabilities out of the engine (one PR each)
> Live loop with the user at the SCADA rig (see LIVE_VALIDATION.md Phase B).
- [~] **B1 / P3.1 (started)** Ported **DELAY** → `plugins/utilities/delay.py` (`@register(override=True)`),
      replicating `_exec_delay` incl. interruptible `_sleep`. Discovery wired at startup
      (`baru._load_plugins()` for `_PLUGIN_CATEGORIES`). At launch the registry's `delay` becomes
      `DelayCapability` (verified). 5 tests + offline startup sim. **Awaiting live confirm:** a flow
      with a Delay step still waits correctly during a real suite.
- [x] **P3.1 (rest)** Ported input + navigation actions → `plugins/actions/` (click, right_click,
      hotkey, type_text, navigate_home/alarm_list/event_list/equipment_page) and **screenshot** →
      `plugins/utilities/`. `actions` added to discovered categories. 11 tests. **trigger_alarm /
      reset_alarm intentionally LEFT legacy** (protocol + sampler-timing critical — port only with
      specific need). Net: **17/19 step types now run from plugins.**
- [~] **P3.2 (started)** Decompose verifications: orchestration moves into a capability, OCR work stays
      in `ISCSVerifier` behind a `VerificationBackend` (FR-13, `iscs_core/backends.py` — structural, no
      change to ISCSVerifier). **verify_alarm_panel** ported → `plugins/verifications/verify_alarm_panel.py`
      (`@register(override=True)`), discovered at startup. 7 tests; supersession verified offline.
      **ALL 7 verifications now ported** to `plugins/verifications/`: alarm_panel (live-confirmed),
      normalize, alarm_list, event_list, equipment_page, alarm_panel_custom, custom. Each delegates to
      the backend; orchestration (skip rules, step re-tags, status) lives in the capability. 20 tests
      across the verify plugins; startup sim shows all 7 superseding their legacy adapters. The
      alarm_panel/normalize ones are live-confirmed; the rest await a live run with those
      zones/nav/custom steps configured.
- [ ] **P3.3** Route protocol handling through `Container` + `ExecutionContext`
- [x] **P3.4** Convert TEXT/IMAGE/HYBRID binding `if/elif` → registered `BindingResolver`s.
      `iscs_assets` now has a `BindingResolver` base + `register/get/list_binding_resolver` registry +
      `Text/Image/HybridBindingResolver`; `BindingExecutor.execute` dispatches by key (no if/elif).
      Self-contained (no `iscs_core` dep). HYBRID composes the registered TEXT+IMAGE resolvers. 10 tests.
- [ ] **P3.5** Delete each enum member + dispatch entry as its capability lands

## Phase 4 — Dynamic UI & auto-discovery
- [x] **P4.1** Add-Step palette is registry-extensible: `_dynamic_catalogue()` = curated `_STEP_CATALOGUE`
      + registry caps with `meta.addable=True` (enum-backed). Param editor already renders arbitrary
      params via `_rebuild_params` fallback. 6 tests. Since **P6.3** the palette accepts arbitrary
      (non-enum) addable plugin keys — the `example_action` plugin (`addable=True`) now appears.
- [ ] **P4.2** Rebuild `auto_register_procedures` to query `is_applicable` — low value (auto_register
      works + is tested); Specification pattern only. Deferred / need-driven.
- [x] **P4.4 (UX) Visual step palette** (live-confirmed; refined) — a "＋ Quick add" toolbar row in the
      Flow Editor. Palette shows **simple steps only** (category action/utility: Click, Right Click,
      Hotkey, Type Text, Delay, Screenshot); **verifications stay in the "+ Add" dropdown** (they need
      configuration). `ProcedureFlowDialog._quick_add` drops the step into the selected IO folder/flow.
      Demo `example_action` set `addable=False` (hidden from UI; file kept as reference so saved test
      flows still run). **Click/Right Click from the palette open the coordinate picker immediately**
      (`_pick_point`) so you grab x/y in one gesture; "Type Text" renamed to **"Text"** in the UI.
- [x] **P4.5 (UX) Type Text "click first" toggle** (code done, awaiting live confirm) — Type Text just
      types by default; an opt-in "Click a field first" checkbox (default OFF) enables the x,y click and
      greys the coord fields when off. Added bool-param (checkbox) support to the step editor. 3 tests.
- [~] **P4.3** Plugin discovery — **infra DONE:** `iscs_core.discovery` (`discover_directory` /
      `discover_package` / `discover_entry_points`) + ambient `using_registry`; `plugins/` NFR-12
      layout + README + working reference example (`plugins/actions/example_action.py`,
      auto-superseding by key). 8 tests. **Startup wiring DONE** in B1: `baru._load_plugins()` runs
      discovery for ported categories (`_PLUGIN_CATEGORIES`) at launch.

## Phase 5 — Reporting layers (started — additive, offline-safe)
> Built as an ADDITIVE layer (`iscs_report_templates.py`) that renders from the SAME
> normalized results. The legacy `Suite_Report.html`/Excel path is untouched (still live-validated).
- [x] **P5 templates** Pluggable template registry (`TEMPLATES`) + 2 audience templates rendered from
      `normalize_results`: **Management Summary** (KPIs, failures-by-category) and **Audit Record**
      (immutable per-attempt log). `render_html` / `generate_template_report` / CLI to render any saved
      results offline. HTML-escaped. 7 tests (from the golden fixture). Samples in `samples/`.
- [x] **P5 data artifact** `ReportManager.generate_reports` now also writes `suite_results.json`
      (raw results) so any template can be re-rendered later with no re-run (FR-30e).
- [x] **P5 templates (audience set complete)** Added **Engineering** (full per-point step traces) and
      a **JSON** data export (FR-30f) → templates: management / engineering / audit / json. 9 tests;
      samples in `samples/`. CLI: `--template engineering|json`.
- [x] **P5 UI picker** (code done, awaiting live confirm) — 📊 button in the Suite panel opens a dialog
      to generate any template (Management/Engineering/Audit/JSON) from the last run's
      `suite_results.json` (or a chosen file) and opens it. `SuitePanel._open_report_picker`.
- [x] **P5 PDF renderer** — `render_pdf` (via `fpdf2`, a binary `write` template) added as a 5th picker
      option "Summary PDF". Requires `pip install fpdf2`; without it the picker shows a clear install
      message. 3 tests (registration always; generation skips if fpdf2 absent).
- [ ] **P5 (optional)** full split of legacy HTML into composable widgets (P5.1).

## Phase 6 — Versioning & hardening (started)
- [x] **P6.1** `schema_version` on persisted **flows** + chained migration mechanism in
      `iscs_workflow` (`FLOW_SCHEMA_VERSION`, `register_flow_migrator`, `_migrate_flow_dict`).
      Missing version = current (legacy data loads); future version rejected with a clear error.
      Pure-data, no runtime-path change. 7 tests.
- [x] **P6.1b** Same scheme for the **asset store** (`iscs_assets.json`): `ASSETS_SCHEMA_VERSION`,
      `register_asset_migrator`, `_migrate_assets_dict`; `save()` tags the file, `_load()` migrates
      first and degrades gracefully (logs, starts empty) on a too-new file. Self-contained (no
      iscs_core dep — keeps the asset store standalone). 6 tests.
- [ ] **P6.2** Generalize optional-dependency handling into the registry load manifest
- [x] **P6.3 (decoupling done)** Procedure no longer bound to the `ProcedureType` enum: unknown/plugin
      keys resolve to `_DynamicProcType` (quacks like an enum member — `.value`/`.name`, value
      equality) so they round-trip + execute via the registry. `from_dict` KEEPS unknown keys (was:
      dropped), `_on_add` + `_dynamic_catalogue` accept arbitrary keys. Demo: `example_noop` (non-enum)
      adds → saves → loads → runs via `ExampleNoOpAction`. 9 tests. **Not done (and not desirable yet):**
      deleting the enum / removing the legacy fallback — trigger_alarm/reset_alarm still use it.

---

### Progress — migration functionally COMPLETE

| Phase | Status |
|---|---|
| **0 — Safety net** | ✅ pytest harness (8/8), golden fixtures, coverage gate live |
| **1 — Registry & contracts** | ✅ capability registry is the live dispatch path (legacy adapters + fallback) |
| **2 — Wiring & events** | ✅ lifecycle events (runner + suite); report + recorder are event subscribers. *P2.1 DI live-wiring deferred — low value.* |
| **3 — Capabilities out of the engine** | ✅ **17/19 step types run from plugins** — all 7 verifications (capability + `VerificationBackend`) + all input/nav/screenshot actions; **P3.4 `BindingResolver` done** (TEXT/IMAGE/HYBRID registered, no if/elif). *trigger_alarm/reset_alarm intentionally legacy (protocol-critical).* |
| **4 — Dynamic UI & discovery** | ✅ registry-extensible Add-Step palette (P4.1) + plugin discovery/startup (P4.3). *P4.2 is_applicable deferred — low value.* |
| **5 — Reporting layers** | ✅ templates (Management/Engineering/Audit/JSON/**PDF**) + raw-results persisted + 📊 UI picker. *PDF needs `pip install fpdf2`. Widget split (P5.1) optional.* |
| **6 — Versioning & hardening** | ✅ schema versioning (flows + assets, P6.1/b) + enum decoupling (P6.3 — arbitrary plugin step keys add/save/load/run). *P6.2 optional-dep manifest todo.* |

**Total: 217 tests passing** (1 skipped — PDF, needs fpdf2), coverage ~37% (gate 18). Repo: `C:\Repo-Gitlab\willowisp`, branch `2-new-update-on-modules`.

### Live-validated at the SCADA rig
- ✅ **Core path re-validated after the 2026-06-23 repair**: trigger → verify → reset → consolidated report.
- ✅ Confirmed: DELAY plugin · report-as-subscriber · recorder-as-subscriber · alarm-panel/normalize/
  **list/event/equipment/custom verifications** · P6.3 arbitrary-step (`example_noop`) · **📊 report UI picker**.
- ⏳ Not yet separately exercised: nav actions (run a flow that navigates).

### Remaining (all OPTIONAL / need-driven — nothing on the critical path)
report widget split (P5.1) · P4.2 `is_applicable` · P6.2 optional-dep manifest · P2.1 DI live-wiring
· port trigger_alarm/reset_alarm (deferred, protocol-critical).

> ⚠️ **2026-06-23 repair note:** accidental edits deleted `iscs_core/container.py` (was untracked) and reverted
> the capability bridge / event wiring in `iscs_workflow.py` + `baru.py`. All restored; 204 tests pass; core
> path re-validated live. **`iscs_core/container.py` must be committed** so it can't be lost again.
