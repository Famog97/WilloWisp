"""
Characterization tests for iscs_assets.AssetManager — the reusable asset
repository (text/image/region/template) persisted to iscs_assets.json.

These lock in ID generation, CRUD, and the persistence/round-trip contract that
the asset-binding verification system depends on. Hermetic: each test points the
asset store at a fresh temp dir and resets the singleton, so nothing touches the
real iscs_assets.json.
"""
import pytest

import iscs_assets
from iscs_assets import AssetManager


@pytest.fixture
def store(tmp_path):
    """A fresh AssetManager rooted in an isolated temp dir."""
    iscs_assets.set_app_dir(tmp_path)
    AssetManager.reset()
    yield AssetManager.instance()
    AssetManager.reset()  # next test's fixture re-points app_dir to a fresh tmp_path


# ──────────────────────────────────────────────────────────────────────────────
#  ID generation
# ──────────────────────────────────────────────────────────────────────────────

def test_text_asset_ids_are_sequential_and_prefixed(store):
    a = store.create_text_asset("High", "HIGH ALARM")
    b = store.create_text_asset("Low", "LOW ALARM")
    assert a.id == "TXT_0001"
    assert b.id == "TXT_0002"


def test_id_counters_are_per_category(store):
    t = store.create_text_asset("t", "v")
    r = store.create_region("r", (0, 0, 10, 10))
    assert t.id.startswith("TXT_")
    assert r.id.startswith("RGN_")
    assert r.id == "RGN_0001"  # independent counter


# ──────────────────────────────────────────────────────────────────────────────
#  CRUD
# ──────────────────────────────────────────────────────────────────────────────

def test_text_asset_crud_cycle(store):
    t = store.create_text_asset("  Spaced  ", "VALUE")
    assert t.name == "Spaced"                       # name is stripped
    assert store.get_text_asset(t.id).value == "VALUE"

    store.update_text_asset(t.id, value="NEW")
    assert store.get_text_asset(t.id).value == "NEW"

    assert store.delete_text_asset(t.id) is True
    assert store.get_text_asset(t.id) is None
    assert store.delete_text_asset(t.id) is False   # already gone


def test_list_text_assets_sorted_by_id(store):
    store.create_text_asset("b", "2")
    store.create_text_asset("a", "1")
    ids = [t.id for t in store.list_text_assets()]
    assert ids == sorted(ids)


def test_update_missing_asset_returns_none(store):
    assert store.update_text_asset("TXT_9999", value="x") is None


# ──────────────────────────────────────────────────────────────────────────────
#  Persistence & counter resumption
# ──────────────────────────────────────────────────────────────────────────────

def test_assets_persist_across_reload(store, tmp_path):
    store.create_text_asset("Persisted", "KEEP ME")
    store.create_region("Zone", (1, 2, 3, 4), monitor_index=1)

    # Simulate an app restart: drop the singleton, reload from disk.
    AssetManager.reset()
    reloaded = AssetManager.instance()

    texts = reloaded.list_text_assets()
    assert [t.value for t in texts] == ["KEEP ME"]
    region = reloaded.list_regions()[0]
    assert (region.x1, region.y1, region.x2, region.y2) == (1, 2, 3, 4)
    assert region.monitor_index == 1


def test_counter_resumes_after_reload_no_id_collision(store):
    first = store.create_text_asset("a", "1")        # TXT_0001
    AssetManager.reset()
    reloaded = AssetManager.instance()
    second = reloaded.create_text_asset("b", "2")     # must NOT reuse TXT_0001
    assert first.id == "TXT_0001"
    assert second.id == "TXT_0002"
