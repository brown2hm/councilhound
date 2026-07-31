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

from councilhound.impact.pins import norm_pin

log = logging.getLogger(__name__)

SQFT_PER_ACRE = 43_560.0


class ParcelResolutionError(RuntimeError):
    pass


def resolve_site(ctx, project,
                 stated_pins: list[str]) -> tuple[list[str], dict, float, str, list[str]]:
    """Returns (pins, geojson_geometry_4326, acres, method, warnings).

    `warnings` are caller-visible strings for the spec's extraction_notes.
    A stated PIN that fails to match the parcel layer used to be a log line
    only, which hid the most consequential failure in the pipeline: a
    hyphenated PIN matching nothing, falling through to the address rung,
    and resolving a single parcel of a multi-parcel assembly.
    """
    parcels = ctx.parcels  # GeoDataFrame with pin/geometry, EPSG:4326
    warnings: list[str] = []

    if stated_pins:
        # PIN separators and padding differ between the assessment DB,
        # documents, and the GIS layer — compare canonical forms
        normalized = parcels["pin"].map(norm_pin)
        targets = {norm_pin(p) for p in stated_pins}
        matched = parcels[normalized.isin(targets)]
        matched, superseded = _drop_superseded(matched)
        if superseded:
            warnings.append(
                f"dropped superseded parent parcel(s) ({', '.join(superseded)}) "
                "that spatially contain other stated parcels — counting a "
                "pre-subdivision record alongside its children would "
                "double-count the site area and its assessed value")
        if len(matched):
            missing = targets - set(normalized)
            if missing:
                log.warning("PINs not found in parcel layer: %s", sorted(missing))
                warnings.append(
                    "document-stated PINs not found in the parcel layer: "
                    f"{', '.join(sorted(missing))} — the site polygon covers "
                    f"{len(matched)} of {len(targets)} stated parcels")
            return (*_dissolve(ctx, matched, "document_pins"), warnings)
        log.warning("no stated PIN matched the parcel layer; trying address")
        warnings.append(
            "WARNING: none of the document-stated PINs "
            f"({', '.join(sorted(targets))}) matched the parcel layer; fell "
            "back to address geocode, which resolves a SINGLE parcel — verify "
            "the site extent before evaluating")

    for getter, method in ((lambda: _address_point(project), "address_geocode"),
                           (lambda: _review_map_point(ctx, project), "review_map")):
        point = getter()  # lazy: the review-map query runs only if needed
        if point is None:
            continue
        hit = parcels[parcels.contains(point)]
        if len(hit):
            return (*_dissolve(ctx, hit, method), warnings)

    raise ParcelResolutionError(
        f"could not resolve parcels for '{project.external_slug}': no usable PINs, "
        "geocoded address, or Development Review Map match. Add parcel PINs to the "
        "spec YAML under `parcels:` and re-run impact-confirm."
    )


def _drop_superseded(matched):
    """Remove parcels that spatially contain another matched parcel.

    Documents routinely name both a pre-subdivision parent and its children
    (58 3 02 013 alongside 58 3 02 013 C), and the assessment layer keeps both
    records. Summing them double-counts area and value, so the containing
    parcel loses. Returns (kept, dropped_pins).
    """
    if len(matched) < 2:
        return matched, []
    geoms = list(matched.geometry)
    pins = list(matched["pin"])
    drop = set()
    for i, outer in enumerate(geoms):
        if outer is None or outer.is_empty:
            continue
        for j, inner in enumerate(geoms):
            if i == j or inner is None or inner.is_empty or inner.area <= 0:
                continue
            # >50% of the smaller parcel lying inside the larger one means one
            # record supersedes the other; the larger is the stale parent
            if (outer.area > inner.area
                    and outer.intersection(inner).area / inner.area > 0.5):
                drop.add(i)
                break
    if not drop or len(drop) == len(geoms):
        return matched, []
    keep_mask = [i not in drop for i in range(len(geoms))]
    dropped = [pins[i] for i in sorted(drop)]
    log.info("dropped %d superseded parent parcel(s): %s", len(dropped), dropped)
    return matched[keep_mask], dropped


def _dissolve(ctx, matched, method: str):
    from shapely.ops import unary_union

    projected = matched.geometry.to_crs(ctx.cfg.crs_projected)
    # union, not sum: condominium units are stacked parcel records sharing one
    # footprint, so summing per-parcel areas counts that footprint once per
    # unit (a 269-record condo block summed to ~280 ac of an 18.5-ac site)
    acres = float(unary_union(list(projected)).area / SQFT_PER_ACRE)
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
