"""Parcel-resolution ladder against a synthetic parcel layer (offline)."""
import pytest

gpd = pytest.importorskip("geopandas")

from shapely.geometry import Polygon  # noqa: E402

from councilhound.impact.intake import parcels as resolver  # noqa: E402

SQFT_PER_ACRE = 43_560.0


class _Cfg:
    slug = "testville"
    crs_projected = "EPSG:2283"
    development_review_map_source = "https://example/FeatureServer/0/query"


class _Ctx:
    """Just enough JurisdictionContext for resolve_site."""
    cfg = _Cfg()

    def __init__(self, parcels):
        self.parcels = parcels


class _Project:
    external_slug = "test-project"
    name = "Test Project"
    address = "123 Main St"
    lat = None
    lng = None


def _parcel_layer():
    # two ~square parcels around lon -77.30, lat 38.85; ~100m sides
    def square(lon, lat, d=0.001):
        return Polygon([(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d)])

    return gpd.GeoDataFrame(
        {"pin": ["57 4 02 015", "57 4 02 016"]},
        geometry=[square(-77.301, 38.8500), square(-77.301, 38.8511)],
        crs="EPSG:4326",
    )


def test_document_pins_resolve_and_dissolve():
    layer = _parcel_layer()
    ctx = _Ctx(layer)
    pins, geometry, acres, method = resolver.resolve_site(ctx, _Project(), ["57 4 02 015", "57 4 02 016"])
    assert method == "document_pins"
    assert set(pins) == {"57 4 02 015", "57 4 02 016"}
    assert geometry["type"] in ("Polygon", "MultiPolygon")
    expected = float(layer.geometry.to_crs("EPSG:2283").area.sum() / SQFT_PER_ACRE)
    assert acres == pytest.approx(expected, rel=1e-6)


def test_address_geocode_fallback(monkeypatch):
    ctx = _Ctx(_parcel_layer())
    project = _Project()
    monkeypatch.setattr("councilhound.geocode.geocode_address",
                        lambda addr: {"lat": 38.8505, "lng": -77.3005, "matched_address": "x"})
    pins, geometry, acres, method = resolver.resolve_site(ctx, project, [])
    assert method == "address_geocode"
    assert pins == ["57 4 02 015"]


def test_city_published_coordinates_beat_geocoder(monkeypatch):
    ctx = _Ctx(_parcel_layer())
    project = _Project()
    project.lat, project.lng = 38.8516, -77.3005  # inside parcel 016

    def boom(addr):
        raise AssertionError("geocoder must not be called when coords exist")

    monkeypatch.setattr("councilhound.geocode.geocode_address", boom)
    pins, _, _, method = resolver.resolve_site(ctx, project, [])
    assert pins == ["57 4 02 016"]


def test_fails_loudly_when_nothing_resolves(monkeypatch):
    ctx = _Ctx(_parcel_layer())
    project = _Project()
    project.address = None
    monkeypatch.setattr(resolver, "_review_map_point", lambda ctx, p: None)
    with pytest.raises(resolver.ParcelResolutionError, match="impact-confirm"):
        resolver.resolve_site(ctx, project, [])
