# Plugins

Drop-in capabilities for WilloWisp. Each file here defines one capability that
**self-registers** at import time via `@register()`. Nothing in the app imports
this folder automatically yet — capabilities are surfaced by the discovery
functions in `iscs_core.discovery`:

```python
from iscs_core import discover_directory
discover_directory("plugins/actions")     # imports every *.py here → they register
```

## Layout (NFR-12)

One folder per capability category. Add a capability by copying the reference
example into the right folder and editing it — **no engine, dispatcher, enum, UI
list, or report code is touched.**

```
plugins/
├── actions/          # TRIGGER, CLICK, NAVIGATE, … (see example_action.py)
├── verifications/    # OCR / colour / template checks → return PASS/FAIL
├── utilities/        # DELAY, SCREENSHOT, …
├── protocols/        # Modbus / SNMP / future transports
├── backends/         # OCR / template / colour / vision engines
├── report_sinks/     # HTML / Excel / PDF / JSON writers
├── report_widgets/   # self-describing report widgets
├── report_templates/ # composable, audience-specific templates
└── modes/            # execution modes
```

## Anatomy of a capability

```python
from iscs_core import register, CapabilityMeta, StepResult, StepStatus

@register()                       # self-registers into the global registry
class MyVerification:
    key = "verify_my_thing"       # stable string key (== a flow step's proc_type)
    meta = CapabilityMeta(
        name="Verify My Thing",
        category="verification",
        description="What it checks.",
        params_schema={"threshold": {"type": "number", "default": 0.85}},
        requires=["ocr"],         # backends/resources it needs (for graceful disable)
    )
    def execute(self, ctx) -> StepResult:
        # ctx carries the runtime collaborators (point, zones, log, backends…)
        return StepResult(StepStatus.PASS, message="ok")
```

Registering a capability under an existing key (e.g. `verify_alarm_panel`)
**supersedes** that step's legacy adapter automatically — the engine resolves by
key and never needs editing. See `ARCHITECTURE_DESIGN.md`.

## Discovery styles

| Style | Call | When |
|---|---|---|
| Directory (file drop) | `discover_directory("plugins/actions")` | local, no packaging |
| Package | `discover_package("my_pkg.capabilities")` | importable package |
| Entry points | `discover_entry_points("willowisp.capabilities")` | installed distributions |
