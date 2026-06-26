# WilloWisp — Deep Decomposition Planning Review

**Role:** Principal Software Architect · **Phase:** 1 of 3 — **Planning (assessment only)**
**Date:** 2026-06-25 · **Status:** Draft for review

> **This is a planning exercise.** It determines *whether* deep decomposition is
> needed, *where*, *why*, and *what must be answered before design begins*. It does
> **not** produce a target architecture, folder structure, file names, package
> layout, implementation details, or migration steps. It does not stop at
> module-level — it descends to class and method granularity.
>
> Context: realizes the long-standing **NFR-3** intent and retires **Risk R2 (god
> objects)** noted in [`ARCHITECTURE_DESIGN.md`](ARCHITECTURE_DESIGN.md). The
> plugin/registry modernization is complete and is the stable base this builds on.

Severity scale used throughout: **S1 Critical · S2 High · S3 Moderate · S4 Low.**
Line/method counts are measured from the current tree (AST), not estimated.

---

## Phase 1 — Responsibility Inventory

For each major file: primary / secondary / unrelated / hidden responsibilities, and
a verdict on whether it has become a **responsibility aggregation point** (a place
where unrelated reasons-to-change accumulate).

### The application module (`baru.py`, 7,663 lines, ~30 classes)
- **Primary:** host the desktop GUI (root window, panels, dialogs, overlays).
- **Secondary:** suite orchestration (runs cards × loops × points on a worker
  thread); screen verification (OCR + colour decisioning); the Modbus protocol
  server; evidence collection; domain models (test scenario, screen zone, monitor).
- **Unrelated (to a GUI module):** a SQLite metadata repository for imported IO
  lists; Excel/sheet column-mapping import logic; configuration loading and global
  availability flags; Tesseract initialization.
- **Hidden:** ambient global state (configuration dict, capability-availability
  booleans, the severity colour matrix) and **import-time side effects** (config
  load, OCR init, protocol registration); implicit UI↔logic back-references (worker
  logic writes to the UI log and drives on-screen overlays directly).
- **Verdict:** **Severe aggregation point (S1).** At least six distinct
  reasons-to-change live here (UI, run orchestration, perception/decision, protocol,
  persistence, import). This is the single largest source of architectural debt.

### The workflow module (`iscs_workflow.py`, 4,841 lines)
- **Primary:** the test-flow **data model** (step, per-point group, flow tree) and
  the **execution engine** (sequential step runner honouring order/enable/dependency).
- **Secondary:** default-flow generation (deriving steps from configured zones/nav);
  the capability bridge that lets registered plugins supersede built-in steps; flow
  schema versioning.
- **Unrelated (to an engine):** the **entire flow-editor GUI** (the step-tree editor,
  step-type palette, parameter editors) and several asset/binding authoring dialogs.
- **Hidden:** the engine carries cross-cutting concerns (timing, screenshot, error
  wrapping, event emission) inside one execution method; the data model and the GUI
  that edits it share a module, so they cannot evolve independently.
- **Verdict:** **Severe aggregation point (S1).** Three unrelated concerns (data
  model, execution, authoring GUI) co-located.

### The reporting module (`iscs_reports.py`, 1,635 lines, one class)
- **Primary:** turn raw run results into a normalized model and emit the consolidated
  report (HTML dashboard + Excel) and persist raw results.
- **Secondary:** evidence-file scanning; acting as an event subscriber.
- **Hidden:** **one method carries ~70% of the module** (the HTML writer is 1,128
  lines); presentation, layout, inline styling, data shaping, and string templating
  are fused; the normalization (data) concern and the rendering (presentation)
  concern are not separable as written.
- **Verdict:** **Concentrated debt (S2).** Not a *breadth* aggregation point like the
  two above, but a **depth** one — a god method inside an otherwise focused module.

### The asset/binding module (`iscs_assets.py`, 1,133 lines)
- **Primary:** a reusable store of expected-text / reference-image / region /
  flow-template assets, with persistence and schema versioning; a binding executor
  with pluggable resolvers.
- **Secondary:** the asset store class is large (510 lines / 35 methods) and mixes
  entity CRUD, ID generation, file/image management, search, and persistence.
- **Verdict:** **Mostly cohesive (S3).** The recent resolver split is healthy; the
  store class is the main candidate for internal decomposition.

### The pluggable-templates module (`iscs_report_templates.py`, 482 lines)
- **Primary:** the post-migration reporting layers (data view, self-describing
  widgets, composable templates, format renderers).
- **Verdict:** **Healthy (S4).** Recently built to the target pattern; only the PDF
  renderer (64 lines) is mildly large. Included as the **reference for "good."**

### The perception helper (`iscs_OCR.py`, 170 lines)
- **Primary:** OCR + adaptive image preprocessing.
- **Verdict:** **Healthy (S4),** cohesive and small.

### The recorder (`iscs_recorder.py`, 479 lines)
- **Primary:** per-card video capture with overlay compositing.
- **Verdict:** **Healthy (S4),** focused.

### The framework kernel (`iscs_core/`) and capabilities (`plugins/`)
- **Verdict:** **Healthy (S4).** Single-purpose units (registry, events, container,
  discovery, manifest, backends) and one capability per file. **The model the rest
  should be measured against.** Their *internal* health is not in question; only the
  *import-path* impact of moving their collaborators is.

---

## Phase 2 — Complexity Assessment

Dimensions: size · cyclomatic complexity (proxied by branching/length) · coupling
(inbound/outbound) · cohesion · testability · change-risk.

### 2.1 God modules (ranked)

| Module | Lines | Why it qualifies | Cohesion | Testability | Change-risk | Severity |
|---|---:|---|---|---|---|---|
| `baru.py` | 7,663 | ≥6 unrelated responsibilities + GUI + globals + import side effects | Very low | Very low (Tk + threads + live screen) | Very high (huge blast radius, merge magnet) | **S1** |
| `iscs_workflow.py` | 4,841 | data model + engine + authoring GUI fused | Low | Mixed (data/engine testable; GUI not) | High | **S1** |
| `iscs_reports.py` | 1,635 | one 1,128-line method dominates | Low (within the method) | Low for the writer; the normalizer is tested | High | **S2** |
| `iscs_assets.py` | 1,133 | a 510-line multi-role store class | Medium | Good (already tested) | Medium | **S3** |

### 2.2 God classes (ranked, measured)

| Class | Lines | Methods | Concern(s) it concentrates | Severity |
|---|---:|---:|---|---|
| `App` | 1,136 | 53 | window lifecycle + menus + global wiring + many flows | **S1** |
| `SuitePanel` | 898 | 31 | suite list UI + run/stop control + persistence + report launching | **S2** |
| `ProcedureFlowDialog` | 875 | 33 | flow-tree editing UI + quick-add + param editors | **S2** |
| `ProcedureRunner` | 820 | 28 | per-step execution + all 19 legacy executors + sampler/timing | **S1** |
| `SuiteRunner` | 697 | 14 | suite/card/loop orchestration + rerun + evidence + UI feedback | **S1** |
| `OverlayWindow` | 570 | 32 | zone/region drawing overlay + interaction state | **S2** |
| `SuiteCardConfigDialog` | 531 | 20 | per-card zone + navigation + protocol configuration UI | **S3** |
| `AssetManager` | 510 | 35 | entity CRUD + IDs + image files + search + persistence | **S3** |
| `ISCS_Engine` | 487 | 11 | an alternate live run mode | **S2** |
| `AddStepDialog` | 466 | 10 | step palette + parameter form construction | **S3** |
| `ISCSVerifier` | 450 | 12 | screen capture + OCR orchestration + colour/blink + datetime + pass/fail policy | **S1** |

### 2.3 God methods (ranked, measured) — the deepest debt

| Method (host) | Lines | What it fuses | Severity |
|---|---:|---|---|
| `_write_html_report` (reporting) | **1,128** | data shaping + layout + inline CSS + templating + evidence embedding, in one function | **S1** |
| `SuiteRunner.run` | 318 | thread lifecycle + card/loop/point iteration + rerun + evidence + reporting handoff + UI updates | **S1** |
| `verify_alarm_panel` (verifier) | 256 | poll loop + multi-frame colour/blink + datetime parse + 5 sub-checks + evidence save | **S1** |
| `_run_scenario_legacy_iscs` (engine) | 232 | a second, parallel run path | **S2** |
| `FailureEvidenceCollector.collect` | 220 | evidence gathering across many artifact types | **S2** |
| `normalize_results` (reporting) | 213 | multi-shape raw→normalized transform | **S2** |
| `auto_register_procedures` (workflow) | 205 | the entire default-flow derivation (zone/nav → 11 steps) | **S2** |
| `_run_scenario` / `_build_card` / `_build_ui` | 160 / 146 / 136 | long UI/flow construction methods | **S3** |

**Reading:** the debt is **two-dimensional** — *breadth* (god modules/classes mixing
many concerns) **and** *depth* (god methods that fuse many steps of one concern into
one unreadable, untestable unit). Both must be in scope; fixing only module breadth
would leave 1,000-line methods intact.

---

## Phase 3 — Decomposition Candidates

Candidates are described as **responsibility clusters / seams**, not as target units
(no names, no layout). For each: current responsibility · why decomposition may help
· expected benefits · potential risks · estimated impact.

1. **GUI vs. everything else (the primary seam).**
   *Current:* the application module owns the GUI **and** orchestration, perception,
   protocol, persistence, import. *Why:* these change for unrelated reasons and the
   GUI makes the rest untestable. *Benefits:* headless-testable core, smaller blast
   radius, parallel work. *Risks:* hidden UI↔logic back-references; Tk threading.
   *Impact:* very high (touches the largest module).

2. **Suite orchestration vs. per-point step execution.**
   *Current:* two layers exist but are entangled with UI feedback and rerun policy.
   *Why:* "what to run and how many times" is a different concern from "execute one
   step." *Benefits:* each independently testable; clearer rerun/loop policy.
   *Risks:* shared mutable run-state; live-only behavior. *Impact:* high.

3. **Perception vs. decision inside verification.**
   *Current:* one class/method does screen capture, OCR orchestration, colour/blink
   sampling, timestamp parsing **and** the pass/fail policy. *Why:* perception is
   reusable and mockable; policy is where rules live. *Benefits:* unit-testable
   decisioning with fixture frames; reusable perception. *Risks:* timing-sensitive
   sampling coupling. *Impact:* high (S1 class + S1 method).

4. **The report HTML writer (depth candidate).**
   *Current:* a single 1,128-line method. *Why:* presentation, layout, and data are
   fused and untestable. *Benefits:* snapshot-testable sections; the new
   widget/template model already proves the pattern. *Risks:* must reproduce the
   exact legacy output. *Impact:* high, but well-bounded (one method).

5. **Result normalization vs. report emission.**
   *Current:* data shaping and writing share a module. *Why:* the normalized model is
   the stable contract every renderer binds to. *Benefits:* one tested data contract,
   many renderers. *Risks:* low (normalizer already tested). *Impact:* medium.

6. **Flow data model vs. flow execution vs. flow authoring GUI.**
   *Current:* all three in one module. *Why:* a data structure, an interpreter, and an
   editor are three concerns. *Benefits:* model reusable headless; editor evolves
   independently. *Risks:* the editor reaches into engine internals. *Impact:* high.

7. **Default-flow derivation (a god method).**
   *Current:* one 205-line function encodes the zone/nav→step policy. *Why:* it is
   pure policy, ideal to isolate and test. *Benefits:* testable, explicit rules.
   *Risks:* low. *Impact:* medium.

8. **Protocol layer.**
   *Current:* already a clean registry, but co-located in the GUI module. *Why:*
   transport has nothing to do with the GUI. *Benefits:* trivially separable,
   independently testable with a fake transport. *Risks:* very low. *Impact:* low.

9. **Persistence concerns (config, asset store, template store, metadata DB).**
   *Current:* spread across modules, with file/DB I/O inline. *Why:* I/O is a distinct
   concern from the logic that uses it. *Benefits:* one place to reason about formats,
   versioning, and failure modes. *Risks:* schema-version handling must be preserved.
   *Impact:* medium.

10. **The asset store class (internal depth).**
    *Current:* 510 lines / 35 methods mixing CRUD, IDs, image files, search,
    persistence. *Why:* multiple roles in one class. *Benefits:* smaller, role-focused
    units. *Risks:* low (well tested). *Impact:* medium.

11. **Ambient global state & startup side effects.**
    *Current:* configuration, availability flags, severity matrix, and init-on-import
    behavior live as module globals. *Why:* implicit global state defeats testability
    and creates init-order coupling. *Benefits:* explicit, injectable, deterministic
    startup. *Risks:* easy to introduce ordering bugs while moving. *Impact:* medium,
    but **pervasive** (touches everything).

12. **Duplicate/parallel run paths.**
    *Current:* multiple run methods (`run`, `_run_scenario`, `_run_scenario_legacy_iscs`,
    `run_scenario`) appear to encode overlapping behavior. *Why:* parallel paths drift.
    *Benefits:* one canonical execution path. *Risks:* the paths may differ subtly;
    needs careful equivalence analysis. *Impact:* high (correctness-sensitive).

---

## Phase 4 — Architectural Constraints

Any future decomposition must respect these. Marked **[HARD]** (non-negotiable) or
**[NEG]** (negotiable / can be revisited in design).

- **[HARD] Behavioral equivalence.** Identical runtime behavior and identical
  report/persisted output. This is a *move*, not a redesign.
- **[HARD] Persisted-data compatibility.** Existing saved scenarios, flows, assets,
  templates, the metadata DB, and `suite_results.json` must continue to load and run;
  schema versions and migrators preserved.
- **[HARD] Stable string-key contract.** The step-type keys (embedded in saved flows
  and used as registry keys) must not change.
- **[HARD] Plugin/capability compatibility.** The registration contract, discovery,
  supersession, and the startup load manifest must keep working unchanged.
- **[HARD] Report compatibility.** The normalized result contract and the existing
  HTML/Excel/PDF/JSON outputs remain functionally equivalent.
- **[HARD] Runtime model.** Single-machine Windows desktop GUI; certain work must
  remain on the GUI main thread, other work on worker threads — the threading model
  cannot be casually changed.
- **[HARD] Graceful degradation.** Every optional-dependency guard and the
  availability manifest must keep functioning; init order must not break degradation.
- **[NEG] Naming and the surface a contributor imports.** Internal names and import
  surfaces can change (this is a *design-phase* decision).
- **[NEG] Whether the core can run without a GUI.** Strongly desirable (testability)
  but the *degree* is a design choice.
- **[NEG] Consolidating duplicate run paths.** Desirable, but only if proven
  behavior-equivalent; otherwise treated as a separate, careful effort.
- **[NEG] Performance.** Must not regress; micro-optimization is not a goal.

---

## Phase 5 — Dependency & Coupling Analysis

- **Coupling hotspots.** The application module is the universal hub: the GUI,
  orchestration, perception, protocol, and persistence all reference each other
  through it. The engine module is a second hub (model + execution + editor).
- **Cyclic-dependency risks.** The most likely cycles: GUI ↔ orchestration (worker
  logic writes to the UI and reads UI state), and engine ↔ editor (the editor
  manipulates engine/model internals). These bidirectional references are the primary
  obstacle to any clean separation.
- **Healthy directional dependencies to preserve.** Capabilities depend only on the
  kernel; the standalone reporting and asset modules deliberately avoid depending on
  the kernel. These one-way edges are assets — they must not be inverted.
- **Modules likely to resist decomposition (need special handling):**
  - The application module — pervasive globals and import-time side effects.
  - The suite/engine runners — live-only behavior, shared mutable run-state,
    threading.
  - The verification class — timing-sensitive multi-frame sampling fused with policy.
  - The HTML report writer — exact-output fidelity inside one giant method.
- **Mechanical signals to establish before design:** a measured import graph
  (to confirm/!disprove cycles) and a "what imports the GUI toolkit" map (to size the
  perception/orchestration extraction).

---

## Phase 6 — Planning Risks (likelihood × impact)

| # | Risk | Likelihood | Impact | Notes |
|---|---|---|---|---|
| K1 | **Behavior regression** in the live path (untestable offline). | High | High | Live path runs only on the rig; CI cannot catch it. |
| K2 | **Hidden coupling** surfaces mid-effort (a dialog calling into perception, etc.). | High | Medium | The two hubs hide many cross-references. |
| K3 | **Cyclic imports** when separating GUI from logic. | Medium | High | Bidirectional UI↔logic refs are the root cause. |
| K4 | **Global-state / init-order bugs** when moving config/availability/severity. | Medium | High | Import-time side effects are easy to reorder wrongly. |
| K5 | **Reporting output drift** when breaking up the 1,128-line writer. | Medium | Medium | Needs golden/snapshot fidelity. |
| K6 | **Plugin/discovery breakage** from import-path churn. | Low | High | Contract is stable; only paths move. |
| K7 | **Duplicate run-path divergence** discovered (paths not equivalent). | Medium | High | Consolidation may expose real behavioral differences. |
| K8 | **Migration complexity / long-branch conflicts** on the largest files. | High | Medium | The big files are merge magnets during a long effort. |
| K9 | **Testing gaps** — extracted units lack tests; false confidence. | Medium | Medium | Today the worst god methods are largely untested. |
| K10 | **Scope creep** into rewrites/features under cover of "refactor." | Medium | Medium | Must hold the "move not rewrite" line. |

---

## Phase 7 — Success Criteria (measurable, with rationale)

These define "done" for a *future* decomposition; they are targets to ratify in
design, stated as measurable thresholds.

- **Method size: target ≤ ~50 lines, hard ceiling ~80; cyclomatic complexity ≤ ~10.**
  *Why:* a unit that fits on a screen and has few branches is comprehensible and
  unit-testable. Today the worst offender is 1,128 lines — ~22× the target.
- **Class size: target ≤ ~300 lines and a single responsibility; ≤ ~12 public
  methods.** *Why:* SRP and reviewability. Today the worst is 1,136 lines / 53
  methods.
- **No module is a responsibility aggregation point — one reason to change per
  module.** *Why:* the breadth problem behind both god modules.
- **Acyclic dependency graph; logic is importable and runnable without the GUI
  toolkit.** *Why:* cycles block separation; GUI-free logic is the precondition for
  real unit testing. Measurable via an import-graph check and a "no GUI import in
  core logic" check.
- **Each decomposed logic unit has unit tests; the current S1 god methods are brought
  under test; overall coverage rises from the present gate.** *Why:* today the
  highest-risk code (run loop, verifier, HTML writer) is the least tested.
- **Single ownership: every responsibility (perception, decision, orchestration,
  protocol, persistence, presentation, authoring UI) has exactly one owning unit, and
  cross-cutting concerns flow one direction.** *Why:* eliminates the "edit six places"
  and "logic reaches into UI" patterns.
- **One canonical run path** (no parallel duplicated run methods), proven
  behavior-equivalent. *Why:* removes drift risk (K7).
- **Full test suite green at every increment; live suite re-validated on the rig after
  any change to the run/perception path.** *Why:* the only backstops available given
  the untestable live path.

---

## Phase 8 — Open Questions for the Design Phase

To be answered **before** design. Grouped by boundary type.

**Ownership boundaries**
- Who owns ambient state today held as globals (configuration, availability flags,
  severity matrix) — a single explicit owner, or injected into each consumer?
- Are the four persisted stores (config, assets, templates, metadata) one ownership
  concern or four?
- Are the multiple run paths one responsibility with variants, or genuinely distinct
  responsibilities? (Must be settled before anything touches them.)

**Responsibility boundaries**
- Where exactly does "perception" (capture + OCR + colour) end and "verification
  policy" (pass/fail rules) begin?
- Is reporting one responsibility or three (normalize data · compose presentation ·
  write a format)? (The new template layer suggests three — confirm for the legacy
  writer.)
- Is default-flow derivation part of the model, the engine, or a policy of its own?
- Where is the line between the flow **data model**, the **engine** that runs it, and
  the **GUI** that edits it?

**Dependency boundaries**
- What is the single allowed direction between GUI, orchestration, and logic — and
  how is "logic must not depend on the GUI" enforced mechanically?
- Which existing one-way dependencies (capabilities→kernel; standalone reporting/asset
  modules *not* depending on the kernel) are invariants that must never be inverted?

**Abstraction boundaries**
- What stable interfaces must exist between perception, decision, action (protocol/
  navigation), and reporting *before* any separation, so units can be swapped/mocked?
- What is the minimal contract the orchestration layer needs from the execution layer
  (and vice-versa) so neither holds the other's internals?

**Runtime boundaries**
- Which responsibilities must remain on the GUI main thread vs. worker threads, and
  which are timing-sensitive (the multi-frame sampler) and therefore cannot be moved
  across a boundary that adds latency?
- Which startup side effects (config load, OCR init, protocol registration, plugin
  discovery, legacy-adapter registration) have ordering requirements that any new
  composition must preserve?

---

## Deliverables index

This document provides: (1) responsibility inventory — Phase 1; (2) complexity
assessment — Phase 2; (3) god-module / (4) god-class / (5) god-method analyses —
Phase 2.1–2.3; (6) decomposition-candidate list — Phase 3; (7) dependency-hotspot
analysis — Phase 5; (8) architectural constraints — Phase 4; (9) risk assessment —
Phase 6; (10) success criteria — Phase 7; (11) open questions for Design — Phase 8.

**No solution, target structure, naming, layout, or migration steps are proposed —
by design.** Those begin only after this planning review is approved.
