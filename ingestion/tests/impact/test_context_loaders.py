"""Offline tests for context builders: ArcGIS paging, POI taxonomy + dedup.

Network is always monkeypatched; heavy-geo cases gate on importorskip so the
base CI env (no geopandas) skips them cleanly.
"""
import pytest

from councilhound.impact.context import geohub
from councilhound.impact.context.pois import classify, name_key


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_all_features_pages_until_short_page(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        offset = int(params["resultOffset"])
        calls.append(offset)
        if offset == 0:
            features = [{"type": "Feature", "id": i} for i in range(geohub.PAGE_SIZE)]
            return _Resp({"features": features, "exceededTransferLimit": True})
        return _Resp({"features": [{"type": "Feature", "id": "last"}]})

    monkeypatch.setattr(geohub.http, "get", fake_get)
    fc = geohub.fetch_all_features("https://example/FeatureServer/0")
    assert len(fc["features"]) == geohub.PAGE_SIZE + 1
    assert calls == [0, geohub.PAGE_SIZE]


def test_fetch_all_features_raises_on_arcgis_error(monkeypatch):
    monkeypatch.setattr(geohub.http, "get",
                        lambda url, params=None, timeout=None: _Resp({"error": {"code": 400}}))
    with pytest.raises(RuntimeError, match="ArcGIS query failed"):
        geohub.fetch_all_features("https://example/FeatureServer/0")


@pytest.mark.parametrize("raw,expected", [
    ("supermarket", "grocery"),
    ("shop=supermarket", "grocery"),
    ("Dining and Drinking > Restaurant > Thai Restaurant", "restaurant_bar"),
    ("amenity=cafe", "restaurant_bar"),
    ("shop=convenience", "retail_convenience"),
    ("gas_station", "retail_convenience"),
    ("clothing_store", "retail_comparison"),
    ("shop=furniture", "retail_comparison"),
    ("beauty_salon", "personal_services"),
    ("amenity=bank", "personal_services"),
    ("movie_theater", "entertainment"),
    ("office=lawyer", "office"),
    ("amenity=library", "civic"),
    ("weird_unmatched_thing", "other"),
    (None, "other"),
])
def test_classify_taxonomy(raw, expected):
    assert classify(raw) == expected


def test_name_key_normalizes():
    assert name_key("Trader Joe's #123") == name_key("TRADER JOES 123")
    assert name_key(None) == ""


def test_merge_sources_dedups_same_name_within_50m():
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    from councilhound.impact.context.pois import merge_sources

    def frame(name, x, y, source, cat):
        return gpd.GeoDataFrame(
            {"name": [name], "category_raw": [cat], "source": [source]},
            geometry=[Point(x, y)], crs="EPSG:2283",
        )

    frames = [
        frame("Trader Joe's", 0, 0, "overture", "grocery_store"),
        frame("Trader Joes", 30, 0, "osm", "shop=supermarket"),   # ~9 m away, same name
        frame("Trader Joe's", 5000, 0, "fsq", "grocery"),          # too far -> separate
        frame("Panera", 10, 0, "fsq", "restaurant"),               # near but different name
    ]
    merged = merge_sources(frames)
    assert len(merged) == 3
    tj = merged[merged["name_key"] == name_key("Trader Joe's")]
    assert len(tj) == 2
    kept = tj[tj["source"] == "overture"]
    assert len(kept) == 1
    assert set(kept.iloc[0]["sources"].split(",")) == {"osm", "overture"}
    assert (merged["taxonomy"] == "grocery").sum() == 2


def test_discovery_pins_layer_urls(monkeypatch, tmp_path):
    from councilhound.impact import jurisdiction as jur

    monkeypatch.setattr(jur, "JURISDICTIONS_DIR", tmp_path)
    (tmp_path / "testville.yaml").write_text(
        "name: Testville\n"
        'fips: {state: "51", county: "600"}\n'
        'crs_projected: "EPSG:2283"\n'
        "projects_index_url: https://example.gov/projects\n"
        "geohub_portal_url: https://example.gov/geohub\n"
    )
    cfg = jur.JurisdictionConfig.load("testville")

    portal_html = 'see <a href="https://data-test.opendata.arcgis.com/">hub</a>'
    catalog = {"dataset": [
        {"title": "Parcels", "distribution": [
            {"accessURL": "https://services.example/Parcels/FeatureServer/0"}]},
        {"title": "City Boundary", "distribution": [
            {"downloadURL": "https://services.example/Boundary/FeatureServer/0"}]},
        {"title": "Trees", "distribution": [
            {"accessURL": "https://services.example/Trees/FeatureServer/0"}]},
    ]}

    class _TextResp:
        text = portal_html

        def json(self):
            return catalog

    monkeypatch.setattr(geohub.http, "get", lambda url, **kw: _TextResp())
    discovered = geohub.discover_layers(cfg)
    assert discovered["parcels_source"].endswith("Parcels/FeatureServer/0")
    again = jur.JurisdictionConfig.load("testville")  # pinned to disk
    assert again.parcels_source.endswith("Parcels/FeatureServer/0")
    assert again.boundary_source.endswith("Boundary/FeatureServer/0")
    assert again.zoning_source is None  # not in catalog -> stays null, never guessed
