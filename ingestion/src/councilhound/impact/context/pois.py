"""Merged POI layer: Overture places + Foursquare OS Places + OSM.

Three open sources, one deduplicated GeoDataFrame with a small internal
taxonomy the Huff model runs over. Raw category strings are kept for audit;
the mapping is deliberately keyword-based and inspectable rather than
model-based (brief §10: deterministic, explainable methods only).

Schema: {name, name_key, category_raw, taxonomy, source, geometry(4326)}
Dedup: same normalized name within 50 m (projected) -> one record, source
priority overture > fsq > osm (richer/cleaner categories first).

Release discovery: both Overture and FSQ publish public S3 buckets; the
latest release prefix is read from the bucket listing, never hard-coded.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from councilhound import http
from councilhound.impact.cache import Manifest, context_dir, raw_path
from councilhound.impact.provenance import prov

log = logging.getLogger(__name__)

OVERTURE_BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com"
# FSQ OS Places left S3 (bucket now holds only LICENSE/NOTICE, verified
# 2026-07); releases live on Hugging Face behind a terms gate (anonymous
# download 401s), so FSQ participates only when HF_TOKEN is set.
FSQ_HF_DATASET = "foursquare/fsq-os-places"
POI_BUFFER_MI = 2.0  # brief §4.3: city boundary + 2 mi

TAXONOMY = (
    "grocery", "restaurant_bar", "retail_comparison", "retail_convenience",
    "personal_services", "entertainment", "office", "civic", "other",
)

# ordered keyword rules over the lowercased raw category string; first hit wins
_RULES: list[tuple[str, str]] = [
    (r"supermarket|grocer|food.?store|farmers.?market", "grocery"),
    (r"restaurant|cafe|coffee|bar\b|pub\b|brewery|bakery|fast.?food|food.?court|"
     r"ice.?cream|dessert|deli|dining|pizzeria|steakhouse|taqueria|diner", "restaurant_bar"),
    (r"convenience|gas.?station|fuel|pharmacy|drug.?store|liquor|newsagent|"
     r"vape|tobacco", "retail_convenience"),
    (r"cloth|apparel|fashion|shoe|jewel|furniture|electronic|department.?store|"
     r"sporting|sports.?goods|book.?store|bookshop|toy|hobby|antique|thrift|"
     r"home.?goods|hardware|garden.?cent|appliance|mattress|bicycle.?shop|"
     r"gift|florist|pet.?store|mall\b|shopping", "retail_comparison"),
    (r"salon|barber|beauty|nail|spa\b|laundry|dry.?clean|tailor|bank\b|"
     r"credit.?union|atm\b|insurance|real.?estate.?agen|repair|dentist|"
     r"veterinar|optician|gym|fitness|yoga|massage|child.?care|tutoring", "personal_services"),
    (r"cinema|movie|theat|museum|gallery|bowling|arcade|casino|night.?club|"
     r"music.?venue|stadium|amusement|karaoke|billiard|entertainment", "entertainment"),
    (r"office|coworking|company|corporate|consult|lawyer|attorney|account|"
     r"engineer|architect|tech.?startup|it.?service|employment.?agen", "office"),
    (r"school|library|city.?hall|townhall|town.?hall|court.?house|post.?office|"
     r"church|temple|mosque|synagogue|worship|community.?cent|government|"
     r"university|college|police|fire.?station|hospital|clinic|park\b|"
     r"recreation|civic", "civic"),
]


def classify(raw: str | None) -> str:
    if not isinstance(raw, str) or not raw:  # None/NaN/empty -> unclassifiable
        return "other"
    text = raw.lower()
    for pattern, taxonomy in _RULES:
        if re.search(pattern, text):
            return taxonomy
    return "other"


def name_key(name: str | None) -> str:
    text = re.sub(r"['’]", "", (name or "").lower())  # Joe's == Joes
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _latest_s3_prefix(bucket_url: str, prefix: str) -> str:
    """Newest CommonPrefix under prefix/ from a public S3 bucket listing."""
    xml = http.get(f"{bucket_url}?list-type=2&prefix={prefix}&delimiter=/").text
    prefixes = re.findall(r"<Prefix>([^<]+)</Prefix>", xml)
    releases = sorted(p for p in prefixes if p != prefix)
    if not releases:
        raise RuntimeError(f"no releases found under {bucket_url}/{prefix}")
    return releases[-1].rstrip("/")


def _bbox(ctx) -> tuple[float, float, float, float]:
    import geopandas as gpd
    boundary = gpd.GeoSeries([ctx.boundary], crs="EPSG:4326")
    buffered = (boundary.to_crs(ctx.cfg.crs_projected)
                .buffer(POI_BUFFER_MI * 5280).to_crs("EPSG:4326"))
    return tuple(buffered.total_bounds)  # (minx, miny, maxx, maxy)


def _study_area(ctx):
    import geopandas as gpd
    boundary = gpd.GeoSeries([ctx.boundary], crs="EPSG:4326")
    return (boundary.to_crs(ctx.cfg.crs_projected)
            .buffer(POI_BUFFER_MI * 5280).to_crs("EPSG:4326").iloc[0])


def _duckdb_connect():
    """duckdb with extensions kept inside the data root (the default
    ~/.duckdb may be unwritable in sandboxed runs)."""
    import duckdb
    ext_dir = raw_path("duckdb_ext", "current")
    con = duckdb.connect()
    con.execute(f"SET extension_directory='{ext_dir}'")
    return con


def _fetch_overture(ctx) -> "object":
    import geopandas as gpd
    import pandas as pd

    release = _latest_s3_prefix(OVERTURE_BUCKET, "release/")  # e.g. release/2026-06-18.0
    version = release.split("/")[-1]
    parquet = raw_path("overture", version, "places.parquet")
    minx, miny, maxx, maxy = _bbox(ctx)
    if not parquet.exists():
        con = _duckdb_connect()
        con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; "
                    "SET s3_region='us-west-2';")
        con.execute(f"""
            COPY (
                SELECT names.primary AS name,
                       categories.primary AS category_raw,
                       ST_X(ST_Centroid(geometry)) AS lon,
                       ST_Y(ST_Centroid(geometry)) AS lat
                FROM read_parquet('s3://overturemaps-us-west-2/{release}/theme=places/type=place/*')
                WHERE bbox.xmin BETWEEN {minx} AND {maxx}
                  AND bbox.ymin BETWEEN {miny} AND {maxy}
            ) TO '{parquet}' (FORMAT PARQUET)
        """)
        con.close()
    df = pd.read_parquet(parquet)
    gdf = gpd.GeoDataFrame(
        df[["name", "category_raw"]],
        geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326",
    )
    gdf["source"] = "overture"
    return gdf, version


def _latest_fsq_release() -> str:
    """Newest release/dt=... directory from the Hugging Face datasets API."""
    entries = http.get(
        f"https://huggingface.co/api/datasets/{FSQ_HF_DATASET}/tree/main/release"
    ).json()
    releases = sorted(e["path"] for e in entries if e["path"].startswith("release/dt="))
    if not releases:
        raise RuntimeError(f"no releases visible for HF dataset {FSQ_HF_DATASET}")
    return releases[-1]


def _fetch_fsq(ctx) -> "object":
    import geopandas as gpd
    import pandas as pd

    release = _latest_fsq_release()  # e.g. release/dt=2026-07-09
    version = release.split("=")[-1]
    parquet = raw_path("fsq", version, "places.parquet")
    minx, miny, maxx, maxy = _bbox(ctx)
    if not parquet.exists():
        import os
        token = os.environ.get("HF_TOKEN", "")
        if not token:
            raise RuntimeError(
                "FSQ OS Places requires an HF token (the dataset is gated): accept the "
                "terms at https://huggingface.co/datasets/foursquare/fsq-os-places and "
                "set HF_TOKEN")
        con = _duckdb_connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"CREATE SECRET hf (TYPE HUGGINGFACE, TOKEN '{token}')")
        # ~100 files / ~11 GB per release; duckdb pulls only the selected
        # columns' pages and the bbox result is cached locally, but expect
        # the cold pull to take a few minutes.
        con.execute(f"""
            COPY (
                SELECT name,
                       array_to_string(fsq_category_labels, ' | ') AS category_raw,
                       longitude AS lon, latitude AS lat
                FROM read_parquet('hf://datasets/{FSQ_HF_DATASET}/{release}/places/parquet/*.parquet')
                WHERE longitude BETWEEN {minx} AND {maxx}
                  AND latitude BETWEEN {miny} AND {maxy}
                  AND date_closed IS NULL
            ) TO '{parquet}' (FORMAT PARQUET)
        """)
        con.close()
    df = pd.read_parquet(parquet)
    gdf = gpd.GeoDataFrame(
        df[["name", "category_raw"]],
        geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326",
    )
    gdf["source"] = "fsq"
    return gdf, version


def _fetch_osm(ctx) -> "object":
    import osmnx as ox

    area = _study_area(ctx)
    feats = ox.features_from_polygon(area, tags={"shop": True, "amenity": True, "office": True})
    feats = feats.reset_index()
    parts = []
    for tag in ("shop", "amenity", "office"):
        if tag in feats.columns:
            sub = feats[feats[tag].notna()].copy()
            sub["category_raw"] = tag + "=" + sub[tag].astype(str)
            parts.append(sub)
    import pandas as pd
    merged = pd.concat(parts) if parts else feats.iloc[0:0].assign(category_raw=None)
    merged = merged[merged.get("name").notna()] if "name" in merged.columns else merged.iloc[0:0]
    # centroid in a projected CRS (geographic-CRS centroids are approximate)
    merged["geometry"] = merged.set_geometry("geometry").geometry.to_crs("EPSG:3857").centroid.to_crs("EPSG:4326")
    out = merged[["name", "category_raw", "geometry"]].copy()
    out["source"] = "osm"
    return out.set_crs("EPSG:4326", allow_override=True), date.today().isoformat()


_SOURCE_PRIORITY = {"overture": 0, "fsq": 1, "osm": 2}
DEDUP_RADIUS_FT = 50 * 3.28084


def merge_sources(frames: list) -> "object":
    """Concatenate, then collapse same-name records within 50 m. Kept record
    = highest-priority source; its sources column lists every contributor."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from scipy.spatial import cKDTree

    all_pois = pd.concat(frames, ignore_index=True)
    all_pois = all_pois[all_pois["name"].notna() & (all_pois["name"].str.strip() != "")]
    all_pois["name_key"] = all_pois["name"].map(name_key)
    # some Overture/OSM records ship without a category; the name often
    # carries the class ("... Nail Salon") — same deterministic keyword
    # rules, category_raw stays null for audit
    all_pois["taxonomy"] = [
        classify(cat) if isinstance(cat, str) and cat else classify(name)
        for cat, name in zip(all_pois["category_raw"], all_pois["name"])
    ]
    all_pois["priority"] = all_pois["source"].map(_SOURCE_PRIORITY)
    all_pois = all_pois.sort_values("priority").reset_index(drop=True)

    coords = np.column_stack([all_pois.geometry.x, all_pois.geometry.y])
    tree = cKDTree(coords)
    pairs = tree.query_pairs(DEDUP_RADIUS_FT)

    # union-find over same-name near pairs
    parent = list(range(len(all_pois)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    names = all_pois["name_key"].to_numpy()
    for i, j in pairs:
        if names[i] and names[i] == names[j]:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)

    all_pois["group"] = [find(i) for i in range(len(all_pois))]
    grouped = all_pois.groupby("group")
    keep = all_pois.loc[grouped["priority"].idxmin()].copy()
    keep["sources"] = grouped["source"].agg(lambda s: ",".join(sorted(set(s)))).to_numpy()
    return gpd.GeoDataFrame(keep.drop(columns=["priority", "group"]),
                            geometry="geometry", crs=all_pois.crs)


def load_pois(ctx):
    import geopandas as gpd

    slug = ctx.cfg.slug
    path = context_dir(slug) / "pois.geoparquet"
    if path.exists():
        return gpd.read_parquet(path)

    crs = ctx.cfg.crs_projected
    sources_prov = []
    frames = []
    for fetch, label, url, optional in (
        (_fetch_overture, "Overture Maps places", "https://overturemaps.org", False),
        (_fetch_fsq, "Foursquare OS Places",
         "https://opensource.foursquare.com/os-places/", True),
        (_fetch_osm, "OpenStreetMap POIs (shop/amenity/office)",
         "https://www.openstreetmap.org", False),
    ):
        try:
            gdf, version = fetch(ctx)
        except Exception as exc:
            if not optional:
                raise
            log.warning("%s unavailable (%s) — merging without it", label, exc)
            sources_prov.append(prov(f"{label} (SKIPPED)", url, "n/a", str(exc)).model_dump())
            continue
        log.info("%s: %d records", label, len(gdf))
        frames.append(gdf.to_crs(crs))
        sources_prov.append(prov(label, url, version).model_dump())

    merged = merge_sources(frames)

    # clip to study area + quality gate on raw-category coverage
    area = gpd.GeoSeries([_study_area(ctx)], crs="EPSG:4326").to_crs(crs).iloc[0]
    merged = merged[merged.within(area)]
    # gate on records with NO classification signal at all (no raw category
    # and a name our keyword rules can't place)
    unclassified = (merged["category_raw"].isna() & (merged["taxonomy"] == "other")).mean()
    null_rate = float(merged["category_raw"].isna().mean())
    if unclassified >= 0.05:
        raise RuntimeError(
            f"POI quality gate failed: {unclassified:.1%} records unclassifiable (>=5%)")

    merged = merged.to_crs("EPSG:4326")
    merged.to_parquet(path)
    Manifest(slug).record(
        "pois", sources_prov,
        {"records": len(merged), "null_category_rate": round(float(null_rate), 4),
         "by_taxonomy": merged["taxonomy"].value_counts().to_dict()},
    )
    return merged
