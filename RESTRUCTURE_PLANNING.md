# WilloWisp Layered Decomposition — Planning

**Initiative:** break up the god-modules into a layered package.
**Phase:** 1 of 3 — **Planning** (this doc). Design and Migration follow, each gated
on sign-off of the previous.
**Status:** Draft for review · **Date:** 2026-06-25

> This is the **requirements/planning** deliverable only. It defines *why*, *what
> must be true*, *what's in and out of scope*, *risks*, *acceptance gates*, and the
> *open questions to resolve before design*. It does **not** specify the target
> module layout in detail, the class-by-class mapping, or the migration steps —
> those are the Design and Migration phases.
>
> Realizes **NFR-3** and retires **Risk R2 (god objects)** from
> [`ARCHITECTURE_DESIGN.md`](ARCHITECTURE_DESIGN.md). The plugin/registry migration
> (see [`MIGRATION_CHECKLIST.md`](MIGRATION_CHECKLIST.md)) is complete and is the
> foundation this builds on.

---

## 1. Context & motivation

The plugin/registry modernization fixed *how behavior is dispatched and
constructed*. It did **not** fix the *file geography*: two modules still
concentrate unrelated responsibilities.

- `baru.py` — **~7,660 lines**, ~30 classes: the Tk UI **and** the verifier
  (`ISCSVerifier`), protocol layer (`ProtocolManager`/`ModbusProtocol`), the suite
  runner (`SuiteRunner`/`ISCS_Engine`/`ClickEngine`), the SQLite metadata store,
  domain models (`Scenario`/`Zone`/`Monitor`), evidence collection, and ~20 dialogs/
  overlays — all in one file.
- `iscs_workflow.py` — **~4,860 lines**: the flow **data model**
  (`Procedure`/`IOGroup`/`ProcedureFlow`), the **engine** (`ProcedureRunner`), the
  capability bridge, `auto_register_procedures`, **and** the flow-editor UI dialogs
  (`AddStepDialog`/`ProcedureFlowDialog`).

Consequences: hard to navigate, risky to edit (large blast radius, merge
conflicts), bidirectional UI↔logic coupling (services hold `self.app`-style
back-references), and the core logic can't be imported without dragging in Tk.

**The healthy parts to preserve as-is:** `iscs_core/` (the framework kernel),
`plugins/` (the 19 capabilities), and the already-standalone `iscs_assets.py` /
`iscs_reports.py` / `iscs_report_templates.py` / `iscs_OCR.py` / `iscs_recorder.py`.

---

## 2. Objectives

- **O1** Decompose `baru.py` and `iscs_workflow.py` into a **layered package**
  organized by responsibility (UI · services · domain · protocols · reporting),
  on top of the existing `iscs_core/` kernel and `plugins/`.
- **O2** Establish and **enforce a one-directional dependency graph**
  (UI → services → domain; protocols/reporting/core as leaves), with no cycles.
- **O3** Make **domain and services Tk-free and headless-importable**, so the core
  logic is testable and reusable without a GUI.
- **O4** **Preserve 100% of behavior**, persisted data, the plugin system, report
  output, and the live run path. This is a *move*, not a *rewrite*.
- **O5** Improve maintainability and onboarding: a contributor can find code by
  responsibility, and a single module owns a single concern.
- **O6** Keep the change **incremental and reversible** — never a broken `main`.

---

## 3. Scope

### In scope
- Relocating existing code from the two god-modules into the new package layout.
- Splitting `iscs_workflow.py` into its data-model, engine, and flow-editor-UI parts.
- Giving clear homes to: the asset/binding system, the SQLite metadata store, the
  protocol layer, reporting, OCR/evidence/verifier services.
- **Breaking UI↔service back-references** by routing through the existing `EventBus`
  (and/or small interfaces), so services no longer hold UI handles.
- Updating import paths in `plugins/` and `iscs_core/` consumers (without changing
  their public APIs).
- Compatibility **shims/re-exports** during transition; packaging + single entry
  point; updating `CLAUDE.md` / `SYSTEM_BLUEPRINT.md` module maps as code moves.

### Out of scope (non-goals for this initiative)
- **No new features, no behavior changes, no algorithm changes** (verification,
  Modbus, OCR, reporting all behave identically).
- No UI redesign or visual changes.
- No deletion of the `ProcedureType` enum / legacy `_exec_*` fallback (kept as the
  instrumented safety net — separate, deferred).
- DI-container live-wiring (P2.1) is **not** a goal; adopt it only if it falls out
  naturally — otherwise leave deferred.
- No change to persisted file formats, schema versions, plugin contract, or registry
  keys.
- Performance tuning beyond "no regression."

---

## 4. Current-state facts (the baseline to protect)

- **Tests:** 259 passing (hermetic — no live screen/Modbus/Tk needed), coverage gate
  `fail_under=18`. This suite is the **safety net** for the whole effort.
- **Live path:** `SuiteRunner.run()` needs a real screen + Modbus and **cannot** be
  unit-tested; it is validated manually on the SCADA rig (see
  [`LIVE_VALIDATION.md`](LIVE_VALIDATION.md)).
- **Module-level global state** in `baru.py` to be handled carefully: `APP_CONFIG`,
  `TESSERACT_AVAILABLE`, the `*_AVAILABLE` capability flags, `SEVERITY_MATRIX`, and
  **import-time side effects** (config load, Tesseract init, plugin discovery,
  legacy-adapter registration).
- **Coupling to untangle:** services reach the UI (log callbacks, HUD/overlay
  updates, `stop_event`/`pause_event`), and the flow editor lives inside the engine
  module.
- **Stable public surfaces that must not change:** `ProcedureType` values (== registry
  keys == persisted `proc_type`), the four persisted stores (`config.json`,
  `iscs_assets.json`, `iscs_template.json`, `iscs_metadata.db`), `suite_results.json`,
  the plugin `@register`/`Capability` contract, and report output.

---

## 5. Requirements

### Functional / structural (R)
- **R1 — Behavior preservation.** Identical runtime behavior and identical report/
  persisted output. The golden-fixture and characterization tests must pass
  unchanged at every step.
- **R2 — Layered packages.** Code is organized into layers by responsibility with a
  documented, enforced dependency direction (UI → services → domain; protocols,
  reporting, core as leaves).
- **R3 — Tk-free core.** No module under `domain/` or `services/` imports `tkinter`
  (verifiable). The core is importable and testable headless.
- **R4 — Stable public contracts.** No change to `ProcedureType` keys, persisted
  formats/schema versions, the plugin contract, registry keys, or report structure.
- **R5 — Incremental & reversible.** Each move is a small, independently shippable
  change; old import paths keep working via re-export shims until an explicit
  cutover; `main` is never broken.
- **R6 — Decoupled UI.** Services communicate outward via the `EventBus` (or narrow
  injected interfaces), not via back-references to UI objects.
- **R7 — Single responsibility.** Each new module owns one concern; the two
  god-modules are retired (or reduced to a thin compatibility facade, then removed).
- **R8 — Plugins/core untouched in spirit.** `iscs_core/` and `plugins/` change only
  by import path; discovery, supersession, and the manifest still work at startup.
- **R9 — Clear persistence homes.** Each store (config, assets, template, metadata)
  has exactly one owning module; file/DB I/O is not scattered across services.
- **R10 — Packaging & entry point.** A single documented entry point; test config and
  any packaging metadata updated to the new layout.
- **R11 — Living docs.** `CLAUDE.md` and `SYSTEM_BLUEPRINT.md` module maps are updated
  as modules move, so the docs never describe a stale structure.

### Non-functional / constraints (NR)
- **NR1 — Platform unchanged.** Single-machine Windows desktop, Tkinter.
- **NR2 — Graceful degradation preserved.** Every optional-dependency guard and the
  load manifest keep working; moving code must not change init order in a way that
  breaks degradation.
- **NR3 — Acyclic imports.** The package import graph has no cycles (mechanically
  checkable).
- **NR4 — Test gate.** The full suite stays green after every step; coverage gate
  held or raised; new headless-testable seams should *add* coverage.
- **NR5 — Live re-validation.** After the runner/verifier/protocol move, the live
  suite is re-validated once on the rig before that step is considered done.
- **NR6 — Reviewability.** No step should be an un-reviewable mega-diff; large pure
  moves are isolated from logic changes.

---

## 6. Risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| K1 | **Big-bang refactor** breaks everything at once. | Strangler-style: one module at a time, shims, tests gate each step (R5/NR4). |
| K2 | **Circular imports** from bidirectional UI↔service coupling. | Enforce dependency direction (R2); decouple via `EventBus`/interfaces (R6); add an import-cycle check (NR3). |
| K3 | **Module-global state & import-time side effects** (config, Tesseract init, plugin discovery order) cause subtle init bugs. | Inventory globals first; decide a config/bootstrap home in Design; preserve startup ordering explicitly. |
| K4 | **Tk runtime quirks** (threads, `after()`, overlays, `self.app` refs) when moving `SuiteRunner`/overlays. | Move UI last; keep Tk concerns in `ui/`; services emit events the UI renders. |
| K5 | **Live path can't be unit-tested** → regressions slip past CI. | Mandatory rig re-validation after the runner move (NR5); move pure logic before live wiring. |
| K6 | **Long-lived refactor branch** accrues merge conflicts on the 7.7k file. | Small, frequent, shippable steps; sequence to empty `baru.py` progressively. |
| K7 | **Hidden coupling** discovered mid-move (e.g. a dialog calling into the verifier). | Design phase maps dependencies first; shims absorb surprises without breaking callers. |
| K8 | **Scope creep** into rewrites/features. | Hard non-goals (§3); "move not rewrite" rule (R1); logic changes are separate PRs. |

---

## 7. Success criteria (acceptance gates)

The initiative is **done** when all hold:

1. **Tests green** — full suite passes at completion *and* after each intermediate
   step; coverage gate maintained.
2. **No Tk in the core** — nothing under `domain/`/`services/` imports `tkinter`
   (checked).
3. **Acyclic graph** — the package import graph has no cycles (checked).
4. **God-modules retired** — `baru.py` and `iscs_workflow.py` are gone (or reduced to
   thin, documented compatibility facades scheduled for removal); a single entry
   point launches the app.
5. **Contracts intact** — existing saved scenarios/flows/assets/templates load and run
   unchanged; reports are structurally identical; plugins still discover and run.
6. **Live-validated once** — a real suite (trigger → verify → reset → report) passes
   on the rig after the runner/verifier relocation.
7. **Docs current** — `CLAUDE.md` / `SYSTEM_BLUEPRINT.md` describe the new structure.

---

## 8. Open questions to resolve in Design

These are **decisions to make before/at the Design phase** — not yet decided:

- **Q1 — Package name & module renames.** Adopt a top-level package (e.g. `willo/`)?
  Rename `iscs_core → core` and drop the `iscs_` prefix, or keep names to minimize
  import churn?
- **Q2 — Flow model split.** Exact homes for `Procedure`/`IOGroup`/`ProcedureFlow`
  (domain) vs `ProcedureRunner` (engine service) vs `auto_register_procedures` vs the
  flow-editor dialogs (UI).
- **Q3 — Suite vs step execution.** Keep suite orchestration (`SuiteRunner`) separate
  from per-point step execution (`ProcedureRunner`)? (Recommended — confirm.)
- **Q4 — Storage layer.** Introduce a dedicated `storage/`/`persistence/` layer for the
  JSON + SQLite repositories, or keep each store self-contained with its domain?
- **Q5 — Configuration & globals.** Replace module-level `APP_CONFIG` and the
  `*_AVAILABLE` flags with a config/service object, or keep module globals behind a
  `config` module? How is startup ordering guaranteed?
- **Q6 — UI decoupling depth.** How far to push event-driven decoupling now: full
  services-emit-events, or minimal injected interfaces where back-references exist
  today? (Balance value vs. churn.)
- **Q7 — Shim strategy.** Keep `baru.py`/`iscs_workflow.py` as compatibility facades
  re-exporting from new locations until a final cutover, vs. update all imports per
  move. (Recommended: facades — confirm.)
- **Q8 — Standalone modules.** Move `iscs_assets`/`iscs_reports` into `domain/` /
  `reporting/` while **preserving their no-`iscs_core`-dependency** property?
- **Q9 — Packaging & entry.** `main.py` → `willo.app`; installable via `pyproject`;
  how `python baru.py` continues to work during transition.
- **Q10 — Cycle/Tk-free enforcement.** Which tool/check enforces NR3 (acyclic) and R3
  (no Tk in core) in CI?

---

## 9. Out-of-this-doc (next phases)

- **Design** (Phase 2): the concrete target package layout, module-by-module
  responsibilities and public surfaces, the dependency rules, the event/decoupling
  design, the configuration/bootstrap design, the shim strategy, and the resolution
  of the §8 open questions.
- **Migration** (Phase 3): the ordered, shippable step list (leaves → UI last),
  per-step test/rig gates, and the cutover + facade-removal plan.

**Guiding principle:** *move, don't rewrite; one layer at a time; tests gate every
step; UI and the live path move last.*
