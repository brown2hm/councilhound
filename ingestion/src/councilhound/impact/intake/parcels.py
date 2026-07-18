"""Parcel resolution: project -> dissolved site polygon.

Resolution ladder (brief §6.0.3), each rung only if the previous failed:
  (a) PINs stated in the documents -> lookup in the cached parcels layer;
  (b) project address -> Census geocoder -> point-in-polygon against parcels;
  (c) name match against the Development Review Map feature service point ->
      point-in-polygon against parcels;
  (d) ParcelResolutionError — a human supplies PINs in the spec YAML.

Geometry is returned as GeoJSON in EPSG:4326 (storage CRS); area math
happens in the jurisdiction's projected CRS.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SQFT_PER_ACRE = 43_560.0


class ParcelResolutionError(RuntimeError):
    pass


def resolve_site(ctx, project, stated_pins: list[str]) -> tuple[list[str], dict, float, str]:
    """Returns (pins, geojson_geometry_4326, acres, method)."""
    import re

    parcels = ctx.parcels  # GeoDataFrame with pin/geometry, EPSG:4326

    if stated_pins:
        # PIN whitespace padding varies between the assessment DB, documents,
        # and the GIS layer — compare collapsed forms
        def norm(pin):
            return re.sub(r"\s+", " ", str(pin)).strip()

        normalized = parcels["pin"].map(norm)
        targets = {norm(p) for p in stated_pins}
        matched = parcels[normalized.isin(targets)]
        if len(matched):
            missing = targets - set(normalized)
            if missing:
                log.warning("PINs not found in parcel layer: %s", sorted(missing))
            return _dissolve(ctx, matched, "document_pins")
        log.warning("no stated PIN matched the parcel layer; trying address")

    for getter, method in ((lambda: _address_point(project), "address_geocode"),
                           (lambda: _review_map_point(ctx, project), "review_map")):
        point = getter()  # lazy: the review-map query runs only if needed
        if point is None:
            continue
        hit = parcels[parcels.contains(point)]
        if len(hit):
            return _dissolve(ctx, hit, method)

    raise ParcelResolutionError(
        f"could not resolve parcels for '{project.external_slug}': no usable PINs, "
        "geocoded address, or Development Review Map match. Add parcel PINs to the "
        "spec YAML under `parcels:` and re-run impact-confirm."
    )


def _dissolve(ctx, matched, method: str):
    from shapely.ops import unary_union

    projected = matched.geometry.to_crs(ctx.cfg.crs_projected)
    acres = float(projected.area.sum() / SQFT_PER_ACRE)
    union = unary_union(list(matched.geometry))
    import json
    from shapely.geometry import mapping
    geometry = json.loads(json.dumps(mapping(union)))
    pins = [p for p in matched["pin"].tolist() if p]
    log.info("resolved %d parcel(s) via %s: %.2f acres", len(matched), method, acres)
    return pins, geometry, acres, method


def _address_point(project):
    """Geocode the directory address via the shared Census geocoder helper.
    The project row may already carry city-published coordinates — prefer
    those (they are authoritative for the site marker)."""
    from shapely.geometry import Point

    if project.lat is not None and project.lng is not None:
        return Point(float(project.lng), float(project.lat))
    if not project.address:
        return None
    from councilhound.geocode import geocode_address
    # directory addresses are sometimes ranges ("10500-10530 Main St");
    # geocode the first address in the range
    address = project.address.split("-")[0].strip()
    result = geocode_address(address)
    if result:
        return Point(result["lng"], result["lat"])
    return None


def _review_map_point(ctx, project):
    """Name match against the Development Review Map FeatureServer."""
    from shapely.geometry import Point

    from councilhound.impact.context import geohub

    url = ctx.cfg.development_review_map_source
    if not url:
        return None
    try:
        fc = geohub.fetch_all_features(url, out_fields="Name,ProjectURL")
    except Exception as exc:
        log.warning("Development Review Map query failed: %s", exc)
        return None
    from councilhound.impact.context.pois import name_key
    target = name_key(project.name)
    for feature in fc["features"]:
        props = feature.get("properties") or {}
        feature_url = props.get("ProjectURL") or ""
        if (project.external_slug in feature_url
                or (target and name_key(props.get("Name")) == target)):
            geom = feature.get("geometry") or {}
            if geom.get("type") == "Point":
                x, y = geom["coordinates"][:2]
                return Point(x, y)
    return None
