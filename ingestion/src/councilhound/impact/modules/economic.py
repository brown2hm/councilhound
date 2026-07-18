"""Economic module: new demand, Huff retail capture, foot-traffic index,
displacement ledger (brief §6.2).

`run(spec, ctx, prior=None) -> (ModuleResult, {label: geojson})`.

Every quantity flows through provenance.Interval so the Assumption bounds
land on the MetricValues; the Huff invariant (cluster captures sum to the
category spend) is pinned by unit tests. The foot-traffic output is a
RELATIVE index (sampled weighted betweenness), labeled as such — it becomes
counts only if calibration counts are ever configured.
"""
from __future__ import annotations

import logging

from councilhound.impact.provenance import Interval, metric, prov
from councilhound.impact.schemas import Assumption, MetricValue, ModuleResult
from councilhound.impact.modules import ces_shares, huff

log = logging.getLogger(__name__)

WALK_SPEED_KMH = 4.8
DBSCAN_EPS_M = 150.0
DBSCAN_MIN_SAMPLES = 3
BETWEENNESS_PAIRS = 2000
BETWEENNESS_SEED = 20260718
FOOT_TRAFFIC_RADIUS_FT = 3_280.0 * 3  # ~3 km study subgraph around the site
TOP_EDGES_IN_LAYER = 300
M_TO_FT = 3.28084

# Huff parameters (brief §6.2.2)
ALPHA = 1.0
BETA_DRIVE = 0.15

RETAIL_CLASSES = ("grocery", "restaurant_bar", "retail_comparison",
                  "retail_convenience", "personal_services", "entertainment")

# ground-floor retail mix assumed for the project's own space
OWN_RETAIL_MIX = {"restaurant_bar": 0.5, "retail_comparison": 0.15,
                  "retail_convenience": 0.15, "personal_services": 0.2}


def _assumptions(ctx) -> dict[str, Assumption]:
    ces = ces_shares.provenance()
    return {a.key: a for a in [
        Assumption(key="occupancy_rate", value=0.95, low=0.90, high=0.97,
                   basis="stabilized multifamily occupancy, industry norm",
                   rationale="share of proposed units occupied at stabilization"),
        Assumption(key="avg_hh_size_renter", value=0.0, low=0.0, high=0.0,  # filled from ACS
                   basis="ACS B25010 (renter-occupied), city block groups",
                   rationale="persons per new household; ±0.3 sensitivity"),
        Assumption(key="income_premium_new_construction", value=1.125, low=1.0, high=1.25,
                   basis="documented openly per the methodology brief",
                   rationale="new-construction multifamily rents draw higher-income "
                             "households than the area median"),
        Assumption(key="ces_scale", value=1.0, low=0.85, high=1.15,
                   basis=ces,
                   rationale="CES line items are national averages; ±15% covers "
                             "regional and vintage drift"),
        Assumption(key="beta_walk", value=0.10, low=0.07, high=0.15,
                   basis="Huff impedance decay per methodology brief",
                   rationale="per-minute walk-time decay in destination choice"),
        Assumption(key="walk_share_neighborhood", value=0.60, low=0.40, high=0.80,
                   basis="methodology brief mode-split default",
                   rationale="walk share for restaurants/convenience/services at a "
                             "walkable mixed-use site"),
        Assumption(key="walk_share_comparison", value=0.10, low=0.0, high=0.30,
                   basis="methodology brief mode-split default",
                   rationale="comparison-goods trips are predominantly by car"),
        Assumption(key="walk_share_grocery_entertainment", value=0.30, low=0.10, high=0.50,
                   basis="interpolated between the brief's neighborhood and comparison splits",
                   rationale="grocery/entertainment trips mix walk and drive"),
        Assumption(key="sqft_per_office_job", value=300.0, low=200.0, high=450.0,
                   basis="office space-per-worker planning standard",
                   rationale="existing commercial sqft -> displaced jobs"),
        Assumption(key="sqft_per_retail_job", value=500.0, low=400.0, high=700.0,
                   basis="retail space-per-worker planning standard",
                   rationale="proposed retail sqft -> on-site jobs"),
        Assumption(key="own_retail_sqft_per_equiv_poi", value=2000.0, low=1500.0, high=3000.0,
                   basis="typical inline retail suite size",
                   rationale="converts the project's retail sqft into POI-count-"
                             "equivalent attractiveness for the Huff run"),
    ]}


def _walk_share_for(category: str, a: dict[str, Assumption]) -> Assumption:
    if category in ("restaurant_bar", "retail_convenience", "personal_services"):
        return a["walk_share_neighborhood"]
    if category == "retail_comparison":
        return a["walk_share_comparison"]
    return a["walk_share_grocery_entertainment"]


def _site_point(spec, ctx):
    from shapely.geometry import shape
    if spec.geometry is None:
        raise ValueError("spec has no site geometry — economic module needs a resolved site")
    return shape(spec.geometry).centroid  # EPSG:4326


def _city_income_and_hh_size(ctx):
    bg = ctx.census_bg
    populated = bg[bg["population"].fillna(0) > 0]
    weights = populated["population"]
    income = float((populated["median_hh_income"] * weights).sum() / weights.sum())
    hh_renter = populated["avg_hh_size_renter"].dropna()
    hh_weights = populated.loc[hh_renter.index, "population"]
    hh_size = float((hh_renter * hh_weights).sum() / hh_weights.sum())
    year = None
    entry = ctx.manifest.get("census_bg")
    if entry:
        year = entry["provenance"].get("vintage")
    return income, hh_size, year or "latest"


def _clusters(ctx, site_pt_projected, own_retail_equiv: dict[str, float]):
    """DBSCAN clusters over retail-class POIs (projected CRS). Returns a list
    of dicts: {name, x, y, counts: {class: n}, own: bool}."""
    import numpy as np
    from sklearn.cluster import DBSCAN

    pois = ctx.pois.to_crs(ctx.cfg.crs_projected)
    retail = pois[pois["taxonomy"].isin(RETAIL_CLASSES)].copy()
    coords = np.column_stack([retail.geometry.x, retail.geometry.y])
    labels = DBSCAN(eps=DBSCAN_EPS_M * M_TO_FT, min_samples=DBSCAN_MIN_SAMPLES).fit_predict(coords)
    retail["cluster"] = labels

    clusters = []
    for label, group in retail[retail["cluster"] >= 0].groupby("cluster"):
        cx, cy = float(group.geometry.x.mean()), float(group.geometry.y.mean())
        # deterministic name: the member POI nearest the centroid
        d2 = (group.geometry.x - cx) ** 2 + (group.geometry.y - cy) ** 2
        anchor = group.loc[d2.idxmin(), "name"]
        clusters.append({
            "name": f"{anchor} area",
            "x": cx, "y": cy,
            "counts": group["taxonomy"].value_counts().to_dict(),
            "own": False,
        })
    clusters.append({
        "name": "Project ground-floor retail (this project)",
        "x": float(site_pt_projected.x), "y": float(site_pt_projected.y),
        "counts": own_retail_equiv,
        "own": True,
    })
    return clusters


def _travel_times(ctx, site_pt_4326, clusters):
    """(walk_min, drive_min) arrays site -> each cluster centroid via the
    cached graphs; unreachable -> inf."""
    import networkx as nx
    import numpy as np
    import osmnx as ox
    import pyproj

    to4326 = pyproj.Transformer.from_crs(ctx.cfg.crs_projected, "EPSG:4326", always_xy=True)
    lons, lats = zip(*[to4326.transform(c["x"], c["y"]) for c in clusters])

    out = []
    for graph in (ctx.walk_graph, ctx.drive_graph):
        origin = ox.distance.nearest_nodes(graph, site_pt_4326.x, site_pt_4326.y)
        targets = ox.distance.nearest_nodes(graph, list(lons), list(lats))
        times = nx.single_source_dijkstra_path_length(graph, origin, weight="travel_min")
        out.append(np.array([times.get(t, np.inf) for t in targets]))
    return out[0], out[1]


def _demand(spec, ctx, a: dict[str, Assumption]):
    """Households, residents, income, per-category spend — all Intervals."""
    units = spec.proposed.units
    income_base, hh_size, acs_year = _city_income_and_hh_size(ctx)
    a["avg_hh_size_renter"] = Assumption(
        key="avg_hh_size_renter", value=round(hh_size, 2),
        low=round(max(hh_size - 0.3, 0.5), 2), high=round(hh_size + 0.3, 2),
        basis=prov(f"Census ACS 5-yr {acs_year}, table B25010 (renter-occupied)",
                   "https://api.census.gov", str(acs_year)),
        rationale="persons per new household; ±0.3 sensitivity")

    households = Interval.point(units) * Interval.from_assumption(a["occupancy_rate"])
    residents = households * Interval.from_assumption(a["avg_hh_size_renter"])
    hh_income = (Interval.point(income_base)
                 * Interval.from_assumption(a["income_premium_new_construction"]))
    aggregate_income = households * hh_income

    spend = {}
    for category in RETAIL_CLASSES:
        # CES line item as a share of CES pre-tax income, applied to the
        # aggregate income of the new households
        share = ces_shares.CATEGORY_SPEND[category][0] / ces_shares.CES_AVG_PRETAX_INCOME
        spend[category] = aggregate_income * share * Interval.from_assumption(a["ces_scale"])
    return households, residents, hh_income, aggregate_income, spend, income_base


def _foot_traffic(ctx, spec, new_residents: float):
    """Sampled weighted betweenness, baseline vs. site-loaded. Returns
    (delta_by_edge {(u,v): pct}, nearest_commercial_delta_pct, edges_gdf)."""
    import networkx as nx
    import numpy as np
    import osmnx as ox

    graph = ctx.walk_graph
    weights = ctx.node_weights
    site = _site_point(spec, ctx)
    site_node = ox.distance.nearest_nodes(graph, site.x, site.y)

    # study subgraph: nodes within the euclidean radius of the site (projected)
    nodes_gdf = ox.convert.graph_to_gdfs(graph, edges=False)[["geometry"]].to_crs(
        ctx.cfg.crs_projected)
    tx = ctx.transformer()
    sx, sy = tx.transform(site.x, site.y)
    near = nodes_gdf[(nodes_gdf.geometry.x - sx) ** 2
                     + (nodes_gdf.geometry.y - sy) ** 2 <= FOOT_TRAFFIC_RADIUS_FT ** 2]
    sub = graph.subgraph(near.index).copy()
    if site_node not in sub:
        raise ValueError("site node fell outside the foot-traffic study subgraph")

    w = weights.reindex(near.index).fillna(0)
    pop = w["pop_400m"].to_numpy(dtype=float)
    poi_cols = [c for c in w.columns if c.startswith("poi_")]
    poi = w[poi_cols].sum(axis=1).to_numpy(dtype=float)
    nodes = list(near.index)
    index_of = {n: i for i, n in enumerate(nodes)}

    def sample_counts(extra_pop_at_site: float):
        rng = np.random.default_rng(BETWEENNESS_SEED)
        p = pop.copy()
        p[index_of[site_node]] += extra_pop_at_site
        if p.sum() == 0 or poi.sum() == 0:
            raise ValueError("no population or POI weight in study area")
        origins = rng.choice(len(nodes), size=BETWEENNESS_PAIRS, p=p / p.sum())
        dests = rng.choice(len(nodes), size=BETWEENNESS_PAIRS, p=poi / poi.sum())
        counts: dict[tuple, float] = {}
        by_origin: dict[int, list[int]] = {}
        for o, d in zip(origins, dests):
            by_origin.setdefault(int(o), []).append(int(d))
        for o, ds in by_origin.items():
            try:
                paths = nx.single_source_dijkstra_path(sub, nodes[o], weight="travel_min")
            except Exception:
                continue
            for d in ds:
                path = paths.get(nodes[d])
                if not path:
                    continue
                for u, v in zip(path[:-1], path[1:]):
                    counts[(u, v)] = counts.get((u, v), 0) + 1
        return counts

    base = sample_counts(0.0)
    loaded = sample_counts(new_residents)
    all_edges = set(base) | set(loaded)
    delta = {}
    for edge in all_edges:
        b, l = base.get(edge, 0), loaded.get(edge, 0)
        if b + l < 5:  # noise floor for the sampled index
            continue
        delta[edge] = 100.0 * (l - b) / b if b else 100.0

    # nearest commercial segments: edges whose endpoints carry POI weight,
    # ranked by distance to the site
    commercial = []
    for (u, v), pct in delta.items():
        if poi[index_of[u]] + poi[index_of[v]] > 0:
            ux, uy = nodes_gdf.loc[u].geometry.x, nodes_gdf.loc[u].geometry.y
            dist = ((ux - sx) ** 2 + (uy - sy) ** 2) ** 0.5
            commercial.append((dist, pct, (u, v)))
    commercial.sort()
    nearest10 = [pct for _, pct, _ in commercial[:10]]
    nearest_delta = float(np.mean(nearest10)) if nearest10 else 0.0
    return delta, nearest_delta, sub


def _foot_traffic_layer(ctx, delta: dict, sub) -> dict:
    """Top-N |% change| edges as a GeoJSON FeatureCollection (EPSG:4326)."""
    import osmnx as ox

    edges_gdf = ox.convert.graph_to_gdfs(sub, nodes=False).reset_index()
    lookup = {(row.u, row.v): row.geometry for row in edges_gdf.itertuples()}
    ranked = sorted(delta.items(), key=lambda kv: abs(kv[1]), reverse=True)[:TOP_EDGES_IN_LAYER]
    features = []
    for (u, v), pct in ranked:
        geom = lookup.get((u, v)) or lookup.get((v, u))
        if geom is None:
            continue
        geom = geom.simplify(0.00005)
        coords = [[round(x, 6), round(y, 6)] for x, y in geom.coords]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"delta_pct": round(pct, 1)},
        })
    return {"type": "FeatureCollection", "features": features}


def run(spec, ctx, prior=None):
    a = _assumptions(ctx)
    notes = [
        "Huff capture and the foot-traffic index are screening estimates, not "
        "predictions: they rank where new spending and walking activity are "
        "likely to land, with sensitivity bounds, and should be read as "
        "relative magnitudes.",
    ]

    if spec.proposed.units is None:
        return (ModuleResult(
            module="economic", metrics=[],
            narrative_notes=["Not computed: the proposed unit count could not be "
                            "extracted from the project documents."],
            assumptions=[],
        ), {})

    households, residents, hh_income, aggregate_income, spend, income_base = _demand(spec, ctx, a)

    site = _site_point(spec, ctx)
    tx = ctx.transformer()
    sx, sy = tx.transform(site.x, site.y)
    from shapely.geometry import Point
    site_projected = Point(sx, sy)

    own_equiv_total = (spec.proposed.retail_sqft or 0) / a["own_retail_sqft_per_equiv_poi"].value
    own_retail_equiv = {cls: own_equiv_total * share for cls, share in OWN_RETAIL_MIX.items()}
    clusters = _clusters(ctx, site_projected, own_retail_equiv)
    walk_min, drive_min = _travel_times(ctx, site, clusters)

    import numpy as np
    capture_by_cluster = np.zeros(len(clusters))
    capture_low = np.zeros(len(clusters))
    capture_high = np.zeros(len(clusters))
    for category in RETAIL_CLASSES:
        attractiveness = np.array([c["counts"].get(category, 0.0) for c in clusters])
        ws = _walk_share_for(category, a)
        for target, beta, ws_value, spend_value in (
            (capture_by_cluster, a["beta_walk"].value, ws.value, spend[category].value),
            (capture_low, a["beta_walk"].high, ws.low, spend[category].low),
            (capture_high, a["beta_walk"].low, ws.high, spend[category].high),
        ):
            p = huff.blended_probabilities(attractiveness, walk_min, drive_min,
                                           walk_share=ws_value, alpha=ALPHA,
                                           beta_walk=beta, beta_drive=BETA_DRIVE)
            target += huff.allocate_spend(spend_value, p)

    order = np.argsort(-capture_by_cluster)
    metrics: list[MetricValue] = []
    ces_prov = ces_shares.provenance()
    acs_prov = a["avg_hh_size_renter"].basis
    huff_method = ("Huff model: P_ij = A_j^a * exp(-b*t_ij) / sum_k, blended "
                   "walk/drive impedance, CES category spend")

    metrics.append(metric("New households", households, "households",
                          [acs_prov] if not isinstance(acs_prov, str) else [],
                          [a["occupancy_rate"]],
                          "proposed units x occupancy_rate", headline=True))
    metrics.append(metric("New residents", residents, "residents",
                          [acs_prov] if not isinstance(acs_prov, str) else [],
                          [a["occupancy_rate"], a["avg_hh_size_renter"]],
                          "households x avg household size (ACS B25010 renter)",
                          headline=True))
    metrics.append(metric(
        "Aggregate household income", aggregate_income, "$/yr",
        [ces_prov], [a["income_premium_new_construction"], a["occupancy_rate"]],
        f"households x city median income (${income_base:,.0f}) x new-construction premium"))

    for category in RETAIL_CLASSES:
        metrics.append(metric(
            f"New annual spending: {category}", spend[category], "$/yr",
            [ces_prov], [a["ces_scale"], a["income_premium_new_construction"]],
            "aggregate income x CES category share"))

    top = [i for i in order if not clusters[i]["own"]][:5]
    for i in top:
        metrics.append(MetricValue(
            name=f"Annual capture: {clusters[i]['name']}",
            value=float(capture_by_cluster[i]), unit="$/yr",
            low=float(capture_low[i]), high=float(capture_high[i]),
            provenance=[ces_prov], method=huff_method,
            assumptions=["beta_walk", "walk_share_neighborhood", "ces_scale"],
        ))
    # in-city capture shares — the fiscal module's meals/sales-tax link:
    # only spending that lands inside city limits generates city tax revenue
    from shapely.geometry import Point as _Point
    from shapely.ops import transform as _shp_transform
    boundary_projected = _shp_transform(tx.transform, ctx.boundary)
    in_city = np.array([boundary_projected.contains(_Point(c["x"], c["y"])) for c in clusters])
    for category, label in (("restaurant_bar", "food_away"),
                            (None, "all_retail")):
        share_num = np.zeros(3)  # value, low, high accumulators
        share_den = np.zeros(3)
        cats = [category] if category else list(RETAIL_CLASSES)
        for cat in cats:
            attractiveness = np.array([c["counts"].get(cat, 0.0) for c in clusters])
            ws = _walk_share_for(cat, a)
            for slot, (beta, ws_value) in enumerate((
                    (a["beta_walk"].value, ws.value),
                    (a["beta_walk"].high, ws.low),
                    (a["beta_walk"].low, ws.high))):
                p = huff.blended_probabilities(attractiveness, walk_min, drive_min,
                                               walk_share=ws_value, alpha=ALPHA,
                                               beta_walk=beta, beta_drive=BETA_DRIVE)
                share_num[slot] += p[in_city].sum()
                share_den[slot] += p.sum()
        shares = np.divide(share_num, share_den, out=np.zeros(3), where=share_den > 0)
        lo, hi = float(min(shares)), float(max(shares))
        metrics.append(MetricValue(
            name=f"In-city capture share: {label}",
            value=float(shares[0]), unit="fraction", low=lo, high=hi,
            provenance=[ces_prov], method=huff_method + "; share of capture landing "
            "at clusters inside the city boundary",
            assumptions=["beta_walk", "walk_share_neighborhood"],
        ))

    own_idx = next(i for i, c in enumerate(clusters) if c["own"])
    metrics.append(MetricValue(
        name="Annual capture: project's own ground-floor retail",
        value=float(capture_by_cluster[own_idx]), unit="$/yr",
        low=float(capture_low[own_idx]), high=float(capture_high[own_idx]),
        provenance=[ces_prov], method=huff_method + "; own retail competes as a destination",
        assumptions=["own_retail_sqft_per_equiv_poi", "beta_walk"], headline=True,
    ))
    notes.append(
        "The project's own retail is included as a competing destination; its "
        "capture estimates how much of the residents' spending the ground floor "
        "itself can hold on to.")

    # displacement ledger
    existing_sqft = spec.existing.sqft or 0.0
    jobs_removed = (Interval.point(existing_sqft)
                    / Interval.from_assumption(a["sqft_per_office_job"]))
    retail_sqft = spec.proposed.retail_sqft or 0.0
    jobs_added = (Interval.point(retail_sqft)
                  / Interval.from_assumption(a["sqft_per_retail_job"]))
    net_jobs = jobs_added - jobs_removed
    site_prov = prov("Project documents (extracted spec)", spec.source_url, "current")
    metrics.append(metric("On-site jobs removed (existing space)", jobs_removed, "jobs",
                          [site_prov], [a["sqft_per_office_job"]],
                          "existing commercial sqft / sqft-per-office-job"))
    metrics.append(metric("On-site retail jobs added", jobs_added, "jobs",
                          [site_prov], [a["sqft_per_retail_job"]],
                          "proposed retail sqft / sqft-per-retail-job"))
    metrics.append(metric("Net on-site job change", net_jobs, "jobs",
                          [site_prov], [a["sqft_per_office_job"], a["sqft_per_retail_job"]],
                          "retail jobs added - existing jobs removed", headline=True))
    if spec.existing.use:
        notes.append(f"Displaced use: {spec.existing.use}. Any spending that "
                     "originated on-site today is assumed negligible relative to "
                     "the new residential demand.")

    # foot-traffic index
    delta, nearest_delta, sub = _foot_traffic(ctx, spec, residents.value)
    osm_prov = prov("OpenStreetMap walk network + ACS population + merged POI layer",
                    "https://www.openstreetmap.org", "current",
                    f"sampled weighted betweenness, k={BETWEENNESS_PAIRS}, seeded")
    metrics.append(MetricValue(
        name="Foot-traffic index change, 10 nearest commercial street segments",
        value=round(nearest_delta, 1), unit="% (relative index)",
        low=None, high=None, provenance=[osm_prov],
        method=("weighted betweenness (population-weighted origins x POI-weighted "
                "destinations), baseline vs. site loaded with new residents"),
        assumptions=["occupancy_rate", "avg_hh_size_renter"], headline=True,
    ))
    if ctx.cfg.calibration_counts is None:
        notes.append("Foot-traffic figures are a relative index (no pedestrian "
                     "calibration counts are configured), not people-per-day.")

    layers = {
        "site": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": spec.geometry, "properties": {"role": "site"}}]},
        "capture_clusters": _cluster_layer(ctx, clusters, capture_by_cluster),
        "foot_traffic_delta": _foot_traffic_layer(ctx, delta, sub),
    }
    result = ModuleResult(
        module="economic", metrics=metrics,
        map_layer_labels=list(layers),
        narrative_notes=notes,
        assumptions=list(a.values()),
    )
    return result, layers


def _cluster_layer(ctx, clusters, capture) -> dict:
    import pyproj
    to4326 = pyproj.Transformer.from_crs(ctx.cfg.crs_projected, "EPSG:4326", always_xy=True)
    features = []
    for c, dollars in zip(clusters, capture):
        if dollars <= 0:
            continue
        lon, lat = to4326.transform(c["x"], c["y"])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {"name": c["name"], "annual_capture_usd": round(float(dollars)),
                           "own": c["own"]},
        })
    return {"type": "FeatureCollection", "features": features}
