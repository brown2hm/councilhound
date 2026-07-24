"""Parcel layer + assessment join -> value-per-acre surface.

The GeoHub Parcels FeatureServer carries PINs, land-use codes, and geometry
but NO assessed values (verified against the live layer), so values come
from a separate assessment source configured in the YAML:

- assessment_source pointing at an ArcGIS layer -> bulk join on PIN;
- assessment_source "vision" -> per-parcel scrape, LOCAL runs only, used
  lazily by the fiscal module for the ~dozens of parcels an evaluation
  touches (site + multifamily comps), never citywide;
- unset -> parcels still load (intake needs geometry/PINs); value-per-acre
  is skipped with a manifest warning instead of failing the build.

The citywide value-per-acre GeoJSON is a headline artifact when values are
available (brief §6.1).
"""
from __future__ import annotations

import logging

from councilhound.impact.cache import Manifest, atomic_write_json, context_dir
from councilhound.impact.provenance import prov

log = logging.getLogger(__name__)

SQFT_PER_ACRE = 43_560.0


def load_parcels(ctx):
    """GeoDataFrame (EPSG:4326): {pin, land_use, acres, [assessed_total,
    value_per_acre], geometry}."""
    import geopandas as gpd

    slug = ctx.cfg.slug
    path = context_dir(slug) / "parcels.geoparquet"
    if path.exists():
        return gpd.read_parquet(path)

    from councilhound.impact.context import geohub
    if ctx.cfg.parcels_source is None:
        geohub.discover_layers(ctx.cfg)
    from councilhound.impact.jurisdiction import require_source
    url = require_source(ctx.cfg, "parcels_source")
    fc = geohub.fetch_all_features(url)
    gdf = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
    rename = {c: c.lower() for c in gdf.columns if c != "geometry"}
    gdf = gdf.rename(columns=rename)
    if "pin" not in gdf.columns:
        raise RuntimeError(f"parcels layer {url} has no PIN field (got {list(gdf.columns)})")
    gdf["land_use"] = gdf.get("elu")
    gdf["acres"] = gdf.geometry.to_crs(ctx.cfg.crs_projected).area / SQFT_PER_ACRE

    stats = {"parcels": len(gdf)}
    assessments = _load_assessment_table(ctx)
    if assessments is not None:
        before = len(gdf)
        gdf = gdf.merge(assessments, on="pin", how="left")
        joined = gdf["assessed_total"].notna().sum()
        join_rate = joined / before if before else 0.0
        stats.update({"assessment_join_rate": round(float(join_rate), 3)})
        if join_rate < 0.90:
            log.warning("parcel/assessment join rate %.1f%% (<90%%)", join_rate * 100)
        gdf["value_per_acre"] = gdf["assessed_total"] / gdf["acres"].where(gdf["acres"] > 0)
        _write_value_per_acre(ctx, gdf)
    else:
        log.warning("no bulk assessment source configured — value-per-acre surface skipped; "
                    "fiscal module will fetch per-parcel assessments on demand")
        stats["assessments"] = "unavailable (no bulk source)"

    keep = [c for c in ("pin", "land_use", "acres", "assessed_total", "value_per_acre")
            if c in gdf.columns]
    gdf = gdf[keep + ["geometry"]]
    gdf.to_parquet(path)
    Manifest(slug).record(
        "parcels",
        prov("Parcels (GeoHub)", url, "live", "ArcGIS FeatureServer").model_dump(),
        stats,
    )
    return gdf


def _load_assessment_table(ctx):
    """Bulk assessment records as {pin, assessed_land, assessed_improvement,
    assessed_total} or None when no bulk source exists."""
    import geopandas as gpd
    import pandas as pd

    source = ctx.cfg.assessment_source
    if not source or source == "vision":
        return None
    if "FeatureServer" not in source and "MapServer" not in source:
        log.warning("assessment_source %r is not an ArcGIS layer; skipping bulk join", source)
        return None
    from councilhound.impact.context import geohub
    fc = geohub.fetch_all_features(source)
    df = gpd.GeoDataFrame.from_features(fc["features"])
    df = df.rename(columns={c: c.lower() for c in df.columns})
    cols = {c: None for c in ("pin", "assessed_land", "assessed_improvement", "assessed_total")}
    # candidate field names, widest-net; GISCAMA (Fairfax CAMA layer) uses the
    # shapefile-truncated CurrentLan/CurrentBui/CurrentTot
    for target, candidates in (
        ("pin", ("pin", "parcel_id", "parcelid", "map_pin")),
        ("assessed_land", ("assessed_land", "landvalue", "land_value", "aprland",
                           "currentlan")),
        ("assessed_improvement", ("assessed_improvement", "imprvalue", "improvement_value",
                                  "aprbldg", "currentbui")),
        ("assessed_total", ("assessed_total", "totalvalue", "total_value", "aprtot",
                            "currenttot")),
    ):
        for cand in candidates:
            if cand in df.columns:
                cols[target] = cand
                break
    if cols["pin"] is None or (cols["assessed_total"] is None and cols["assessed_land"] is None):
        log.warning("assessment layer %s lacks recognizable fields; skipping", source)
        return None
    out = pd.DataFrame({"pin": df[cols["pin"]]})
    for field in ("assessed_land", "assessed_improvement", "assessed_total"):
        out[field] = pd.to_numeric(df[cols[field]], errors="coerce") if cols[field] else pd.NA
    if cols["assessed_total"] is None:
        out["assessed_total"] = out["assessed_land"].fillna(0) + out["assessed_improvement"].fillna(0)
    return out


def _write_value_per_acre(ctx, gdf):
    """Citywide value-per-acre GeoJSON (headline artifact)."""
    path = context_dir(ctx.cfg.slug) / "value_per_acre.geojson"
    subset = gdf[gdf["value_per_acre"].notna()][["pin", "acres", "value_per_acre", "geometry"]]
    simplified = subset.copy()
    simplified["geometry"] = (simplified.geometry.to_crs(ctx.cfg.crs_projected)
                              .simplify(5 * 3.28084).to_crs("EPSG:4326"))
    atomic_write_json(path, simplified.__geo_interface__)
    log.info("value-per-acre surface: %d parcels -> %s", len(simplified), path.name)
