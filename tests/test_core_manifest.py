"""
Tests for iscs_core.manifest — capability load manifest + optional-dependency
probes (FR-18, FR-19, retires R10).

Covers the probe registry (importable / unknown / faulty), the manifest record +
summary, requirement evaluation (report and opt-in disable), and the discovery
integration that feeds loaded/failed entries into the manifest.
"""
import textwrap
from pathlib import Path

import pytest

import iscs_core.manifest as man
from iscs_core import (
    CapabilityRegistry, CapabilityMeta, StepResult, StepStatus,
    LoadManifest, evaluate_requirements, register_dependency,
    dependency_status, missing_requirements, importable, discover_directory,
)


@pytest.fixture
def probes():
    """Snapshot/restore the global dependency-probe registry."""
    saved = dict(man._PROBES)
    try:
        yield man._PROBES
    finally:
        man._PROBES.clear()
        man._PROBES.update(saved)


class _Cap:
    def __init__(self, key, requires=()):
        self.key = key
        self.meta = CapabilityMeta(name=key, category="verification", requires=list(requires))
    def execute(self, ctx):
        return StepResult(StepStatus.PASS)


# ── probes ─────────────────────────────────────────────────────────────────────

def test_importable_probe_true_and_false():
    ok, _ = importable("os")()
    assert ok is True
    ok, detail = importable("a_module_that_does_not_exist_xyz")()
    assert ok is False and "a_module_that_does_not_exist_xyz" in detail


def test_unknown_dependency_is_assumed_available():
    ok, detail = dependency_status("some_engine_provided_thing")
    assert ok is True and "assumed available" in detail


def test_register_dependency_duplicate_rejected(probes):
    register_dependency("dep_x", lambda: (True, ""))
    with pytest.raises(ValueError):
        register_dependency("dep_x", lambda: (True, ""))
    register_dependency("dep_x", lambda: (False, "now gone"), override=True)
    assert dependency_status("dep_x") == (False, "now gone")


def test_faulty_probe_does_not_crash(probes):
    def _boom():
        raise RuntimeError("kaboom")
    register_dependency("dep_boom", _boom)
    ok, detail = dependency_status("dep_boom")
    assert ok is False and "probe error" in detail


def test_missing_requirements_lists_only_unmet(probes):
    register_dependency("present", lambda: (True, ""))
    register_dependency("absent", lambda: (False, "not installed"))
    missing = missing_requirements(["present", "absent", "unknown_ok"])
    assert [n for n, _ in missing] == ["absent"]


# ── manifest record + summary ────────────────────────────────────────────────

def test_manifest_records_and_summarizes():
    m = LoadManifest()
    m.record_loaded("click", category="action", source="plugins/actions/input.py")
    m.record_unavailable("verify_x", "ocr (requires module 'pytesseract')", category="verification")
    m.record_failed("bad_plugin", "RuntimeError: boom", source="plugins/x/bad.py")

    assert {e.identifier for e in m.loaded()} == {"click"}
    assert {e.identifier for e in m.unavailable()} == {"verify_x"}
    assert {e.identifier for e in m.failed()} == {"bad_plugin"}

    s = m.summary()
    assert "1 loaded, 1 unavailable, 1 failed" in s
    assert "verify_x" in s and "bad_plugin" in s

    d = m.as_dict()
    assert d["loaded"][0]["source"].endswith("input.py")


def test_record_registry_backfills_unrecorded_caps():
    reg = CapabilityRegistry()
    reg.register(_Cap("a"))
    reg.register(_Cap("b"))
    m = LoadManifest()
    m.record_loaded("a", category="verification", source="known")  # pre-recorded
    m.record_registry(reg)
    keys = {e.identifier for e in m.loaded()}
    assert keys == {"a", "b"}
    # the pre-recorded one keeps its source (not overwritten)
    assert next(e for e in m.loaded() if e.identifier == "a").source == "known"


# ── requirement evaluation (FR-18) ───────────────────────────────────────────

def test_evaluate_requirements_reports_without_disabling(probes):
    register_dependency("absent", lambda: (False, "missing"))
    reg = CapabilityRegistry()
    reg.register(_Cap("needs_absent", requires=["absent"]))
    reg.register(_Cap("needs_nothing"))
    m = LoadManifest()
    bad = evaluate_requirements(reg, m, disable=False)
    assert bad == ["needs_absent"]
    assert reg.has("needs_absent")            # NOT disabled by default
    assert {e.identifier for e in m.unavailable()} == {"needs_absent"}


def test_evaluate_requirements_disable_unregisters(probes):
    register_dependency("absent", lambda: (False, "missing"))
    reg = CapabilityRegistry()
    reg.register(_Cap("needs_absent", requires=["absent"]))
    evaluate_requirements(reg, LoadManifest(), disable=True)
    assert not reg.has("needs_absent")        # disabled + removed (FR-18)


# ── discovery integration (FR-19) ────────────────────────────────────────────

def _write_plugin(folder: Path, name: str, key: str):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.py").write_text(textwrap.dedent(f"""
        from iscs_core import register, CapabilityMeta, StepResult, StepStatus
        @register()
        class _C:
            key = {key!r}
            meta = CapabilityMeta(name={key!r}, category="action")
            def execute(self, ctx):
                return StepResult(StepStatus.PASS)
    """), encoding="utf-8")


def test_discovery_populates_manifest_loaded_and_failed(tmp_path):
    _write_plugin(tmp_path, "good", "good_cap_m")
    (tmp_path / "bad.py").write_text("raise RuntimeError('boom at import')", encoding="utf-8")
    reg = CapabilityRegistry()
    m = LoadManifest()
    discover_directory(tmp_path, into=reg, manifest=m)

    loaded_keys = {e.identifier for e in m.loaded()}
    failed_ids = {e.identifier for e in m.failed()}
    assert "good_cap_m" in loaded_keys
    assert "bad" in failed_ids
    reason = next(e for e in m.failed() if e.identifier == "bad").reason
    assert "RuntimeError" in reason
