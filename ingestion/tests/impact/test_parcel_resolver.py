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


def _square(lon, lat, d=0.001):
    return Polygon([(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d)])


def _parcel_layer(pins=("57 4 02 015", "57 4 02 016")):
    # two ~square parcels around lon -77.30, lat 38.85; ~100m sides
    return gpd.GeoDataFrame(
        {"pin": list(pins)},
        geometry=[_square(-77.301, 38.8500), _square(-77.301, 38.8511)],
        crs="EPSG:4326",
    )


def test_document_pins_resolve_and_dissolve():
    layer = _parcel_layer()
    ctx = _Ctx(layer)
    pins, geometry, acres, method, warnings = resolver.resolve_site(
        ctx, _Project(), ["57 4 02 015", "57 4 02 016"])
    assert method == "document_pins"
    assert set(pins) == {"57 4 02 015", "57 4 02 016"}
    assert geometry["type"] in ("Polygon", "MultiPolygon")
    expected = float(layer.geometry.to_crs("EPSG:2283").area.sum() / SQFT_PER_ACRE)
    assert acres == pytest.approx(expected, rel=1e-6)
    assert warnings == []


def test_hyphenated_document_pins_match_padded_layer_pins():
    """The regression that mattered: documents write '57-4-02-076' while the
    GIS layer stores '57 4 02    076'. Whitespace-only normalization matched
    nothing, fell through to the address rung, and resolved ONE parcel of a
    multi-parcel assembly — silently understating the site and its baseline."""
    layer = _parcel_layer(pins=["57 4 02    015", "57 4 02    016"])
    ctx = _Ctx(layer)
    pins, _, acres, method, warnings = resolver.resolve_site(
        ctx, _Project(), ["57-4-02-015", "57-4-02-016"])
    assert method == "document_pins"
    assert len(pins) == 2
    assert warnings == []
    expected = float(layer.geometry.to_crs("EPSG:2283").area.sum() / SQFT_PER_ACRE)
    assert acres == pytest.approx(expected, rel=1e-6)


def test_partial_pin_match_warns():
    ctx = _Ctx(_parcel_layer())
    pins, _, _, method, warnings = resolver.resolve_site(
        ctx, _Project(), ["57 4 02 015", "57 4 02 999"])
    assert method == "document_pins"
    assert pins == ["57 4 02 015"]
    assert any("57 4 02 999" in w for w in warnings)


def test_unmatched_pins_warn_about_single_parcel_fallback(monkeypatch):
    ctx = _Ctx(_parcel_layer())
    monkeypatch.setattr("councilhound.geocode.geocode_address",
                        lambda addr: {"lat": 38.8505, "lng": -77.3005, "matched_address": "x"})
    pins, _, _, method, warnings = resolver.resolve_site(
        ctx, _Project(), ["99 9 99 999"])
    assert method == "address_geocode"
    assert pins == ["57 4 02 015"]
    assert any("SINGLE parcel" in w for w in warnings)


def test_superseded_parent_parcel_is_dropped():
    """Documents routinely name a pre-subdivision parent alongside its child.
    Summing both double-counts the site, so the containing parcel loses."""
    child = _square(-77.301, 38.8500, d=0.0005)
    parent = _square(-77.301, 38.8500, d=0.002)  # contains the child
    layer = gpd.GeoDataFrame({"pin": ["58 3 02 013 C", "58 3 02 013"]},
                             geometry=[child, parent], crs="EPSG:4326")
    ctx = _Ctx(layer)
    pins, _, acres, method, warnings = resolver.resolve_site(
        ctx, _Project(), ["58 3 02 013 C", "58 3 02 013"])
    assert pins == ["58 3 02 013 C"]
    assert any("supersed" in w for w in warnings)
    child_acres = float(gpd.GeoSeries([child], crs="EPSG:4326")
                        .to_crs("EPSG:2283").area.sum() / SQFT_PER_ACRE)
    assert acres == pytest.approx(child_acres, rel=1e-6)


def test_address_geocode_fallback(monkeypatch):
    ctx = _Ctx(_parcel_layer())
    project = _Project()
    monkeypatch.setattr("councilhound.geocode.geocode_address",
                        lambda addr: {"lat": 38.8505, "lng": -77.3005, "matched_address": "x"})
    pins, geometry, acres, method, _ = resolver.resolve_site(ctx, project, [])
    assert method == "address_geocode"
    assert pins == ["57 4 02 015"]


def test_city_published_coordinates_beat_geocoder(monkeypatch):
    ctx = _Ctx(_parcel_layer())
    project = _Project()
    project.lat, project.lng = 38.8516, -77.3005  # inside parcel 016

    def boom(addr):
        raise AssertionError("geocoder must not be called when coords exist")

    monkeypatch.setattr("councilhound.geocode.geocode_address", boom)
    pins, _, _, method, _ = resolver.resolve_site(ctx, project, [])
    assert pins == ["57 4 02 016"]


def test_fails_loudly_when_nothing_resolves(monkeypatch):
    ctx = _Ctx(_parcel_layer())
    project = _Project()
    project.address = None
    monkeypatch.setattr(resolver, "_review_map_point", lambda ctx, p: None)
    with pytest.raises(resolver.ParcelResolutionError, match="impact-confirm"):
        resolver.resolve_site(ctx, project, [])


def test_attached_suffix_matches_detached_layer_suffix():
    """Documents write '58-3-02-013C'; the layer stores '58 3 02    013 C'.
    Whitespace- or separator-only normalization sees two different PINs, which
    is how a three-parcel site resolved to one parcel at Fairfax Square."""
    layer = gpd.GeoDataFrame(
        {"pin": ["58 3 02    013 C", "58 3 02    013 A"]},
        geometry=[_square(-77.301, 38.8500), _square(-77.301, 38.8511)],
        crs="EPSG:4326")
    ctx = _Ctx(layer)
    pins, _, _, method, warnings = resolver.resolve_site(
        ctx, _Project(), ["58-3-02-013C", "58-3-02-013A"])
    assert method == "document_pins"
    assert len(pins) == 2
    assert warnings == []


def test_stacked_condo_records_report_union_acreage():
    """Condominium units are stacked parcel records sharing one footprint;
    summing per-parcel areas counts the footprint once per unit (an 18.5-ac
    site read as ~280 ac)."""
    footprint = _square(-77.301, 38.8500)
    layer = gpd.GeoDataFrame(
        {"pin": [f"57 1 39 {i:03d}" for i in range(1, 6)]},
        geometry=[footprint] * 5, crs="EPSG:4326")
    ctx = _Ctx(layer)
    pins, _, acres, _, _ = resolver.resolve_site(
        ctx, _Project(), [f"57 1 39 {i:03d}" for i in range(1, 6)])
    assert len(pins) == 5
    single = float(gpd.GeoSeries([footprint], crs="EPSG:4326")
                   .to_crs("EPSG:2283").area.sum() / SQFT_PER_ACRE)
    assert acres == pytest.approx(single, rel=1e-6)  # union, not 5x
