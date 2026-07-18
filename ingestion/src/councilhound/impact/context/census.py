"""Census loaders: ACS 5-year (block group), TIGERweb geometries, LEHD LODES.

Outputs are cached GeoDataFrames (geoparquet) keyed by data vintage; every
build records provenance in the context manifest. The ACS loader verifies
the city's total population lands within 10% of the configured expectation
(brief §8 data-quality gate) so a bad geography filter fails at build time,
not in a published report.
"""
from __future__ import annotations

import gzip
import io
import logging

from councilhound import http
from councilhound.config import CENSUS_API_KEY
from councilhound.impact.cache import Manifest, context_dir, raw_path
from councilhound.impact.provenance import prov

log = logging.getLogger(__name__)

ACS_TABLES = {
    "B01003_001E": "population",
    "B19013_001E": "median_hh_income",
    "B25010_001E": "avg_hh_size",
    "B25010_003E": "avg_hh_size_renter",
    "B25044_001E": "hh_total_tenure",
    "B25044_003E": "hh_no_vehicle_owner",
    "B25044_010E": "hh_no_vehicle_renter",
    "B08301_001E": "commuters_total",
    "B08301_010E": "commute_transit",
    "B08301_019E": "commute_walk",
}
# TIGERweb "Tracts_Blocks" service; layer 1 = 2020+ block groups,
# layer 2 = 2020 census blocks (rows carry POP100 + centroid fields)
TIGERWEB_BG_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/1"
)
TIGERWEB_BLOCKS_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/2"
)
BLOCKS_BUFFER_M = 3_000  # match the walk-graph buffer so edge-of-city nodes get weights
LODES_BASE = "https://lehd.ces.census.gov/data/lodes/LODES8"
EXPECTED_CITY_POP = 24_500  # gate: within ±10% (brief §8)


def _require_key() -> str:
    """The Census API stopped honoring anonymous requests (it 302s to an HTML
    missing-key page, which is why we check up front instead of letting JSON
    parsing fail downstream)."""
    if not CENSUS_API_KEY:
        raise RuntimeError(
            "CENSUS_API_KEY is required for ACS loads — free instant signup at "
            "https://api.census.gov/data/key_signup.html, then export "
            "CENSUS_API_KEY=... (or add it to .env)"
        )
    return CENSUS_API_KEY


def _latest_acs_year() -> int:
    """Newest ACS 5-yr endpoint that answers; API vintages trail by ~1-2 yrs."""
    from datetime import date
    key = _require_key()
    for year in range(date.today().year - 1, date.today().year - 5, -1):
        try:
            resp = http.get(f"https://api.census.gov/data/{year}/acs/acs5", timeout=30,
                            params={"get": "B01003_001E", "for": "state:51", "key": key})
            resp.json()  # HTML error pages fail here even when status is 200
            return year
        except Exception:
            continue
    raise RuntimeError("no responsive ACS 5-yr endpoint found")


def load_blockgroups(ctx):
    """Block-group GeoDataFrame (EPSG:4326) for the jurisdiction county, with
    ACS columns per ACS_TABLES."""
    import geopandas as gpd
    import pandas as pd

    slug = ctx.cfg.slug
    manifest = Manifest(slug)
    existing = manifest.get("census_bg")
    if existing:
        year = existing["provenance"]["vintage"]
        path = context_dir(slug) / f"census_bg_{year}.parquet"
        if path.exists():
            return gpd.read_parquet(path)

    year = _latest_acs_year()
    path = context_dir(slug) / f"census_bg_{year}.parquet"
    state, county = ctx.cfg.fips.state, ctx.cfg.fips.county

    params = {
        "get": ",".join(ACS_TABLES),
        "for": "block group:*",
        "in": f"state:{state} county:{county}",
        "key": _require_key(),
    }
    acs_url = f"https://api.census.gov/data/{year}/acs/acs5"
    rows = http.get(acs_url, params=params, timeout=60).json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    for code, name in ACS_TABLES.items():
        df[name] = pd.to_numeric(df[code], errors="coerce")
        # ACS sentinel for suppressed/absent estimates
        df.loc[df[name] <= -666_666_666, name] = pd.NA
    df["geoid"] = df["state"] + df["county"] + df["tract"] + df["block group"]

    city_pop = df["population"].sum()
    if abs(city_pop - EXPECTED_CITY_POP) / EXPECTED_CITY_POP > 0.10:
        raise RuntimeError(
            f"ACS sanity gate failed: county {state}{county} population {city_pop:,.0f} "
            f"not within 10% of expected ~{EXPECTED_CITY_POP:,}"
        )

    from councilhound.impact.context.geohub import fetch_all_features
    fc = fetch_all_features(
        TIGERWEB_BG_URL,
        where=f"STATE='{state}' AND COUNTY='{county}'",
        out_fields="GEOID,STATE,COUNTY,TRACT,BLKGRP",
    )
    geo = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
    geo = geo.rename(columns={"GEOID": "geoid"})[["geoid", "geometry"]]
    merged = geo.merge(df[["geoid", *ACS_TABLES.values()]], on="geoid", how="left")
    if merged["population"].isna().all():
        raise RuntimeError("ACS/TIGERweb join produced no populated block groups")

    merged.to_parquet(path)
    manifest.record(
        "census_bg",
        prov(f"Census ACS 5-yr {year} (block group) + TIGERweb", acs_url, str(year),
             f"tables {sorted(set(t.split('_')[0] for t in ACS_TABLES))}").model_dump(),
        {"block_groups": len(merged), "city_population": int(city_pop)},
    )
    log.info("census_bg built: %d block groups, pop %s", len(merged), f"{city_pop:,.0f}")
    return merged


def load_blocks(ctx):
    """2020 census-block population points: {geoid, pop, lon, lat}.

    Blocks are the finest published population geography (~100x smaller than
    block groups), so a block's population can be treated as sitting at its
    centroid with error far below the 400 m radii the node weights use.
    Fetched by envelope (boundary + walk-graph buffer) so weights don't stop
    at the city line — unlike the ACS layer, which is county-scoped."""
    import geopandas as gpd
    import pandas as pd

    slug = ctx.cfg.slug
    path = context_dir(slug) / "blocks_2020.parquet"
    if path.exists():
        return pd.read_parquet(path)

    boundary = gpd.GeoSeries([ctx.boundary], crs="EPSG:4326")
    buffered = (boundary.to_crs(ctx.cfg.crs_projected)
                .buffer(BLOCKS_BUFFER_M * 3.28084).to_crs("EPSG:4326"))
    bbox = tuple(buffered.total_bounds)

    from councilhound.impact.context.geohub import fetch_all_attributes
    rows = fetch_all_attributes(
        TIGERWEB_BLOCKS_URL, out_fields="GEOID,POP100,CENTLON,CENTLAT", bbox=bbox)
    df = pd.DataFrame({
        "geoid": [r.get("GEOID") for r in rows],
        "pop": pd.to_numeric([r.get("POP100") for r in rows], errors="coerce"),
        "lon": pd.to_numeric([r.get("CENTLON") for r in rows], errors="coerce"),
        "lat": pd.to_numeric([r.get("CENTLAT") for r in rows], errors="coerce"),
    }).dropna()
    df = df[df["pop"] > 0].reset_index(drop=True)
    if not len(df):
        raise RuntimeError("TIGERweb block query returned no populated blocks")

    df.to_parquet(path)
    Manifest(slug).record(
        "blocks",
        prov("Census 2020 (PL 94-171) block population via TIGERweb",
             TIGERWEB_BLOCKS_URL, "2020",
             f"envelope query, boundary + {BLOCKS_BUFFER_M} m buffer").model_dump(),
        {"blocks": len(df), "population": int(df['pop'].sum())},
    )
    log.info("blocks built: %d populated blocks, pop %s", len(df), f"{df['pop'].sum():,.0f}")
    return df


def _latest_lodes_year(state: str = "va") -> int:
    for year in range(2023, 2018, -1):
        url = f"{LODES_BASE}/{state}/wac/{state}_wac_S000_JT00_{year}.csv.gz"
        try:
            resp = http.get_http_session().head(url, timeout=30)
            if resp.status_code == 200:
                return year
        except Exception:
            continue
    raise RuntimeError("no LODES WAC year found under LODES8")


def load_lodes(ctx):
    """Per-block-group workforce frame: workers_here (WAC S000 jobs) and
    resident_workers (RAC via OD main, residence side), aggregated from
    blocks (block GEOID[:12] = block group)."""
    import pandas as pd

    slug = ctx.cfg.slug
    manifest = Manifest(slug)
    existing = manifest.get("lodes")
    if existing:
        year = existing["provenance"]["vintage"]
        path = context_dir(slug) / f"lodes_{year}.parquet"
        if path.exists():
            return pd.read_parquet(path)

    year = _latest_lodes_year()
    path = context_dir(slug) / f"lodes_{year}.parquet"
    state_fips, county_fips = ctx.cfg.fips.state, ctx.cfg.fips.county
    county_prefix = state_fips + county_fips

    frames = {}
    for kind, fname, geocol in (
        ("wac", f"va_wac_S000_JT00_{year}.csv.gz", "w_geocode"),
        ("od", f"va_od_main_JT00_{year}.csv.gz", "h_geocode"),
    ):
        url = f"{LODES_BASE}/va/{kind}/{fname}"
        raw = raw_path("lodes", str(year), fname)
        if not raw.exists():
            http.download(url, str(raw))
        with gzip.open(raw, "rb") as fh:
            df = pd.read_csv(io.BytesIO(fh.read()), dtype={geocol: str})
        frames[kind] = df

    wac = frames["wac"]
    wac = wac[wac["w_geocode"].str.startswith(county_prefix)]
    wac_bg = (wac.assign(geoid=wac["w_geocode"].str[:12])
              .groupby("geoid")["C000"].sum().rename("workers_here"))

    od = frames["od"]
    od = od[od["h_geocode"].str.startswith(county_prefix)]
    od_bg = (od.assign(geoid=od["h_geocode"].str[:12])
             .groupby("geoid")["S000"].sum().rename("resident_workers"))

    out = pd.concat([wac_bg, od_bg], axis=1).fillna(0).reset_index()
    out.to_parquet(path)
    manifest.record(
        "lodes",
        prov(f"LEHD LODES8 {year} (WAC S000 + OD main, JT00)",
             f"{LODES_BASE}/va/", str(year)).model_dump(),
        {"block_groups": len(out), "workers_here": int(out['workers_here'].sum())},
    )
    return out
