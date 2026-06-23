"""
Tests for asset-store schema versioning (FR-27) — the iscs_assets.json file now
carries a schema_version with a chained migration mechanism. Hermetic: each test
points the store at a temp dir and resets the singleton.
"""
import json

import pytest

import iscs_assets
from iscs_assets import AssetManager, ASSETS_SCHEMA_VERSION, _migrate_assets_dict


@pytest.fixture
def store(tmp_path):
    iscs_assets.set_app_dir(tmp_path)
    AssetManager.reset()
    yield AssetManager.instance()
    AssetManager.reset()


def _asset_file(tmp_path):
    return tmp_path / "iscs_assets.json"


# ──────────────────────────────────────────────────────────────────────────────
#  Version tag on save
# ──────────────────────────────────────────────────────────────────────────────

def test_saved_file_includes_schema_version(store, tmp_path):
    store.create_text_asset("Label", "HIGH ALARM")
    raw = json.loads(_asset_file(tmp_path).read_text(encoding="utf-8"))
    assert raw["schema_version"] == ASSETS_SCHEMA_VERSION


# ──────────────────────────────────────────────────────────────────────────────
#  Backward compatibility — pre-versioning files have no schema_version
# ──────────────────────────────────────────────────────────────────────────────

def test_legacy_file_without_version_loads(store, tmp_path):
    store.create_text_asset("Label", "HIGH ALARM")

    # Strip schema_version to simulate a file saved before versioning existed.
    path = _asset_file(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("schema_version", None)
    path.write_text(json.dumps(raw), encoding="utf-8")

    AssetManager.reset()
    reloaded = AssetManager.instance()
    assert [t.value for t in reloaded.list_text_assets()] == ["HIGH ALARM"]


# ──────────────────────────────────────────────────────────────────────────────
#  Future version — handled gracefully (logged, not crashed)
# ──────────────────────────────────────────────────────────────────────────────

def test_future_version_file_does_not_crash_load(store, tmp_path):
    path = _asset_file(tmp_path)
    path.write_text(json.dumps({
        "schema_version": ASSETS_SCHEMA_VERSION + 9,
        "text_assets": [{"id": "TXT_0001", "name": "X", "value": "V",
                         "description": "", "created_at": "", "updated_at": ""}],
    }), encoding="utf-8")

    AssetManager.reset()
    reloaded = AssetManager.instance()       # _load swallows the migration error
    # Too-new file is not loaded, but the app doesn't crash and starts empty.
    assert reloaded.list_text_assets() == []


# ──────────────────────────────────────────────────────────────────────────────
#  Migration mechanism (independent of the real version)
# ──────────────────────────────────────────────────────────────────────────────

def test_migration_chain_runs_in_order():
    calls = []
    migrators = {
        1: lambda d: (calls.append("1→2"), {**d, "v2": True})[1],
        2: lambda d: (calls.append("2→3"), {**d, "v3": True})[1],
    }
    out = _migrate_assets_dict({"schema_version": 1}, migrators=migrators, current=3)
    assert calls == ["1→2", "2→3"]
    assert out["v2"] and out["v3"]


def test_future_version_raises_in_migrator():
    with pytest.raises(ValueError) as ei:
        _migrate_assets_dict({"schema_version": 99}, migrators={}, current=1)
    assert "newer than supported" in str(ei.value)


def test_missing_migrator_raises():
    with pytest.raises(ValueError) as ei:
        _migrate_assets_dict({"schema_version": 1}, migrators={}, current=2)
    assert "No migrator" in str(ei.value)
