# Plugins & extension points

Drop-in extensions for WilloWisp. Each capability **self-registers** at import
time, so adding one touches **no engine, dispatcher, enum, UI list, or report
code**. This page is the one-stop reference (NFR-12) for every extension surface
the framework exposes.

> The migration is complete: **all 19 step types run from plugins** discovered at
> startup. New step types are added the same way — drop a file in, no enum edit.

---

## 1. Capabilities (actions / verifications / utilities)

A capability is one step type, addressed by a stable string `key` (the same value
stored in a saved flow's `proc_type`). It implements `execute(ctx) -> StepResult`.

```python
from iscs_core import register, CapabilityMeta, StepResult, StepStatus

@register()                        # self-registers into the global registry
class MyVerification:
    key = "verify_my_thing"        # stable key == a flow step's proc_type value
    meta = CapabilityMeta(
        name="Verify My Thing",
        category="verification",   # "action" | "verification" | "utility"
        description="What it checks.",
        params_schema={"threshold": {"type": "number", "default": 0.85}},
        requires=["ocr"],          # logical deps — see §4 (graceful disable)
        addable=True,              # show in the Add-Step palette (FR-20)
    )
    def execute(self, ctx) -> StepResult:
        return StepResult(StepStatus.PASS, message="ok")
```

**Superseding a built-in:** register under an existing key with
`@register(override=True)` and your capability replaces that step's legacy adapter
by key — the engine resolves by key and never needs editing. (This is how every
ported step works; see `plugins/actions/protocol.py` for `trigger_alarm`.)

### What `ctx` gives you

`ctx` bridges the runner to the uniform contract. Read collaborators defensively
with `getattr` (so capabilities stay unit-testable with a fake ctx):

| `ctx.…` | What it is |
|---|---|
| `ctx.proc` | the `Procedure` (use `ctx.proc.params` for the step's params) |
| `ctx.exec` | the runner's `ExecContext` — `.pt` (IO point), `.resolved_bbox`, `.trigger_time/ns`, `.sampler`, … |
| `ctx.runner` | the `ProcedureRunner` — `.config`, `.handler` (protocol), `.verifier`, `._sleep(s)` |
| `ctx.log` | `callable(str)` for the UI log |
| `ctx.sampler_ok` | whether the frame sampler is available this run |

### `StepResult`

```python
StepResult(status, message="", screenshot="", data={})
```
Verifications put their per-check rows in `data={"verify_results": [...]}` — the
report layer consumes them generically (no report edits per new verification).

---

## 2. Binding resolvers (asset-bound `verify_custom` — TEXT / IMAGE / HYBRID)

Binding kinds are registered strategies in **`iscs_assets`** (kept standalone — no
`iscs_core` dependency). `BindingExecutor` dispatches by key, no `if/elif`.

```python
from iscs_assets import BindingResolver, register_binding_resolver

class VisionBindingResolver(BindingResolver):
    kind = "VISION"                       # matches StepBinding.type
    def resolve(self, img, resolved) -> dict:
        return {"status": "PASS", "message": "...", "expected": "", "actual": "", "score": 1.0}

register_binding_resolver(VisionBindingResolver())   # override=True to replace a built-in
```

---

## 3. Report widgets, templates, and renderers (`iscs_report_templates`)

Reports are three independent layers (FR-30e): **data** (`ResultView` over the
normalized results) → **widgets** (self-rendering sections) → **templates**
(ordered widget lists). Output formats (HTML/PDF/JSON) draw from the same data.

```python
from iscs_report_templates import ReportWidget, register_widget, TEMPLATES

class BannerWidget(ReportWidget):
    key = "banner"
    consumes = ("meta",)                  # which ResultView fields it reads
    def render(self, view) -> str:        # view.records / view.summary / view.meta
        return "<div class='banner'>CONFIDENTIAL</div>"

register_widget(BannerWidget())

# A template is pure config — an ordered list of widget keys (enable/reorder freely):
TEMPLATES["my_view"] = {"name": "My View", "audience": "ops", "order": 35,
                        "filename": "My_View.html",
                        "widgets": ["header", "banner", "kpis"]}
```

`list_templates()` returns templates in `order`. The picker (📊) lists them
Legacy → Audit → Engineering → Management → PDF → JSON. JSON/PDF are
format-specific renderers (a `render`/`write` hook instead of a widget list).

---

## 4. Dependency probes & the load manifest (FR-18/FR-19)

A capability declares logical resources in `meta.requires` (e.g. `["ocr"]`,
`["assets"]`). At startup `baru._load_plugins()` builds a **`LoadManifest`** —
what loaded / what's unavailable (unmet requirement) / what failed to import — and
prints one diagnostic block. Register a probe for a new logical dependency:

```python
from iscs_core import register_dependency, importable
register_dependency("vision", importable("my_vision_pkg"))   # or any () -> (ok, detail)
```

Unknown requirement names (engine-provided, e.g. `verifier`) are assumed
available. Reporting is the default; `evaluate_requirements(reg, manifest,
disable=True)` would unregister capabilities with unmet deps.

---

## 5. Layout (NFR-12)

One folder per category; copy the reference example and edit it.

```
plugins/
├── actions/          # trigger/reset, click, navigate, … (reference: example_action.py)
├── verifications/    # OCR / colour / template / custom checks → PASS/FAIL
├── utilities/        # delay, screenshot, …
├── protocols/        # Modbus / SNMP / future transports
├── backends/         # OCR / template / colour / vision engines
├── report_sinks/     # HTML / Excel / PDF / JSON writers
├── report_widgets/   # self-describing report widgets
├── report_templates/ # composable, audience-specific templates
└── modes/            # execution modes
```

## 6. Discovery styles

| Style | Call | When |
|---|---|---|
| Directory (file drop) | `discover_directory("plugins/actions")` | local, no packaging |
| Package | `discover_package("my_pkg.capabilities")` | importable package |
| Entry points | `discover_entry_points("willowisp.capabilities")` | installed distributions |

At startup, `baru._load_plugins()` runs `discover_directory` over
`actions / verifications / utilities`. See `ARCHITECTURE_DESIGN.md` for the full design.
