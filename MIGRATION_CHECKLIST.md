# WilloWisp Modernization — Migration Checklist

Task-by-task breakdown of the Strangler-Fig migration in
[`ARCHITECTURE_DESIGN.md`](ARCHITECTURE_DESIGN.md) §6. Each phase is shippable and
reversible. **Phases 1–6 (the abstraction) are GATED** on Phase 0 completion and the
agreed trigger (regression tests exist / `_exec_*` duplication becomes painful) — see
the deferral decision. Phase 0 is active now.

Legend: `[x]` done · `[~]` in progress · `[ ]` todo · `[gated]` deferred until gate met.

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
      - [ ] **cutover** remove the direct recorder/report calls and drive them purely from subscribers
            — **DEFERRED (run-required):** a wrong payload/wiring could silently stop reports/recording,
            and no offline test would catch it. Do under live-run validation.

## Phase 3 — Migrate capabilities out of the engine (one PR each) [gated]
- [ ] **P3.1** Port action `_exec_*` → standalone Capability classes under `plugins/actions/`
- [ ] **P3.2** Decompose `ISCSVerifier`; each verification owns its logic + a `VerificationBackend`
- [ ] **P3.3** Route protocol handling through `Container` + `ExecutionContext`
- [ ] **P3.4** Convert TEXT/IMAGE/HYBRID binding `if/elif` → registered `BindingResolver`s
- [ ] **P3.5** Delete each enum member + dispatch entry as its capability lands

## Phase 4 — Dynamic UI & auto-discovery [gated]
- [ ] **P4.1** Drive `AddStepDialog`/`ProcedureFlowDialog` palette + param editors from registry metadata
- [ ] **P4.2** Rebuild `auto_register_procedures` to query `is_applicable`
- [ ] **P4.3** Enable `plugins/` auto-discovery + entry points; NFR-12 directory layout + README templates

## Phase 5 — Reporting layers [gated]
- [ ] **P5.1** Split `iscs_reports.py` into `ResultView` / widgets / templates / renderers
- [ ] **P5.2** Ship Legacy template; prove it reproduces Phase-0 golden output
- [ ] **P5.3** Add Engineering / Management / Audit templates + PDF/JSON renderers

## Phase 6 — Versioning & hardening [gated]
- [ ] **P6.1** Add `schema_version` to persisted artifacts + Chain-of-Responsibility upgraders
- [ ] **P6.2** Generalize optional-dependency handling into the registry load manifest
- [ ] **P6.3** Remove legacy dispatch fallback once the enum is empty; publish contract version

---

### Progress
- Phase 0: **8 / 8** ✅ · coverage gate live
- Phase 1: **4 / 4** ✅ — registry is the live execution path (legacy adapters + fallback)
- Phase 2: **events fully emitted** (runner + suite levels). Cutover to subscribers (P2.3b) and DI
  wiring (P2.1) DEFERRED as run-required — can't verify offline.
- Total: **112 tests passing**, coverage 28.7% (gate 18)
- Repo: `C:\Repo-Gitlab\willowisp`, branch `1-willowisp-first-issue` (changes uncommitted/staged)
- Phases 3–6: gated
