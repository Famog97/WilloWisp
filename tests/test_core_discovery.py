"""
Tests for iscs_core.discovery — plugin auto-discovery (FR-3/FR-4) and the
ambient `using_registry` target. All discovery loads into a fresh registry so the
global one (and the live engine) is never touched.
"""
import sys
import textwrap
from pathlib import Path

import pytest

from iscs_core import (
    CapabilityRegistry, register, CapabilityMeta, StepResult, StepStatus,
    using_registry, discover_directory, discover_package, discover_entry_points,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_plugin(folder: Path, name: str, key: str, category="action", body_extra=""):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.py").write_text(textwrap.dedent(f"""
        from iscs_core import register, CapabilityMeta, StepResult, StepStatus
        {body_extra}
        @register()
        class _Cap:
            key = {key!r}
            meta = CapabilityMeta(name={key!r}, category={category!r})
            def execute(self, ctx):
                return StepResult(StepStatus.PASS)
    """), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
#  using_registry — ambient target
# ──────────────────────────────────────────────────────────────────────────────

def test_using_registry_redirects_bare_register():
    reg = CapabilityRegistry()
    with using_registry(reg):
        @register()
        class Tmp:
            key = "ambient_cap"
            meta = CapabilityMeta(name="Ambient", category="action")
            def execute(self, ctx):
                return StepResult(StepStatus.PASS)
    assert reg.has("ambient_cap")
    # ambient target restored after the block → global registry untouched
    from iscs_core import registry as global_reg
    assert not global_reg.has("ambient_cap")


# ──────────────────────────────────────────────────────────────────────────────
#  discover_directory
# ──────────────────────────────────────────────────────────────────────────────

def test_discover_directory_loads_and_registers(tmp_path):
    _write_plugin(tmp_path, "my_action", "tmp_action_x")
    reg = CapabilityRegistry()
    loaded = discover_directory(tmp_path, into=reg)
    assert "my_action" in loaded
    assert reg.has("tmp_action_x")


def test_discover_directory_skips_underscore_files(tmp_path):
    _write_plugin(tmp_path, "_private", "should_not_load")
    reg = CapabilityRegistry()
    loaded = discover_directory(tmp_path, into=reg)
    assert loaded == []
    assert not reg.has("should_not_load")


def test_discover_directory_isolates_bad_plugin(tmp_path):
    _write_plugin(tmp_path, "good", "good_cap")
    (tmp_path / "bad.py").write_text("raise RuntimeError('boom at import')", encoding="utf-8")
    reg = CapabilityRegistry()
    loaded = discover_directory(tmp_path, into=reg)
    # the good plugin still loads; the bad one is logged + skipped, not fatal
    assert "good" in loaded and "bad" not in loaded
    assert reg.has("good_cap")


def test_discover_directory_missing_dir_returns_empty(tmp_path):
    assert discover_directory(tmp_path / "nope", into=CapabilityRegistry()) == []


# ──────────────────────────────────────────────────────────────────────────────
#  discover_package
# ──────────────────────────────────────────────────────────────────────────────

def test_discover_package_imports_submodules(tmp_path):
    pkg = tmp_path / "wisp_test_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _write_plugin(pkg, "cap_mod", "pkg_cap_y")
    sys.path.insert(0, str(tmp_path))
    try:
        reg = CapabilityRegistry()
        loaded = discover_package("wisp_test_pkg", into=reg)
        assert any(name.endswith("cap_mod") for name in loaded)
        assert reg.has("pkg_cap_y")
    finally:
        sys.path.remove(str(tmp_path))
        for m in [m for m in sys.modules if m.startswith("wisp_test_pkg")]:
            del sys.modules[m]


# ──────────────────────────────────────────────────────────────────────────────
#  discover_entry_points — safe when nothing is installed
# ──────────────────────────────────────────────────────────────────────────────

def test_discover_entry_points_empty_group_is_safe():
    assert discover_entry_points("willowisp.nonexistent.group.xyz",
                                 into=CapabilityRegistry()) == []


# ──────────────────────────────────────────────────────────────────────────────
#  The shipped reference plugin actually works
# ──────────────────────────────────────────────────────────────────────────────

def test_reference_example_plugin_discovers():
    reg = CapabilityRegistry()
    discover_directory(REPO_ROOT / "plugins" / "actions", into=reg)
    assert reg.has("example_noop")
    cap = reg.get("example_noop")
    assert cap.meta.category == "action"
    # it runs and returns PASS without any real context
    assert cap.execute(object()).status is StepStatus.PASS
