"""ArcGIS Feature Service access + GeoHub layer discovery.

Two jobs:
- a generic paged fetcher for any ArcGIS FeatureServer/MapServer layer
  (GeoHub layers, TIGERweb, FEMA all speak the same REST dialect);
- discovery of the city's open-data layer URLs from its GeoHub portal's
  DCAT catalog (data.json), pinning what it finds into the jurisdiction
  YAML so later runs (and reviewers) see exactly which endpoint fed which
  layer. URLs are never guessed: discovery reads the catalog or fails.

Fetches go through councilhound.http (global throttle + retries). The
fairfaxva.gov WAF rejects non-browser user agents, so city-hosted pages use
the scraper's FAIRFAX_HEADERS; Esri-cloud hosts don't need them but the
shared session UA is browser-like anyway.
"""
from __future__ import annotations

import json
import logging
import re

from councilhound import http
from councilhound.impact.cache import Manifest, atomic_write_json, context_dir
from councilhound.impact.provenance import prov

log = logging.getLogger(__name__)

PAGE_SIZE = 1000


def _envelope_params(bbox: tuple[float, float, float, float] | None) -> dict:
    """Optional spatial filter: (minx, miny, maxx, maxy) in EPSG:4326."""
    if bbox is None:
        return {}
    return {
        "geometry": ",".join(str(v) for v in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }


def _page(url: str, params: dict, features_key: str = "features"):
    offset = 0
    while True:
        resp = http.get(url, params={**params, "resultOffset": str(offset),
                                     "resultRecordCount": str(PAGE_SIZE)}, timeout=120)
        payload = resp.json()
        if "error" in payload:
            raise RuntimeError(f"ArcGIS query failed for {url}: {payload['error']}")
        page = payload.get(features_key, [])
        yield from page
        if len(page) < PAGE_SIZE and not payload.get("exceededTransferLimit"):
            break
        offset += len(page)
        if not page:  # defensive: some servers omit exceededTransferLimit
            break


def fetch_all_features(layer_url: str, where: str = "1=1", out_fields: str = "*",
                       geometry_precision: int = 6,
                       bbox: tuple[float, float, float, float] | None = None) -> dict:
    """Page through an ArcGIS layer's /query endpoint; return one GeoJSON
    FeatureCollection. Works for hosted FeatureServers (maxRecordCount is
    commonly 1000-2000) and MapServer layers."""
    url = layer_url.rstrip("/")
    if not url.endswith("/query"):
        url += "/query"
    params = {
        "where": where,
        "outFields": out_fields,
        "f": "geojson",
        "outSR": "4326",
        "geometryPrecision": str(geometry_precision),
        **_envelope_params(bbox),
    }
    return {"type": "FeatureCollection", "features": list(_page(url, params))}


def fetch_all_attributes(layer_url: str, where: str = "1=1", out_fields: str = "*",
                         bbox: tuple[float, float, float, float] | None = None) -> list[dict]:
    """Attribute-only paging (returnGeometry=false) — for layers whose rows
    carry what we need (e.g. census blocks publish POP100 + centroid fields),
    skipping megabytes of polygon geometry."""
    url = layer_url.rstrip("/")
    if not url.endswith("/query"):
        url += "/query"
    params = {
        "where": where,
        "outFields": out_fields,
        "f": "json",
        "returnGeometry": "false",
        **_envelope_params(bbox),
    }
    return [feature.get("attributes", {}) for feature in _page(url, params)]


# GeoHub dataset title (lowercased) -> jurisdiction config attribute
DISCOVERY_TITLES = {
    "city boundary": "boundary_source",
    "parcels": "parcels_source",
    "zoning splits": "zoning_source",
}


def _portal_catalog_url(portal_page_url: str) -> str:
    """The city page links to an ArcGIS Hub site; its DCAT catalog lives at
    /data.json on the hub domain."""
    from councilhound.scraper.fairfax_projects import FAIRFAX_HEADERS
    headers = FAIRFAX_HEADERS if "fairfaxva.gov" in portal_page_url else None
    html = http.get(portal_page_url, headers=headers).text
    match = re.search(r"https?://[a-z0-9.-]*opendata\.arcgis\.com/?", html)
    if not match:
        raise RuntimeError(
            f"could not find an opendata.arcgis.com hub link on {portal_page_url}"
        )
    return match.group(0).rstrip("/") + "/data.json"


def discover_layers(cfg) -> dict[str, str]:
    """Read the portal DCAT catalog and pin any still-null layer URLs into
    the jurisdiction YAML. Returns {attr: url} for what was discovered."""
    if not cfg.geohub_portal_url:
        raise RuntimeError(f"jurisdiction '{cfg.slug}' has no geohub_portal_url configured")
    catalog_url = _portal_catalog_url(cfg.geohub_portal_url)
    catalog = http.get(catalog_url).json()
    discovered: dict[str, str] = {}
    for dataset in catalog.get("dataset", []):
        attr = DISCOVERY_TITLES.get((dataset.get("title") or "").strip().lower())
        if not attr:
            continue
        for dist in dataset.get("distribution", []):
            url = dist.get("accessURL") or dist.get("downloadURL") or ""
            if "FeatureServer" in url or "MapServer" in url:
                discovered[attr] = url
                break
    changed = False
    for attr, url in discovered.items():
        if getattr(cfg, attr) is None:
            setattr(cfg, attr, url)
            changed = True
            log.info("pinned %s = %s", attr, url)
    if changed:
        cfg.save()
    return discovered


def load_boundary(ctx):
    """City boundary as a shapely (multi)polygon in EPSG:4326, cached."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    path = context_dir(ctx.cfg.slug) / "boundary.geojson"
    if not path.exists():
        if ctx.cfg.boundary_source is None:
            discover_layers(ctx.cfg)
        from councilhound.impact.jurisdiction import require_source
        url = require_source(ctx.cfg, "boundary_source")
        fc = fetch_all_features(url)
        if not fc["features"]:
            raise RuntimeError(f"boundary layer {url} returned no features")
        atomic_write_json(path, fc)
        Manifest(ctx.cfg.slug).record(
            "boundary",
            prov("City boundary (GeoHub)", url, "live", "ArcGIS FeatureServer").model_dump(),
            {"features": len(fc["features"])},
        )
    fc = json.loads(path.read_text())
    return unary_union([shape(f["geometry"]) for f in fc["features"]])


def load_commercial_retail_zones(ctx) -> dict:
    """Dissolved city zoning footprint for the CR (Commercial Retail) district.

    Most zoning comes from whole parcels. Split-zoned parcels use the city's
    separate ZoningSplits geometry so only their CR portion is included.
    """
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    path = context_dir(ctx.cfg.slug) / "zoning_commercial_retail_v2.geojson"
    if not path.exists():
        from councilhound.impact.jurisdiction import require_source

        if ctx.cfg.parcels_source is None or ctx.cfg.zoning_source is None:
            discover_layers(ctx.cfg)
        parcels_url = require_source(ctx.cfg, "parcels_source")
        splits_url = require_source(ctx.cfg, "zoning_source")
        parcels = fetch_all_features(
            parcels_url,
            where="ZONE1 = 'CR' AND SPLITZONED = 'N'",
            out_fields="ZONE1,SPLITZONED",
        )
        splits = fetch_all_features(
            splits_url,
            where="ZONE = 'CR'",
            out_fields="ZONE",
        )
        source_features = parcels["features"] + splits["features"]
        if not source_features:
            raise RuntimeError("parcel and zoning-split layers returned no CR features")

        dissolved = unary_union([
            shape(feature["geometry"])
            for feature in source_features
            if feature.get("geometry")
        ]).buffer(0)
        if dissolved.is_empty:
            raise RuntimeError("CR zoning features produced an empty dissolved geometry")
        parts = len(dissolved.geoms) if dissolved.geom_type == "MultiPolygon" else 1
        fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": mapping(dissolved),
                "properties": {"ZONE": "CR"},
            }],
        }
        atomic_write_json(path, fc)
        Manifest(ctx.cfg.slug).record(
            "zoning_commercial_retail",
            [
                prov(
                    "Parcel zoning (GeoHub)",
                    parcels_url,
                    "live",
                    "ArcGIS FeatureServer; filter: ZONE1 = 'CR' AND SPLITZONED = 'N'",
                ).model_dump(),
                prov(
                    "Split-zone fragments (GeoHub)",
                    splits_url,
                    "live",
                    "ArcGIS FeatureServer; filter: ZONE = 'CR'",
                ).model_dump(),
            ],
            {
                "parcel_features": len(parcels["features"]),
                "split_features": len(splits["features"]),
                "dissolved_parts": parts,
                "zone": "CR",
            },
        )
    return json.loads(path.read_text())
