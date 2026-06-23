# WilloWisp Framework — Modernization Requirements Specification

**Status:** Draft for review · **Part 5** of the architecture initiative
**Date:** 2026-06-22

> This document covers **requirements only** (functional + non-functional), plus the target
> architecture diagram. The remaining deliverables — (1) architectural assessment, (2) scalability &
> maintainability risks, (3) abstraction layers & interfaces, (4) design patterns, (6) migration
> strategy — are tracked separately and build on the requirement IDs below.

---

## Objectives

- Support future product growth without significant refactoring.
- Minimize code changes when introducing new modules, actions, verifications, utilities, or execution modes.
- Reduce coupling between components.
- Improve maintainability, readability, and testability.
- Enable plugin-style module registration and discovery.
- Support centralized module management and configuration.
- Follow SOLID principles and modern software architecture practices.
- Ensure backward compatibility with existing modules where possible.

## Scope

Re-architect the framework so new modules, actions, verifications, utilities, execution modes,
protocols, and report sinks can be added with minimal, localized code changes, via plugin-style
registration — without breaking existing scenario cards, saved flows, templates, or assets.

**Out of scope (this phase):** Studio/Agent split, remote/VNC capture, headless/CI, web dashboard.
The architecture should *not preclude* these, but they are not requirements here.

## Definitions

| Term | Meaning |
|---|---|
| **Capability** | A pluggable unit of behavior: an action, a verification, a utility, a protocol handler, a verification backend (OCR/template/colour), a report sink, or an execution mode. |
| **Registry** | A central catalog where capabilities self-register and are discovered by string key. |
| **Step** | A `Procedure` instance in a flow; references a capability by stable string key (the current enum `value`). |
| **Contract** | The interface a capability must implement to be invoked uniformly by the engine. |

---

## Functional Requirements

### A. Capability registration & discovery

- **FR-1** The system shall provide a central **registry** for each capability category (actions, verifications, utilities, protocols, verification backends, report sinks, execution modes).
- **FR-2** A new capability shall be addable by defining a single self-contained unit (class/object implementing the contract) and registering it — **without editing the engine, the dispatcher, or any enum**. The current hardcoded `dispatch` dict (`iscs_workflow.py:1191`) and `ProcedureType` enum (`iscs_workflow.py:110`) shall no longer require edits to add a step type.
- **FR-3 (Automatic registration)** The system shall support **automatic capability registration** without manual updates to a central import list or registry. The registration mechanism shall be **pluggable per developer preference**, supporting at minimum:
  - **Decorator** — `@register_action("click")` at class/function definition;
  - **Reflection** — scan a capability package and register all classes implementing a contract;
  - **Plugin manifest** — a declarative file (e.g. `plugin.json`/`plugin.toml`) listing the capabilities a folder provides;
  - **Entry points** — Python packaging entry-point groups, so installed packages contribute capabilities.

  The engine shall treat all four uniformly: whatever the registration style, the result is the same registry entry (FR-1, FR-5).
- **FR-4** The system shall **auto-discover** capability modules placed in a known location (e.g. a `plugins/` package or entry-point group) so dropping in a file makes the capability available without modifying a central import list.
- **FR-5** Each registered capability shall expose **descriptive metadata** (stable key, display name, category, parameter schema, required context/resources) sufficient for the UI to render an editor and for `auto_register_procedures` to decide applicability — replacing today's hardcoded UI step lists in `AddStepDialog`.
- **FR-6** The registry shall support **lookup, listing by category, and existence checks**, and shall fail with a clear, actionable error when a flow references an unknown key (vs. today's generic `NotImplementedError`, `iscs_workflow.py:1214`).
- **FR-7** Duplicate-key registration shall be detected and rejected (or explicitly overridable) with a clear diagnostic.

### B. Uniform execution contract

- **FR-8** Every action/verification/utility capability shall implement a **uniform contract** (e.g. `execute(context) -> StepResult`), so the runner invokes all capabilities polymorphically and contains **no per-type branching**.
- **FR-9** Capabilities shall receive their inputs through a **single execution-context object** (point data, resolved zones/bbox, navigation coords, protocol handler, sampler, config, logger) rather than via bespoke method signatures, so adding a capability never changes the runner's call site. (Today executors take `(proc, ctx, sampler_ok, log)` and are bound methods of the runner.)
- **FR-10** Verification capabilities shall return results in a **normalized result structure** that the report layer consumes generically — so a new verification appears in `Suite_Report.html` and Excel **without changes to `normalize_results`** in `iscs_reports.py`.
- **FR-11** The engine shall preserve existing cross-step semantics: `enabled`/`disabled`, `order`, `depends_on` (skip on failed prerequisite), per-IO `IOGroup` isolation, and the per-step exception-to-`ERROR` wrapping currently in `_execute_procedure`.

### C. Pluggable subsystems

- **FR-12** **Protocol handlers** (Modbus, SNMP, and future protocols) shall be registered capabilities resolved by key, injected into the execution context — decoupled from the main app (`baru.py`) and from `ProcedureRunner.handler`.
- **FR-13** **Verification backends** (OCR via Tesseract, template/`matchTemplate`, colour, datetime, and future backends such as a vision-LLM) shall be pluggable behind a common interface so a verification capability can select a backend by key without importing it directly.
- **FR-14** **Report sinks** (HTML, Excel, and future: JSON/JUnit/web) shall be pluggable so a new output format is added by registering a sink, not by editing `ReportManager`.
- **FR-15** **Execution modes** (Targeted Sequence / Grid Scan / Suite Runner today; future modes) shall be registered and selected through a common mode interface, sharing the same registries and execution context.
- **FR-16** **Asset binding types** (TEXT / IMAGE / HYBRID today) shall be pluggable so a new binding type is a registered resolver, not an `if/elif` chain in `BindingExecutor`.

### C-bis. Configuration & lifecycle

- **FR-17** The system shall provide **centralized configuration** that can enable/disable individual capabilities and supply per-capability settings, sourced from the existing `config.json` (extended), without code changes.
- **FR-18** Capability availability shall degrade gracefully: if an optional dependency or capability is missing, the system shall **disable just that capability** with a clear message and continue — extending today's `try/except` import-guard pattern (`UPGRADES_AVAILABLE`, `RECORDER_AVAILABLE`, etc.) to all capabilities uniformly.
- **FR-19** The registry/config shall expose, at startup, a **manifest of loaded vs. unavailable capabilities** (and why) for diagnostics.

### D. UI & authoring

- **FR-20** The Flow Editor (`AddStepDialog` / `ProcedureFlowDialog`) shall build its step palette and per-step parameter editors **dynamically from registry metadata** (FR-5), so a new capability appears in the UI automatically.
- **FR-21** `auto_register_procedures` shall build default flows by querying capabilities for applicability against the card's zones/IO list, rather than hardcoding the zone→step mapping.

### E. Backward compatibility & persistence

- **FR-22** Existing persisted artifacts shall continue to load and run: saved scenario cards, `procedure_flow` data, `iscs_template.json`, `iscs_assets.json`, and `iscs_metadata.db`. Existing string keys (the current enum `value`s, e.g. `"verify_alarm_panel"`) shall remain the stable capability keys.
- **FR-23** Where a flow references a now-removed/renamed capability, the system shall provide an **alias/deprecation mechanism** rather than failing the run.
- **FR-24** Existing report output (`Suite_Report.html`, Excel layout, evidence tree, rerun history) shall remain functionally equivalent after migration.
- **FR-25** Migration shall be **incremental**: the legacy dispatch path and the new registry path may coexist during transition (e.g. registry falls back to legacy executors for not-yet-migrated types).

### F. Dependency injection, versioning & events

- **FR-26 (Dependency injection)** Capabilities, the runner, protocol handlers, verification backends, and report sinks shall be **instantiated through a dependency-injection container/resolver**, not constructed directly by the execution engine. The engine shall depend on abstractions and request implementations from the container (`container.resolve(IProcedureRunner)`), replacing today's direct construction (`ProcedureRunner(...)`, `ModbusHandler()` in `baru.py`). Lifetime management (singleton vs. per-run vs. per-step) shall be configurable per registration. *(Supports NFR-2, NFR-4.)*
- **FR-27 (Schema versioning of persisted data)** Every persisted flow, template, asset file, and card shall carry a **schema version identifier**. The loader shall:
  - read the version and route to the correct deserializer/upgrader so `v1`, `v2`, `v3` artifacts coexist;
  - **up-convert** older versions to the current in-memory model on load (migrations chained: v1→v2→v3);
  - refuse, with a clear message, versions newer than the running app supports.

  This generalizes FR-22/FR-23 from "string keys are stable" to "the whole document format is versioned and migratable."
- **FR-28 (Event publication / pub-sub)** The system shall provide an **event bus** through which the engine and subsystems publish lifecycle events and any capability/service may subscribe **without direct dependencies** on the publisher. Minimum event set:
  `SuiteStarted`, `CardStarted`, `IOPointStarted`, `StepStarted`, `StepCompleted`, `VerificationPassed`, `VerificationFailed`, `IOPointCompleted`, `RerunStarted`, `CardCompleted`, `SuiteCompleted`.
  Subscribers (report sinks, metrics, recorder overlay, a future AI assistant, a live dashboard) shall react to events instead of being called directly by the runner. Event delivery shall be isolated: a failing subscriber shall not abort the run (ties to NFR-11).
- **FR-29 (Preserve user workflows & operations)** The refactoring shall preserve existing **user workflows and operational procedures**. Changes shall primarily affect internal architecture and extension mechanisms. The user-facing experience — import IO list → pick monitor → draw zones/load template → auto-build flow → run → review report — and all existing flows, templates, assets, and report outputs shall remain familiar and backward-compatible. No requirement in this spec shall be satisfied by a change that forces users to re-author existing flows or re-import existing IO profiles. *(Acceptance gate over FR-22–25, NFR-5.)*

### G. Reporting

- **FR-30 (Pluggable report templates)** Report templates shall be **pluggable and selectable at report-generation time**, allowing the same stored execution results to be rendered with different layouts, content sections, visual styles, and audience-specific views — **without re-executing the suite**. Template selection shall operate on persisted results, so any past run can be re-rendered under any template on demand.
- **FR-30a (Legacy template preserved)** The existing report layout and presentation (`Suite_Report.html`, evidence tree, per-point trace, rerun history, Excel layout) shall be preserved as a built-in **"Legacy" template**, kept as the default to guarantee continuity for existing users. *(Acceptance gate over FR-24, FR-29.)*
- **FR-30b (Built-in template library)** The system shall ship **multiple built-in templates** spanning traditional and modern presentation styles, targeting distinct audiences — at minimum: **Engineering** (full step traces, diagnostics), **Management** (pass-rate summary, trends, KPIs), **Customer Acceptance** (clean pass/fail per requirement, sign-off oriented), **Troubleshooting** (failures-first, evidence-forward), and **Audit** (immutable record, timestamps, full traceability).
- **FR-30c (Composable widgets/sections)** Templates shall be composed of **configurable report widgets and sections**. Users shall be able to **enable, disable, reorder, and configure** widgets **without modifying the report engine** — driven by template configuration, not code.
- **FR-30d (Self-describing, self-rendering widgets)** Each report widget shall **declare the execution data it consumes** and **render itself** from the available results. New widgets shall be addable through the **report extension mechanism** (the registry/plugin model, consistent with FR-2/FR-4/NFR-12) **without changes to existing templates or to report-generation logic**.
- **FR-30e (Three-layer reporting separation)** The reporting system shall separate **(1) execution data**, **(2) report templates**, and **(3) presentation widgets** into independent layers, so report appearance and structure can evolve **independently** of test execution and result collection. The execution-data layer is the existing normalized result model (`normalize_results`), which becomes the **stable contract** widgets bind to.
- **FR-30f (Format-specific presentations)** Output formats — HTML, Excel, PDF, JSON, and future formats — **may implement format-specific presentations and are not required to mirror one another's layout**, provided they all draw from the **same consistent underlying execution data**. A template may therefore render richly in HTML/PDF while exporting a flatter tabular form in Excel/JSON from the identical result set.

---

## Non-Functional Requirements

| ID | Requirement |
|---|---|
| **NFR-1 (Extensibility)** | Adding a typical new action or verification shall require touching **only one new file/unit** plus its tests — zero edits to engine, dispatcher, enums, UI lists, or report normalizer. (Open/Closed.) |
| **NFR-2 (Coupling)** | The execution engine shall depend only on **abstractions** (contracts/registry), not on concrete capability classes, protocol libraries, or `baru.py`. No capability shall import the engine internals. (Dependency Inversion.) |
| **NFR-3 (Cohesion / SRP)** | Each capability and subsystem shall have a single responsibility. The ~7,400-line `baru.py` and ~4,350-line `iscs_workflow.py` shall be decomposed so no single class owns dispatch + execution + UI + protocol concerns simultaneously. |
| **NFR-4 (Testability)** | Every capability and the registry shall be unit-testable **without** a live SCADA screen, real Modbus device, or Tkinter event loop — via mockable context, protocol, and backend interfaces. |
| **NFR-5 (Backward compatibility)** | 100% of existing valid saved flows/templates/assets shall load and execute with equivalent results post-migration (verified against archived `test_logs` runs as regression fixtures). |
| **NFR-6 (Maintainability/Readability)** | No "edit six places to add one thing." A documented, single, discoverable extension point per capability category. New-contributor onboarding example: "add a verification" in <1 page of docs. |
| **NFR-7 (Performance)** | Registration/discovery overhead shall be negligible at startup (one-time import scan); per-step dispatch via registry shall be O(1) lookup, no slower than the current dict dispatch. |
| **NFR-8 (Stability of contracts)** | Capability contracts shall be **versioned**; a contract change shall not silently break dropped-in plugins — incompatible plugins are reported, not crashed. |
| **NFR-9 (Diagnosability)** | Capability load failures, unknown keys, and contract-mismatch errors shall produce clear, logged, user-visible messages (extending the existing `print`/`logging` import-guard pattern). |
| **NFR-10 (Portability)** | The plugin model shall not assume internet, a packaging server, or admin rights — local file/entry-point discovery only, consistent with the current single-machine Windows deployment. |
| **NFR-11 (Safety)** | A faulty plugin shall not crash the suite run: load-time isolation (skip + report) and run-time isolation (per-step exception capture → `ERROR`, already present) shall both apply. |
| **NFR-12 (Documented extension structure)** | Each capability category shall have a **documented, conventional directory structure and a single documented extension mechanism** (see layout below). Each folder shall contain a short `README` template and a minimal reference example. Onboarding target: add a working capability of any category by following one page of docs. |
| **NFR-13 (Reporting testability)** | Report templates and widgets shall be **render-testable against fixture result sets without a live run**: the normalized result model shall be serializable to/loadable from fixtures; each widget shall be independently renderable from a fixture declaring only the data it consumes; each template shall be renderable end-to-end for golden-file/snapshot regression; archived `test_logs/` runs shall be usable as regression fixtures (ties to NFR-5). |

### NFR-12 — conventional plugin layout

```
plugins/
├── actions/          # one file per action capability
├── verifications/
├── utilities/
├── protocols/
├── backends/         # OCR / template / colour / vision verification engines
├── report_sinks/
├── report_widgets/   # self-describing widgets (FR-30d)
├── report_templates/ # composable templates (FR-30, FR-30b)
└── modes/            # execution modes
```

---

## Target Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                   UI LAYER                                 │
│   Scenario Cards · Flow Editor · Asset Manager · Metadata Browser          │
│   (palette + param editors built DYNAMICALLY from registry metadata FR-20) │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │  builds / edits  (string keys, not classes)
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                              FLOW ENGINE                                   │
│   ProcedureRunner — iterates IOGroups & ordered steps, honours             │
│   enabled / order / depends_on; NO per-type branching.                     │
│   Resolves each step's capability from the registry and calls execute().   │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │  resolve(key) → capability
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         CAPABILITY REGISTRY                                │
│   Discovery: decorator · reflection · manifest · entry points (FR-3)       │
│   Lookup by key · list by category · metadata · alias/deprecation (FR-23)  │
│  ┌──────────┬──────────────┬───────────┬───────────┬────────────┬───────┐ │
│  │ Actions  │ Verifications│ Utilities │ Protocols │ ReportSinks│ Modes │ │
│  └──────────┴──────────────┴───────────┴───────────┴────────────┴───────┘ │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │  every capability implements a uniform
                                 │  contract: execute(ctx) -> StepResult (FR-8)
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       SHARED EXECUTION CONTEXT                             │
│   point data · resolved zones/bbox · nav coords · protocol handle ·        │
│   sampler · config · logger · run/loop/card identifiers   (FR-9)           │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │  context hands out infra services
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       INFRASTRUCTURE SERVICES                              │
│   OCR backend · template/colour matcher · vision backend (future) ·        │
│   Modbus/SNMP transport · screen capture · recorder · asset store ·        │
│   metadata DB (SQLite) · config provider · report writers (HTML/Excel/…)   │
└────────────────────────────────────────────────────────────────────────────┘

   ╎ cross-cutting spines, available to every layer ╎
   ┌──────────────────────────┐      ┌────────────────────────────────────┐
   │  DI CONTAINER (FR-26)     │      │  EVENT BUS (FR-28)                  │
   │  resolves contracts →     │      │  StepStarted · VerificationFailed · │
   │  implementations;         │◄────►│  SuiteCompleted · …                 │
   │  manages lifetimes        │      │  subscribers: reports · metrics ·   │
   │                           │      │  recorder · AI assistant · dashboard│
   └──────────────────────────┘      └────────────────────────────────────┘
```

**Reading the diagram**

- **Top-down = control flow.** UI authors flows referencing capabilities by *string key only*; the Flow Engine resolves keys against the **Registry** and invokes each capability through one uniform `execute(ctx)` contract — so the engine never names a concrete action/verification class.
- **Bottom = where the real libraries live.** Capabilities reach infra (OCR, Modbus, capture, report writers) *through the Shared Execution Context*, never by importing them directly — keeping the engine free of `pymodbus`/`tesseract`/`tkinter` imports.
- **DI container** is *how* anything gets constructed (FR-26); **Event Bus** is *how* anything reacts to lifecycle (FR-28). Neither is a layer — both are cross-cutting, which is why reporting/metrics/recorder/AI attach without the engine depending on them.
- A new capability = drop a file in the right `plugins/` folder (NFR-12) → self-registers (FR-3) → appears in the UI palette (FR-20) and the engine (FR-8) → emits/consumes events (FR-28) → renders in reports generically (FR-10). **Zero engine edits.**

### Reporting sub-architecture (FR-30 series)

```
Execution Results (normalized, immutable)      ← stable data contract (FR-30e, FR-10)
        │  consumed by
        ▼
Report Widgets (self-describing, registered)   ← FR-30c, FR-30d  (plugin-discovered, NFR-12)
        │  composed/configured by
        ▼
Report Templates (Legacy, Eng, Mgmt, Audit…)   ← FR-30, FR-30a, FR-30b  (selectable at gen time)
        │  emitted via
        ▼
Format Renderers (HTML · Excel · PDF · JSON)   ← FR-30f, FR-14
```

---

## Constraints carried from the current system

- Single-machine Windows desktop app; optional-dependency graceful degradation is already a design value and must be preserved and generalized.
- Stable string keys already exist (enum `value`s) and are embedded in saved data — these become the public registry keys, which makes backward compatibility achievable.
- Pure-data + JSON persistence layers (`iscs_assets.json`, `iscs_template.json`, SQLite `iscs_metadata.db`) are already decoupled from UI — they should stay as-is and inform the registry/config design.

---

## Traceability

| Objective | Requirements |
|---|---|
| Growth without refactor | FR-1, FR-2, FR-4, FR-26, FR-27, NFR-1 |
| Minimize changes for new capability | FR-2, FR-8, FR-10, FR-20, FR-30c, FR-30d, NFR-1, NFR-6 |
| Reduce coupling | FR-9, FR-12–16, FR-26, FR-28, FR-30e, NFR-2, NFR-3 |
| Maintainability / readability / testability | FR-26, FR-28, NFR-3, NFR-4, NFR-6, NFR-12, NFR-13 |
| Plugin registration & discovery | FR-1–7, FR-30d, NFR-12 |
| Centralized management & config | FR-17, FR-19, FR-26, FR-30c |
| SOLID & modern practices | FR-8, FR-26, FR-28, NFR-1, NFR-2, NFR-3 |
| Backward compatibility | FR-22–25, FR-27, FR-29, FR-30a, FR-30f, NFR-5, NFR-13 |

---

## Requirement inventory

- **Functional:** FR-1 … FR-29, FR-30 (+ FR-30a–f)
- **Non-functional:** NFR-1 … NFR-13

## Pending deliverables (separate parts)

1. Architectural assessment of the current design.
2. Identified scalability and maintainability risks.
3. Proposed abstraction layers and interfaces.
4. Recommended design patterns.
6. Migration strategy from the current implementation.
