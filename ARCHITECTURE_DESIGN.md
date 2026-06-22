# WilloWisp Framework — Architecture Assessment & Design

**Status:** Draft for review · **Parts 1–4 + 6** of the architecture initiative
**Date:** 2026-06-22
**Companion to:** [`ARCHITECTURE_REQUIREMENTS.md`](ARCHITECTURE_REQUIREMENTS.md) (Part 5)

> This document delivers the remaining sections requested:
> **(1)** architectural assessment, **(2)** scalability & maintainability risks,
> **(3)** proposed abstraction layers & interfaces, **(4)** recommended design patterns,
> **(6)** migration strategy. Every recommendation traces to a requirement ID (FR-/NFR-) from Part 5.

---

## 1. Architectural Assessment of the Current Design

### 1.1 What the system is today

A single Tkinter desktop application (`baru.py`, ~7,400 lines) plus six focused modules
(`iscs_workflow.py` ~4,350, `iscs_reports.py` ~1,590, `iscs_assets.py` ~1,010, `iscs_recorder.py`,
`iscs_OCR.py`, optional `iscs_Sampler_Anchor.py`). The module *boundaries* are sound — OCR, recording,
reporting, and the asset store are already separated and communicate through plain dataclasses/JSON.
The problem is not the file split; it is **how behavior is dispatched and constructed inside those
modules**.

### 1.2 The execution core — the central coupling point

The heart of the system is `ProcedureRunner._execute_procedure` ([`iscs_workflow.py:1176`](iscs_workflow.py:1176)),
which routes a step to an executor via a **hardcoded dispatch dict** keyed by a **closed enum**:

```python
class ProcedureType(str, Enum):          # iscs_workflow.py:110  — closed set, 19 values
    TRIGGER_ALARM = "trigger_alarm"
    ...

dispatch = {                             # iscs_workflow.py:1191 — rebuilt every call, in the engine
    ProcedureType.TRIGGER_ALARM      : self._exec_trigger_alarm,
    ProcedureType.VERIFY_ALARM_PANEL : self._exec_verify_alarm_panel,
    ... 19 entries ...
}
fn = dispatch.get(proc.proc_type)
```

Each `_exec_*` is a **bound method of the runner** with a bespoke role, and verifications delegate
into the giant `ISCSVerifier` class ([`baru.py:1049`](baru.py:1049)). Consequences:

- The engine **knows every concrete step type by name**. Adding one violates Open/Closed.
- Executors are not independently testable — they need a live `ProcedureRunner`, `ISCSVerifier`,
  protocol handler, and often a real screen.
- `ProcedureType` is a **closed enum**, so step types cannot come from a plugin — a plugin cannot add
  an enum member.

**The "add one thing, edit six places" tax.** Introducing a new verification today requires edits to:
(1) the `ProcedureType` enum, (2) a new `_exec_*` method, (3) the `dispatch` dict, (4)
`auto_register_procedures` ([`iscs_workflow.py:626`](iscs_workflow.py:626)), (5) the `AddStepDialog`
UI palette, and (6) `normalize_results` in `iscs_reports.py` so it renders. This is the single biggest
obstacle to the objectives.

### 1.3 What is already done right (the seeds to build on)

The codebase already contains **two working instances of the exact pattern we want to generalize** —
this de-risks the whole proposal:

- **`ProtocolManager`** ([`baru.py:995`](baru.py:995)) is a real registry:
  `register_protocol("MODBUS", ModbusProtocol)`, lookup by string key, lazy instantiation, and a
  `BaseProtocol` ABC ([`baru.py:880`](baru.py:880)) with `trigger_alarm`/`reset_alarm`. This is
  precisely the Registry + Strategy + Factory model FR-1/FR-12 ask for — it just needs to be applied
  to the other capability categories.
- **Manual dependency injection already exists**: `ProcedureRunner.__init__(flow, verifier, handler,
  config, on_log, stop_event, pause_event)` ([`iscs_workflow.py:905`](iscs_workflow.py:905)) takes its
  collaborators as constructor parameters rather than building them. FR-26 formalizes and centralizes
  what is already a constructor-injection habit.
- **The IOGroup flow tree is a Composite** ([`iscs_workflow.py:406`](iscs_workflow.py:406)) — per-IO
  folders holding step sequences. The reporting widget/template model (FR-30) reuses the same shape.
- **Normalized result records** already flow generically in places: `custom_checks` from asset-bound
  steps are picked up by `normalize_results` ([`iscs_reports.py:176`](iscs_reports.py:176)) and
  rendered as a distinct report card — a proof that a generic, data-driven result contract (FR-10) is
  feasible.
- **Graceful optional-dependency degradation** (`UPGRADES_AVAILABLE`, `RECORDER_AVAILABLE`,
  `_ASSETS_AVAILABLE`, `WORKFLOW_AVAILABLE`) is an established value — FR-18 generalizes it.

### 1.4 Assessment summary

| Dimension | Current state | Verdict |
|---|---|---|
| Module separation (OCR/record/report/assets) | Already separate, JSON/dataclass contracts | **Good — keep** |
| Step dispatch | Closed enum + hardcoded dict in the engine | **Primary risk — replace** |
| Protocol handling | Registry + ABC already in place | **Good seed — generalize** |
| Verification | Monolithic `ISCSVerifier` owns all verify logic | **Decompose into capabilities/backends** |
| Construction/wiring | Manual constructor injection, scattered | **Centralize via DI container** |
| Reporting | One hardcoded layout; normalizer knows result shapes | **Add template/widget layers** |
| Cross-module reactions | Direct calls (runner → recorder, runner → report) | **Introduce event bus** |
| Persistence/versioning | JSON/SQLite, no schema version field | **Add schema versioning** |
| Testability | Requires live screen/Tk/device | **Enable via contracts + context** |

**One-line verdict:** the *module geography* is healthy; the *dispatch and construction mechanics* are
the bottleneck. The fix is to generalize a pattern the codebase already proves works
(`ProtocolManager`) across all capability categories.

---

## 2. Scalability & Maintainability Risks

Ordered by severity. Each names the requirement that retires it.

| # | Risk | Evidence | Impact | Retired by |
|---|---|---|---|---|
| **R1** | **Closed-enum dispatch** blocks plugin step types and forces 6-file edits per capability. | `ProcedureType` enum + `dispatch` dict | High change-cost; merge conflicts; the core objective is unmet. | FR-2, FR-3, FR-8 |
| **R2** | **God objects.** `baru.py` (UI + protocols + verifier + suite runner + metadata store) and `ISCSVerifier` concentrate unrelated responsibilities. | ~7,400-line file; `ISCSVerifier` owns all verify_* | Low readability; risky edits; poor SRP. | NFR-3 |
| **R3** | **Untestable core.** Executors/verifications need live screen, Tk loop, real Modbus. | `_exec_*` bound to runner+verifier | No CI; regressions caught only by manual runs. | NFR-4, NFR-13 |
| **R4** | **Reporting is single-layout & shape-aware.** `normalize_results` must learn each new result shape; one HTML layout. | `iscs_reports.py:176` | Each new verification touches the report engine; no audience views. | FR-10, FR-30 series |
| **R5** | **Hidden cross-module coupling.** Runner directly drives recorder/report/HUD. | direct calls in runner/suite | New reactive features (metrics, dashboard, AI) require engine edits. | FR-28 |
| **R6** | **No schema versioning.** Saved flows/templates/assets have no version field. | `iscs_template.json`, `procedure_flow` JSON | Format evolution risks breaking old saved data silently. | FR-27 |
| **R7** | **Scattered construction.** Collaborators built ad hoc at call sites (`ISCSVerifier(...)`, `ProcedureRunner(...)` at `baru.py:2093/2144/4147`). | multiple constructions | Wiring duplicated; lifetimes unmanaged; hard to swap fakes. | FR-26 |
| **R8** | **UI palette hardcoded.** `AddStepDialog` enumerates step types by hand. | `iscs_workflow.py:2006` | New capability invisible in UI until UI edited. | FR-5, FR-20 |
| **R9** | **Binding type `if/elif`.** TEXT/IMAGE/HYBRID branching is closed. | `BindingExecutor` | New binding (e.g. vision-LLM) edits the executor. | FR-16 |
| **R10** | **Optional-dep handling is per-module boilerplate**, not uniform. | repeated `try/except ImportError` flags | Inconsistent diagnostics; no single manifest of what loaded. | FR-18, FR-19 |

---

## 3. Proposed Abstraction Layers & Interfaces

Five layers + two cross-cutting spines (matches the Part 5 diagram). Interfaces are sketched as Python
`Protocol`/ABCs — names are illustrative.

### 3.1 Layer 0 — Capability contract (the keystone)

Every action/verification/utility becomes a self-contained **Capability** implementing one contract,
replacing the `_exec_*` methods and the dispatch dict.

```python
# capabilities/base.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class Capability(Protocol):
    key: str                      # stable string key == today's enum value ("verify_alarm_panel")
    category: str                 # "action" | "verification" | "utility" | ...
    metadata: "CapabilityMeta"    # display name, param schema, required resources (FR-5)

    def is_applicable(self, sc) -> bool:            # used by auto-register (FR-21)
        ...
    def execute(self, ctx: "ExecutionContext") -> "StepResult":   # FR-8, uniform call site
        ...
```

`CapabilityMeta` carries the **parameter schema** (drives the dynamic UI editor, FR-20) and declared
required resources (so FR-18 can disable a capability whose backend is missing).

### 3.2 Layer 1 — Capability Registry & discovery

```python
class CapabilityRegistry:
    def register(self, cap: Capability, *, override=False) -> None: ...   # FR-7 dup-check
    def get(self, key: str) -> Capability: ...                            # FR-6, clear error
    def list(self, category: str | None = None) -> list[Capability]: ...  # FR-6, drives UI
    def alias(self, old_key: str, new_key: str) -> None: ...              # FR-23 deprecation
    def manifest(self) -> "LoadManifest": ...                             # FR-19
```

Discovery adapters (FR-3) all funnel into `register()`:

```python
@register("click", category="action")          # decorator style
class ClickAction: ...

discover_by_reflection("plugins.actions")       # reflection style
discover_by_manifest("plugins/**/plugin.json")  # manifest style
discover_by_entry_points("willowisp.capabilities")  # entry-point style
```

> This is `ProtocolManager.register_protocol` ([`baru.py:1003`](baru.py:1003)) generalized to every
> category and given auto-discovery.

### 3.3 Layer 2 — Flow Engine (slimmed)

`ProcedureRunner` keeps orchestration (iterate IOGroups, honour `order`/`enabled`/`depends_on`,
per-step exception→ERROR, FR-11) but loses all per-type knowledge:

```python
cap = registry.get(step.key)            # was: dispatch.get(proc.proc_type)
if not cap.gate_passed(ctx): ...        # depends_on
result = cap.execute(ctx)               # uniform; no if/elif, no enum
bus.publish(StepCompleted(step, result))   # FR-28
```

### 3.4 Layer 3 — Shared Execution Context (Facade over infra)

One object handing capabilities everything they need (FR-9), so call sites never change:

```python
@dataclass
class ExecutionContext:
    point: IOPoint | None
    zones: ResolvedZones            # bbox resolution, anchors
    nav: NavCoords
    protocol: Protocol              # FR-12 (BaseProtocol today)
    backends: BackendRegistry       # FR-13: ctx.backends.get("ocr")
    sampler: FrameSampler | None
    config: ConfigProvider          # FR-17
    log: Callable[[str], None]
    bus: EventBus                   # FR-28
    ids: RunIds                     # suite/loop/card/point identifiers
```

### 3.5 Layer 4 — Infrastructure service interfaces

```python
class Protocol(ABC):                       # exists as BaseProtocol — promote & reuse
    @abstractmethod
    def trigger_alarm(self, payload): ...
    @abstractmethod
    def reset_alarm(self, payload): ...

class VerificationBackend(Protocol):       # FR-13 — OCR / template / colour / vision
    def evaluate(self, image, expectation) -> BackendResult: ...

class BindingResolver(Protocol):           # FR-16 — TEXT / IMAGE / HYBRID / future
    kind: str
    def resolve(self, binding, ctx) -> CheckResult: ...
```

### 3.6 Reporting layers (FR-30 series)

Three independent layers over the **stable normalized result contract** (FR-30e):

```python
class ReportWidget(Protocol):              # FR-30d — self-describing & self-rendering
    key: str
    consumes: list[str]                    # which result fields it needs
    def render(self, data: ResultView, fmt: str) -> Fragment: ...

class ReportTemplate(Protocol):            # FR-30, FR-30b — composes widgets
    key: str
    audience: str                          # engineering | management | audit | ...
    def widgets(self, cfg) -> list[ReportWidget]: ...   # enable/disable/reorder via cfg (FR-30c)

class ReportRenderer(Protocol):            # FR-30f, FR-14 — HTML / Excel / PDF / JSON
    fmt: str
    def emit(self, template: ReportTemplate, data, out_dir) -> Path: ...
```

The existing `normalize_results` output becomes `ResultView` — the immutable fixture that makes
templates/widgets render-testable offline (NFR-13).

### 3.7 Cross-cutting spines

```python
class Container:                           # FR-26 — DI
    def register(self, iface, factory, *, lifetime="singleton"): ...
    def resolve(self, iface): ...          # container.resolve(IProcedureRunner)

class EventBus:                            # FR-28 — pub/sub, isolated delivery (NFR-11)
    def subscribe(self, event_type, handler): ...
    def publish(self, event) -> None: ...  # subscriber error logged, never aborts run
```

---

## 4. Recommended Design Patterns

| Pattern | Where | Requirement | Why |
|---|---|---|---|
| **Registry** | `CapabilityRegistry`, backend/widget/template registries | FR-1, FR-2 | Decouples "what exists" from "who uses it"; already proven by `ProtocolManager`. |
| **Strategy** | Each Capability / VerificationBackend / BindingResolver | FR-8, FR-13, FR-16 | Interchangeable behaviors behind one interface; kills the dispatch dict. |
| **Command** | `Capability.execute(ctx)` | FR-8, FR-11 | A step is a uniform, queueable, loggable command with consistent lifecycle. |
| **Plugin / Abstract Factory** | Discovery adapters (decorator/reflection/manifest/entry-point) | FR-3, FR-4 | Self-registration at import; drop-in extension. |
| **Dependency Injection** | `Container` | FR-26, NFR-4 | Centralized wiring + lifetimes; swap real ↔ fake for tests. |
| **Observer / Pub-Sub** | `EventBus` | FR-28 | Reporting/metrics/recorder/AI react without engine dependencies. |
| **Facade** | `ExecutionContext` | FR-9 | One stable surface over OCR/protocol/sampler/config/bus. |
| **Adapter** | Legacy-executor wrappers; format renderers | FR-25, FR-30f | Wrap old `_exec_*` as Capabilities during migration; adapt one result model to many formats. |
| **Composite** | Flow IOGroups (exists); Template→Widgets | FR-30c | Uniform tree of parts; reuse the proven IOGroup shape. |
| **Template Method** | `BaseCapability` (timing, screenshot, error→ERROR) | FR-11, NFR-1 | Shared step scaffolding; subclasses fill only the specific work. |
| **Chain of Responsibility** | Schema upgraders v1→v2→v3 | FR-27 | Chained, ordered migrations for persisted data. |
| **Builder** | `auto_register_procedures` querying `is_applicable` | FR-21 | Assembles default flow from capabilities, not hardcoded mapping. |
| **Specification** | `Capability.is_applicable(sc)` | FR-21 | Each capability decides its own applicability vs. central if-tree. |

---

## 6. Migration Strategy

**Approach: Strangler Fig.** Stand the registry/engine path up *beside* the existing dispatch, route
new and migrated capabilities through it, and retire the old dispatch only once empty. The legacy path
stays runnable at every step (FR-25), so the app is never broken mid-migration and existing
flows/templates/assets keep working (FR-29, NFR-5).

### Phase 0 — Safety net (no behavior change)
- Capture 3–5 archived `test_logs/` suite runs as **golden fixtures**; assert the *current* HTML/Excel
  output byte-for-byte where stable, structurally otherwise. This is the regression oracle for NFR-5.
- Add a thin `ResultView` serializer around `normalize_results` so reports can be regenerated from a
  saved fixture offline (seeds NFR-13). **No engine changes yet.**

### Phase 1 — Introduce contracts & registry (additive)
- Add `Capability`, `CapabilityRegistry`, `ExecutionContext`, `EventBus`, `Container` modules.
- **Do not touch** `_execute_procedure` behavior yet. Instead, wrap the existing 19 `_exec_*` methods
  as **`LegacyCapabilityAdapter`** instances auto-registered under their current enum-value keys.
- Change `_execute_procedure` to: `registry.get(key).execute(ctx)` **with fallback** to the old
  dispatch dict if a key is unregistered (FR-25). Run golden fixtures — output must be identical.

### Phase 2 — Centralize wiring & events
- Introduce the `Container`; move the scattered `ISCSVerifier(...)`/`ProcedureRunner(...)`/
  `ProtocolManager(...)` constructions ([`baru.py:2093/2144/4147/6306`](baru.py:2093)) behind
  `container.resolve(...)` (FR-26).
- Emit lifecycle events from the runner (`StepStarted/Completed`, `Verification*`, `Suite*`) and make
  the **recorder and report manager subscribers** instead of direct calls (FR-28, retires R5).
  Behavior identical; coupling removed.

### Phase 3 — Migrate capabilities out of the engine (incremental, one PR each)
- Port `_exec_*` real logic into standalone `Capability` classes under `plugins/{actions,verifications,
  utilities}/`, decomposing `ISCSVerifier` so each verification owns its logic + chosen
  `VerificationBackend` (FR-13, retires R2/R3). Delete each enum member + dispatch entry as its
  capability lands. Golden fixtures gate every PR.
- Convert protocol handling: it is already a registry — just route it through the unified `Container`
  and `ExecutionContext` (small change, low risk).
- Convert binding resolvers (TEXT/IMAGE/HYBRID) to registered `BindingResolver`s (FR-16, retires R9).

### Phase 4 — Dynamic UI & auto-discovery
- Drive `AddStepDialog`/`ProcedureFlowDialog` palette and param editors from registry metadata
  (FR-5/FR-20, retires R8). Rebuild `auto_register_procedures` to query `is_applicable` (FR-21).
- Turn on auto-discovery (`plugins/` scan + entry points), establish the NFR-12 directory layout with
  README templates and one reference example per category.

### Phase 5 — Reporting layers
- Refactor `iscs_reports.py` into `ResultView` (data) + `ReportWidget`s + `ReportTemplate`s +
  `ReportRenderer`s. Ship the **Legacy template** first and prove it reproduces Phase-0 golden output
  (FR-30a, NFR-13). Then add Engineering/Management/Audit templates (FR-30b) and PDF/JSON renderers
  (FR-30f). Retires R4.

### Phase 6 — Versioning & hardening
- Add `schema_version` to all persisted artifacts and a Chain-of-Responsibility upgrader; write
  v(N-1)→vN migrators with fixtures (FR-27, retires R6).
- Generalize optional-dependency handling into the registry's load manifest (FR-18/FR-19, retires R10).
- Remove the legacy dispatch fallback once the enum is empty. Publish the contract version (NFR-8).

### Sequencing & risk controls
- **Every phase is shippable** and reversible; the legacy path remains until Phase 6.
- **Golden fixtures run in CI** from Phase 0 — the objective backstop for "equivalent results" (NFR-5).
- **One capability per PR** in Phase 3 keeps reviews small and blast radius minimal.
- Order chosen so the **highest-severity risks fall earliest**: R1/R5 by Phase 1–2, R2/R3/R9 across
  Phase 3, R4 in Phase 5, R6/R10 in Phase 6.

### Migration-to-risk coverage

| Phase | Retires |
|---|---|
| 0 | (establishes NFR-5/NFR-13 oracle) |
| 1 | R1 (mechanism), R8 (groundwork) |
| 2 | R5, R7 |
| 3 | R1 (completed), R2, R3, R9 |
| 4 | R8 |
| 5 | R4 |
| 6 | R6, R10 |

---

## Appendix — "Add a verification" before vs. after

**Before (6 edits, 2 files):** enum value → `_exec_*` method → dispatch entry →
`auto_register_procedures` → `AddStepDialog` palette → `normalize_results`.

**After (1 file):**

```python
# plugins/verifications/verify_high_level.py
@register("verify_high_level", category="verification")
class VerifyHighLevel(BaseVerification):
    metadata = CapabilityMeta(name="Verify High Level", params=SCHEMA, requires=["ocr"])

    def is_applicable(self, sc) -> bool:
        return sc.has_zone("alarm_panel")

    def execute(self, ctx) -> StepResult:
        img = ctx.zones.grab("alarm_panel")
        return ctx.backends.get("ocr").evaluate(img, self.expectation).as_step_result()
```

Auto-discovered (FR-3/FR-4), appears in the UI (FR-20), runs in the engine (FR-8), emits events
(FR-28), and renders in every template (FR-10/FR-30) — **zero engine, dispatcher, enum, UI-list, or
report-normalizer edits** (NFR-1).
