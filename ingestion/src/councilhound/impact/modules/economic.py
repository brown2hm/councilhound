"""Economic module: new demand, Huff retail capture, foot-traffic flows,
displacement ledger (brief §6.2).

`run(spec, ctx, prior=None) -> (ModuleResult, {label: geojson})`.

Granularity model:
- The Huff run treats every retail POI as an individual destination (single-
  source Dijkstra from the site makes per-POI travel times free); DBSCAN
  clusters exist only as a REPORTING rollup for the "top destinations"
  metrics, so capture is spatially resolved to business locations.
- Foot traffic is computed exactly, not sampled: the change caused by the
  project is precisely the walk trips its residents generate, so those trips
  are allocated over POI-weighted destinations with distance decay and routed
  along shortest paths, giving deterministic per-edge flows. A seeded sampled
  betweenness baseline provides the "% vs. today" denominator only.
- Demand income uses the site's own census tract (brief §6.2.1), not the
  citywide mean.

Every quantity flows through provenance.Interval so the Assumption bounds
land on the MetricValues; the Huff invariant (captures sum to the category
spend) is pinned by unit tests.
"""
from __future__ import annotations

import logging
import math

from councilhound.impact.provenance import Interval, metric, prov
from councilhound.impact.schemas import Assumption, MetricValue, ModuleResult
from councilhound.impact.modules import ces_shares, huff

log = logging.getLogger(__name__)

WALK_SPEED_KMH = 4.8
DBSCAN_EPS_M = 150.0
DBSCAN_MIN_SAMPLES = 3
BASELINE_PAIRS = 2000
BASELINE_SEED = 20260718
BASELINE_MIN_COUNT = 5  # sampled-baseline noise floor for % comparisons
FOOT_TRAFFIC_RADIUS_FT = 3_280.0 * 3  # ~3 km study subgraph around the site
TOP_EDGES_IN_LAYER = 300
MIN_POINT_CAPTURE_USD = 200  # trim the long tail out of the heat layer
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
        Assumption(key="walk_trips_per_resident_day", value=2.0, low=1.0, high=3.0,
                   basis="NHTS 2022 daily walking trip rates for residents of "
                         "walkable mixed-use areas",
                   rationale="scales new residents into daily walk trips for the "
                             "foot-traffic flow allocation"),
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


def _acs_vintage(ctx) -> str:
    entry = ctx.manifest.get("census_bg")
    return (entry["provenance"].get("vintage") if entry else None) or "latest"


def _hh_size(ctx) -> float:
    bg = ctx.census_bg
    populated = bg[bg["population"].fillna(0) > 0]
    hh_renter = populated["avg_hh_size_renter"].dropna()
    weights = populated.loc[hh_renter.index, "population"]
    return float((hh_renter * weights).sum() / weights.sum())


def _site_income(ctx, site_pt_4326) -> tuple[float, str]:
    """Median household income for the site's census TRACT (population-
    weighted over the tract's block groups, brief §6.2.1); falls back to the
    citywide mean when the tract's medians are suppressed."""
    bg = ctx.census_bg
    populated = bg[bg["population"].fillna(0) > 0]

    def weighted_income(frame):
        rows = frame[frame["median_hh_income"].notna() & (frame["population"] > 0)]
        if not len(rows):
            return None
        return float((rows["median_hh_income"] * rows["population"]).sum()
                     / rows["population"].sum())

    hit = bg[bg.contains(site_pt_4326)]
    if len(hit):
        tract = hit.iloc[0]["geoid"][:11]
        tract_income = weighted_income(populated[populated["geoid"].str[:11] == tract])
        if tract_income is not None:
            return tract_income, f"site tract {tract}"
    citywide = weighted_income(populated)
    if citywide is None:
        raise ValueError("no usable median income in the census layer")
    return citywide, "citywide (site tract suppressed)"


def _demand(spec, ctx, a: dict[str, Assumption], site_pt_4326):
    """Households, residents, income, per-category spend — all Intervals."""
    units = spec.proposed.units
    acs_year = _acs_vintage(ctx)
    hh_size = _hh_size(ctx)
    income_base, income_scope = _site_income(ctx, site_pt_4326)
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
    return households, residents, aggregate_income, spend, income_base, income_scope


# --- destinations: every retail POI, individually ---------------------------

def _destinations(ctx, site_pt_4326, site_projected, own_retail_equiv):
    """Per-POI destination table + cluster rollup metadata.

    Returns dict with parallel arrays over destinations (all retail POIs plus
    the project's own retail as the last entry): taxonomy/name arrays,
    walk/drive minutes from the site, in_city mask, lon/lat, cluster label
    (-1 = DBSCAN noise, own = -2), and {label: meta} for named reporting."""
    import networkx as nx
    import numpy as np
    import osmnx as ox
    import pyproj
    from shapely.geometry import Point
    from shapely.ops import transform as shp_transform
    from sklearn.cluster import DBSCAN

    crs = ctx.cfg.crs_projected
    pois = ctx.pois
    retail = pois[pois["taxonomy"].isin(RETAIL_CLASSES)].reset_index(drop=True)
    projected = retail.to_crs(crs)

    coords = np.column_stack([projected.geometry.x, projected.geometry.y])
    labels = DBSCAN(eps=DBSCAN_EPS_M * M_TO_FT,
                    min_samples=DBSCAN_MIN_SAMPLES).fit_predict(coords)

    cluster_meta: dict[int, dict] = {}
    for label in set(labels):
        if label < 0:
            continue
        members = np.where(labels == label)[0]
        cx, cy = float(coords[members, 0].mean()), float(coords[members, 1].mean())
        d2 = ((coords[members, 0] - cx) ** 2 + (coords[members, 1] - cy) ** 2)
        anchor = retail.iloc[members[int(np.argmin(d2))]]["name"]
        cluster_meta[int(label)] = {"name": f"{anchor} area", "x": cx, "y": cy,
                                    "poi_count": int(len(members)), "own": False}
    cluster_meta[-2] = {"name": "Project ground-floor retail (this project)",
                        "x": float(site_projected.x), "y": float(site_projected.y),
                        "poi_count": 0, "own": True}

    # travel times: one Dijkstra per graph gives every POI's time via its
    # nearest network node
    lons = retail.geometry.x.to_numpy()
    lats = retail.geometry.y.to_numpy()
    times = []
    walk_nodes = None
    walk_origin = None
    for graph in (ctx.walk_graph, ctx.drive_graph):
        origin = ox.distance.nearest_nodes(graph, site_pt_4326.x, site_pt_4326.y)
        nearest = ox.distance.nearest_nodes(graph, list(lons), list(lats))
        dist = nx.single_source_dijkstra_path_length(graph, origin, weight="travel_min")
        times.append(np.array([dist.get(n, np.inf) for n in nearest]))
        if walk_nodes is None:  # first graph is the walk graph
            walk_nodes, walk_origin = list(nearest), origin
    walk_min, drive_min = times

    tx = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    boundary_projected = shp_transform(tx.transform, ctx.boundary)
    in_city = np.array([boundary_projected.contains(Point(x, y)) for x, y in coords])

    # append the project's own retail as the final destination (t = 0: it is
    # the origin), attractiveness supplied per category by own_retail_equiv
    n = len(retail)
    return {
        "n": n + 1,
        "taxonomy": np.append(retail["taxonomy"].to_numpy(), "__own__"),
        "walk_min": np.append(walk_min, 0.0),
        "drive_min": np.append(drive_min, 0.0),
        "in_city": np.append(in_city, True),  # the site is inside the city
        "lon": np.append(lons, site_pt_4326.x),
        "lat": np.append(lats, site_pt_4326.y),
        "cluster": np.append(labels, -2),
        "cluster_meta": cluster_meta,
        "own_retail_equiv": own_retail_equiv,
        # walk-graph node per retail POI (no entry for the own-retail
        # destination — its dollars stay on-site) + the site's walk node
        "walk_nodes": walk_nodes,
        "walk_origin": walk_origin,
    }


def _capture(dest, spend, a):
    """Per-destination capture and walk-arriving dollars (value/low/high),
    plus in-city share accumulators. Probabilities per category sum to 1, so
    total capture = total spend and total walk dollars = sum(spend x walk
    share) — both invariants are pinned by unit tests."""
    import numpy as np

    n = dest["n"]
    capture = {slot: np.zeros(n) for slot in range(3)}
    walk_dollars = {slot: np.zeros(n) for slot in range(3)}
    share_food = np.zeros((3, 2))    # [slot][num, den] for food_away
    share_all = np.zeros((3, 2))

    for category in RETAIL_CLASSES:
        attractiveness = (dest["taxonomy"] == category).astype(float)
        attractiveness[-1] = dest["own_retail_equiv"].get(category, 0.0)
        ws = _walk_share_for(category, a)
        for slot, (beta, ws_value, spend_value) in enumerate((
            (a["beta_walk"].value, ws.value, spend[category].value),
            (a["beta_walk"].high, ws.low, spend[category].low),
            (a["beta_walk"].low, ws.high, spend[category].high),
        )):
            p = huff.blended_probabilities(attractiveness, dest["walk_min"],
                                           dest["drive_min"], walk_share=ws_value,
                                           alpha=ALPHA, beta_walk=beta,
                                           beta_drive=BETA_DRIVE)
            capture[slot] += huff.allocate_spend(spend_value, p)
            # walk-mode component only: the dollars that arrive on foot
            p_walk = huff.huff_probabilities(attractiveness, dest["walk_min"],
                                             alpha=ALPHA, beta=beta)
            walk_dollars[slot] += huff.allocate_spend(spend_value * ws_value, p_walk)
            in_mass = p[dest["in_city"]].sum()
            share_all[slot] += (in_mass, p.sum())
            if category == "restaurant_bar":
                share_food[slot] += (in_mass, p.sum())
    return capture, walk_dollars, share_food, share_all


def _rollup(dest, capture, walk_dollars):
    """Sum per-POI capture (total and walk-arriving) into named clusters for
    the reporting metrics and cluster tooltips."""
    import numpy as np

    labels = dest["cluster"]
    rolled = {}
    for label, meta in dest["cluster_meta"].items():
        members = np.where(labels == label)[0]
        rolled[label] = {
            **meta,
            "value": float(capture[0][members].sum()),
            "low": float(capture[1][members].sum()),
            "high": float(capture[2][members].sum()),
            "walk_value": float(walk_dollars[0][members].sum()),
        }
    return rolled


# --- foot traffic: exact marginal flows -------------------------------------

def route_edge_amounts(sub, origin, amounts: dict) -> dict:
    """Route fixed per-destination amounts (already-decided trips or dollars)
    from `origin` along shortest paths; returns {edge: amount}. Destinations
    missing from the graph or unreachable are skipped. Deterministic; pure
    networkx; unit-tested against a hand-computed toy case."""
    import networkx as nx

    _dists, paths = nx.single_source_dijkstra(sub, origin, weight="travel_min")
    flows: dict[tuple, float] = {}
    for node, amount in amounts.items():
        if amount <= 0 or node == origin:
            continue
        path = paths.get(node)
        if not path:
            continue
        for edge in zip(path[:-1], path[1:]):
            flows[edge] = flows.get(edge, 0.0) + amount
    return flows


def marginal_edge_flows(sub, origin, dest_weights: dict, beta: float,
                        total_trips: float) -> dict:
    """Exact per-edge walk flows generated by `total_trips` starting at
    `origin`: destination choice ∝ weight × exp(-beta × t), routed along
    shortest paths. Deterministic — no sampling. Pure networkx; unit-tested
    against a hand-computed toy case."""
    import networkx as nx

    dists, _paths = nx.single_source_dijkstra(sub, origin, weight="travel_min")
    utilities = {}
    for node, weight in dest_weights.items():
        t = dists.get(node)
        if t is None or weight <= 0 or node == origin:
            continue
        utilities[node] = weight * math.exp(-beta * t)
    total = sum(utilities.values())
    if total <= 0:
        return {}
    return route_edge_amounts(
        sub, origin,
        {node: total_trips * utility / total for node, utility in utilities.items()})


def _foot_traffic(ctx, spec, total_trips: float, trip_rate: float, beta: float):
    """(flows {edge: trips/day}, pct {edge: %Δ vs baseline}, nearest-10
    commercial mean %Δ, subgraph). The marginal flows are exact; the baseline
    is the seeded sampled betweenness of today's population, used only as the
    denominator. Both sides carry the same trip_rate, so it cancels out of
    the percentage — the % is rate-assumption-free."""
    import networkx as nx
    import numpy as np
    import osmnx as ox

    graph = ctx.walk_graph
    weights = ctx.node_weights
    site = _site_point(spec, ctx)
    site_node = ox.distance.nearest_nodes(graph, site.x, site.y)

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
    if pop.sum() == 0 or poi.sum() == 0:
        raise ValueError("no population or POI weight in study area")

    # exact marginal flows from the site
    dest_weights = {node: poi[i] for node, i in index_of.items() if poi[i] > 0}
    flows = marginal_edge_flows(sub, site_node, dest_weights, beta, total_trips)

    # seeded sampled baseline (today's walkers), for the % comparison only
    rng = np.random.default_rng(BASELINE_SEED)
    origins = rng.choice(len(nodes), size=BASELINE_PAIRS, p=pop / pop.sum())
    dests = rng.choice(len(nodes), size=BASELINE_PAIRS, p=poi / poi.sum())
    baseline: dict[tuple, float] = {}
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
                baseline[(u, v)] = baseline.get((u, v), 0) + 1

    # baseline sample count -> trips/day at the SAME trip rate the marginal
    # flows use: baseline_trips_e = count_e x (pop_total x rate / k)
    baseline_scale = pop.sum() * trip_rate / BASELINE_PAIRS

    pct: dict[tuple, float] = {}
    for edge, marginal in flows.items():
        count = baseline.get(edge, 0)
        if count >= BASELINE_MIN_COUNT:
            pct[edge] = 100.0 * marginal / (count * baseline_scale)

    commercial = []
    for edge, p in pct.items():
        u, v = edge
        if poi[index_of[u]] + poi[index_of[v]] > 0:
            ux, uy = nodes_gdf.loc[u].geometry.x, nodes_gdf.loc[u].geometry.y
            dist = ((ux - sx) ** 2 + (uy - sy) ** 2) ** 0.5
            commercial.append((dist, p))
    commercial.sort()
    nearest = [p for _, p in commercial[:10]]
    nearest_delta = float(np.mean(nearest)) if nearest else 0.0
    return flows, pct, nearest_delta, sub


def _street_layer(sub, primary: dict, prop: str, decimals: int = 1,
                  secondary: dict | None = None, secondary_prop: str = "") -> dict:
    """Top-N edges of `primary` as GeoJSON lines, with an optional second
    property joined per edge (e.g. Δ% alongside trips/day)."""
    import osmnx as ox

    edges_gdf = ox.convert.graph_to_gdfs(sub, nodes=False).reset_index()
    lookup = {(row.u, row.v): row.geometry for row in edges_gdf.itertuples()}
    ranked = sorted(primary.items(), key=lambda kv: kv[1], reverse=True)[:TOP_EDGES_IN_LAYER]
    features = []
    for edge, value in ranked:
        geom = lookup.get(edge) or lookup.get((edge[1], edge[0]))
        if geom is None:
            continue
        geom = geom.simplify(0.00005)
        coords = [[round(x, 6), round(y, 6)] for x, y in geom.coords]
        properties = {prop: round(value, decimals)}
        if secondary is not None and edge in secondary:
            properties[secondary_prop] = round(secondary[edge], 1)
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": properties,
        })
    return {"type": "FeatureCollection", "features": features}


def _capture_points_layer(dest, capture, walk_dollars) -> dict:
    """Per-POI capture as weighted points — the heatmaps' real input.
    walk_usd is the walk-arriving share of that business's capture, so the
    frontend can show total capture and walk-in capture on one scale."""
    features = []
    for i in range(dest["n"]):
        dollars = float(capture[0][i])
        if dollars < MIN_POINT_CAPTURE_USD:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(float(dest["lon"][i]), 6),
                                         round(float(dest["lat"][i]), 6)]},
            "properties": {"capture_usd": round(dollars),
                           "walk_usd": round(float(walk_dollars[0][i])),
                           "own": bool(dest["cluster"][i] == -2)},
        })
    return {"type": "FeatureCollection", "features": features}


def _cluster_layer(ctx, rolled: dict) -> dict:
    import pyproj
    to4326 = pyproj.Transformer.from_crs(ctx.cfg.crs_projected, "EPSG:4326", always_xy=True)
    features = []
    for label, c in rolled.items():
        if c["value"] <= 0:
            continue
        lon, lat = to4326.transform(c["x"], c["y"])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {"name": c["name"], "annual_capture_usd": round(c["value"]),
                           "walk_usd": round(c.get("walk_value", 0.0)),
                           "poi_count": c["poi_count"], "own": c["own"]},
        })
    return {"type": "FeatureCollection", "features": features}


def run(spec, ctx, prior=None):
    a = _assumptions(ctx)
    notes = [
        "Huff capture is a screening estimate computed per business location "
        "(every retail POI is an individual destination) and aggregated to "
        "named areas for reporting; it ranks where new spending is likely to "
        "land, with sensitivity bounds — it is not a prediction.",
    ]

    if spec.proposed.units is None:
        return (ModuleResult(
            module="economic", metrics=[],
            narrative_notes=["Not computed: the proposed unit count could not be "
                            "extracted from the project documents."],
            assumptions=[],
        ), {})

    site = _site_point(spec, ctx)
    households, residents, aggregate_income, spend, income_base, income_scope = \
        _demand(spec, ctx, a, site)

    tx = ctx.transformer()
    sx, sy = tx.transform(site.x, site.y)
    from shapely.geometry import Point
    site_projected = Point(sx, sy)

    own_equiv_total = (spec.proposed.retail_sqft or 0) / a["own_retail_sqft_per_equiv_poi"].value
    own_retail_equiv = {cls: own_equiv_total * share for cls, share in OWN_RETAIL_MIX.items()}

    dest = _destinations(ctx, site, site_projected, own_retail_equiv)
    capture, walk_dollars, share_food, share_all = _capture(dest, spend, a)
    rolled = _rollup(dest, capture, walk_dollars)

    metrics: list[MetricValue] = []
    ces_prov = ces_shares.provenance()
    acs_prov = a["avg_hh_size_renter"].basis
    huff_method = ("Huff model over individual retail POIs: P_ij = A_j^a * "
                   "exp(-b*t_ij) / sum_k, blended walk/drive impedance, CES "
                   "category spend; clusters are a reporting rollup")

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
        f"households x median income of the {income_scope} "
        f"(${income_base:,.0f}, ACS B19013) x new-construction premium"))

    for category in RETAIL_CLASSES:
        metrics.append(metric(
            f"New annual spending: {category}", spend[category], "$/yr",
            [ces_prov], [a["ces_scale"], a["income_premium_new_construction"]],
            "aggregate income x CES category share"))

    named = [c for label, c in rolled.items() if label >= 0]
    for c in sorted(named, key=lambda c: -c["value"])[:5]:
        metrics.append(MetricValue(
            name=f"Annual capture: {c['name']}",
            value=c["value"], unit="$/yr", low=c["low"], high=c["high"],
            provenance=[ces_prov], method=huff_method,
            assumptions=["beta_walk", "walk_share_neighborhood", "ces_scale"],
        ))

    for label, shares in (("food_away", share_food), ("all_retail", share_all)):
        import numpy as np
        ratio = [float(shares[slot][0] / shares[slot][1]) if shares[slot][1] > 0 else 0.0
                 for slot in range(3)]
        metrics.append(MetricValue(
            name=f"In-city capture share: {label}",
            value=ratio[0], unit="fraction", low=min(ratio), high=max(ratio),
            provenance=[ces_prov], method=huff_method + "; share of capture at "
            "destinations inside the city boundary",
            assumptions=["beta_walk", "walk_share_neighborhood"],
        ))

    own = rolled[-2]
    metrics.append(MetricValue(
        name="Annual capture: project's own ground-floor retail",
        value=own["value"], unit="$/yr", low=own["low"], high=own["high"],
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

    # walking expenditures: the walk-mode share of capture, totaled exactly
    # (per-category walk probabilities sum to 1, so the per-POI allocation
    # sums back to spend x walk share) and routed over the streets below
    walk_total = None
    for category in RETAIL_CLASSES:
        term = spend[category] * Interval.from_assumption(_walk_share_for(category, a))
        walk_total = term if walk_total is None else walk_total + term
    ces_mode_assumptions = [a["walk_share_neighborhood"], a["walk_share_comparison"],
                            a["walk_share_grocery_entertainment"], a["ces_scale"]]
    metrics.append(metric(
        "New annual spending arriving on foot", walk_total, "$/yr",
        [ces_prov], ces_mode_assumptions,
        "sum over categories of spend x walk mode share; allocated per business "
        "by walk-time Huff probabilities", headline=True))
    metrics.append(MetricValue(
        name="Spending arriving on foot at project's own retail",
        value=float(walk_dollars[0][-1]), unit="$/yr",
        low=float(walk_dollars[1][-1]), high=float(walk_dollars[2][-1]),
        provenance=[ces_prov],
        method="walk-mode Huff allocation at the own-retail destination",
        assumptions=["own_retail_sqft_per_equiv_poi", "beta_walk",
                     "walk_share_neighborhood"],
    ))

    # foot traffic: exact marginal flows
    trips = residents * Interval.from_assumption(a["walk_trips_per_resident_day"])
    flows, pct, nearest_delta, sub = _foot_traffic(
        ctx, spec, total_trips=trips.value,
        trip_rate=a["walk_trips_per_resident_day"].value,
        beta=a["beta_walk"].value)

    # consistency diagnostic: dollars per walk trip should be plausible
    per_trip = walk_total / (trips * 365.0)
    metrics.append(metric(
        "Implied spending per resident walk trip", per_trip, "$/trip",
        [ces_prov], [a["walk_trips_per_resident_day"], *ces_mode_assumptions],
        "walking spend total / (daily walk trips x 365) — consistency check "
        "between the mode-split and trip-rate assumptions"))
    if not (2.0 <= per_trip.value <= 60.0):
        notes.append(
            f"CONSISTENCY FLAG: implied spending per walk trip is "
            f"${per_trip.value:,.2f}, outside the plausible $2-60 range — the "
            "mode-split and walk-trip-rate assumptions disagree; revisit them "
            "before leaning on the walking-expenditure figures.")
    trips_prov = prov("Derived: new residents x NHTS walking trip rate",
                      "https://nhts.ornl.gov", "2022")
    osm_prov = prov("OpenStreetMap walk network + ACS population + merged POI layer",
                    "https://www.openstreetmap.org", "current",
                    f"exact shortest-path flow allocation; baseline sampled "
                    f"betweenness k={BASELINE_PAIRS}, seeded")
    metrics.append(metric(
        "New resident walk trips per day", trips, "trips/day",
        [trips_prov], [a["walk_trips_per_resident_day"], a["avg_hh_size_renter"],
                       a["occupancy_rate"]],
        "new residents x daily walk trips per resident"))
    metrics.append(MetricValue(
        name="Foot-traffic index change, 10 nearest commercial street segments",
        value=round(nearest_delta, 1), unit="% (relative index)",
        low=None, high=None, provenance=[osm_prov],
        method=("exact marginal trip flows from the site (POI-weighted "
                "destinations, exp(-b*t) walk decay, shortest paths) vs. the "
                "seeded sampled baseline betweenness of today's population"),
        assumptions=["occupancy_rate", "avg_hh_size_renter",
                     "walk_trips_per_resident_day", "beta_walk"], headline=True,
    ))
    if ctx.cfg.calibration_counts is None:
        notes.append("Foot-traffic flows are exact allocations of the new "
                     "residents' modeled walk trips; the % comparison uses a "
                     "sampled index of today's walkers, not calibrated "
                     "pedestrian counts.")

    # route the walk-arriving dollars over the same street tree the trips use
    dollar_amounts: dict = {}
    for i, node in enumerate(dest["walk_nodes"]):  # excludes the own destination
        if node in sub:
            dollar_amounts[node] = dollar_amounts.get(node, 0.0) + float(walk_dollars[0][i])
    dollar_flows = route_edge_amounts(sub, dest["walk_origin"], dollar_amounts)
    notes.append(
        "Walk-in capture per business (and its street-routed form) is the "
        "walk-arriving share of the NEW residents' spending — not total "
        "pedestrian commerce, and not incremental sales (some walk-arriving "
        "dollars would otherwise have arrived by car). Comparing a business's "
        "walk-in capture to its total capture shows how much of its projected "
        "gain depends on being within walking distance of the project.")

    layers = {
        "site": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": spec.geometry, "properties": {"role": "site"}}]},
        "capture_points": _capture_points_layer(dest, capture, walk_dollars),
        "capture_clusters": _cluster_layer(ctx, rolled),
        "commercial_retail_zones": ctx.commercial_retail_zones,
        "foot_traffic_delta": _street_layer(sub, flows, "trips_per_day",
                                            secondary=pct, secondary_prop="delta_pct"),
        "walk_dollars": _street_layer(sub, dollar_flows, "dollars_per_year", decimals=0),
    }
    result = ModuleResult(
        module="economic", metrics=metrics,
        map_layer_labels=list(layers),
        narrative_notes=notes,
        assumptions=list(a.values()),
    )
    return result, layers
