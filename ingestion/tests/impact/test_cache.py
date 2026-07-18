"""Disk-cache behavior: build-if-missing, atomic writes, manifest (no heavy deps)."""
import json

import pytest

from councilhound.impact import cache


@pytest.fixture(autouse=True)
def tmp_data_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(cache, "RAW_DATA_DIR", str(tmp_path / "data" / "raw"))
    return tmp_path


def test_cached_builds_once(tmp_path):
    target = tmp_path / "layer.json"
    calls = []

    def build(part):
        calls.append(1)
        part.write_text('{"ok": true}')

    p1 = cache.cached(target, build)
    p2 = cache.cached(target, build)
    assert p1 == p2 == target
    assert calls == [1]  # second call was a cache hit
    assert json.loads(target.read_text()) == {"ok": True}


def test_cached_failed_builder_leaves_no_artifact(tmp_path):
    target = tmp_path / "layer.json"

    def bad_build(part):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        cache.cached(target, bad_build)
    assert not target.exists()

    def empty_build(part):
        pass  # writes nothing

    with pytest.raises(RuntimeError, match="produced no file"):
        cache.cached(target, empty_build)


def test_manifest_round_trip():
    m = cache.Manifest("testville")
    m.record("pois", {"source_name": "Overture", "vintage": "2026-06"}, stats={"rows": 812})
    again = cache.Manifest("testville")
    entry = again.get("pois")
    assert entry["provenance"]["vintage"] == "2026-06"
    assert entry["stats"]["rows"] == 812
    assert again.get("missing") is None


def test_raw_path_creates_vintage_dirs():
    p = cache.raw_path("acs", "2023", "b25010.json")
    assert p.parent.is_dir()
    assert p.parent.name == "2023"
