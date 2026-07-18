from types import SimpleNamespace

from councilhound.impact.context import geohub


def test_commercial_retail_zones_combine_whole_and_split_parcels(tmp_path, monkeypatch):
    captured = {"calls": []}
    parcel_feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
        "properties": {"ZONE1": "CR", "SPLITZONED": "N"},
    }
    split_feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]],
        },
        "properties": {"ZONE": "CR"},
    }

    def fake_fetch(url, **kwargs):
        captured["calls"].append({"url": url, **kwargs})
        feature = parcel_feature if "Parcels" in url else split_feature
        return {"type": "FeatureCollection", "features": [feature]}

    class FakeManifest:
        def __init__(self, _slug):
            pass

        def record(self, layer, provenance, stats):
            captured.update(layer=layer, provenance=provenance, stats=stats)

    monkeypatch.setattr(geohub, "context_dir", lambda _slug: tmp_path)
    monkeypatch.setattr(geohub, "fetch_all_features", fake_fetch)
    monkeypatch.setattr(geohub, "Manifest", FakeManifest)
    ctx = SimpleNamespace(cfg=SimpleNamespace(
        slug="fairfax_city_va",
        parcels_source="https://example.test/Parcels/FeatureServer/0",
        zoning_source="https://example.test/ZoningSplits/FeatureServer/0",
    ))

    result = geohub.load_commercial_retail_zones(ctx)

    assert captured["calls"] == [
        {
            "url": ctx.cfg.parcels_source,
            "where": "ZONE1 = 'CR' AND SPLITZONED = 'N'",
            "out_fields": "ZONE1,SPLITZONED",
        },
        {
            "url": ctx.cfg.zoning_source,
            "where": "ZONE = 'CR'",
            "out_fields": "ZONE",
        },
    ]
    assert len(result["features"]) == 1
    assert result["features"][0]["properties"] == {"ZONE": "CR"}
    assert result["features"][0]["geometry"]["type"] == "Polygon"
    assert captured["layer"] == "zoning_commercial_retail"
    assert len(captured["provenance"]) == 2
    assert captured["stats"] == {
        "parcel_features": 1,
        "split_features": 1,
        "dissolved_parts": 1,
        "zone": "CR",
    }
