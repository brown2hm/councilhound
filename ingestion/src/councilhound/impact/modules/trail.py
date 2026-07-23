"""Trail module: economic + fiscal screening for linear trail / greenway
projects (multi-use paths, park trails).

`run(spec, ctx, prior=None) -> (ModuleResult, {label: geojson})`.

Two additive channels:
(a) trail-user spending — access points along the trail line -> per-access-
    point Dijkstra over the walk network -> decay-weighted catchment
    population (beta_trail_access_km, the best-powered curve in Iacono's
    MnDOT report: N=1,967, R2=0.93) -> annual user-days x spend per user-day
    (NCDOT/ITRE four-trail transcription) -> allocated to nearby businesses
    with the walk-decay Huff machinery.
(b) property capitalization — parcels within TRAIL_PREMIUM_BAND_FT of the
    line x trail_property_premium (Crompton & Nicholls 2019; 0 floor per the
    null findings, incl. NCDOT's own ATT hedonic) -> assessed-value uplift ->
    annual real-estate tax increment at the pinned city rate (unpinned rate
    degrades to a note, never a guess — the fiscal-module idiom).

Ordinary-greenway regime only: destination-trail figures (GAP, Virginia
Creeper, Duck Trail) are deliberately excluded from the anchors.
"""
from __future__ import annotations

import logging

from councilhound.impact.jurisdiction import MissingRateError, require_rate
from councilhound.impact.provenance import Interval, metric, prov, term
from councilhound.impact.schemas import Assumption, MetricValue, ModuleResult
from councilhound.impact.modules import huff
from councilhound.impact.modules.economic import (
    RETAIL_CLASSES, _assumptions as _econ_assumptions, _city_boundary_layer)

log = logging.getLogger(__name__)

M_TO_FT = 3.28084
ACCESS_NODE_BUFFER_M = 50.0     # walk-graph nodes "on" the trail
ACCESS_SPACING_M = 250.0        # thin trail nodes to one access point per 250 m
MAX_ACCESS_POINTS = 40          # Dijkstra budget
TRAIL_PREMIUM_BAND_FT = 1_650.0  # ~1/3 mi: the Crompton evidence window
CATCHMENT_TOP_POINTS = 500
MIN_POINT_USD = 100
WALK_MIN_PER_M = 60.0 / 4.8 / 1000.0  # walk minutes per network meter

_TRAIL_FACILITY_WORDS = ("trail", "shared use path", "shared-use path",
                         "greenway", "multi-use", "multiuse")


def _assumptions(ctx) -> dict[str, Assumption]:
    # beta_walk is shared with the economic module verbatim (bundle dedupes
    # by key) — it shapes only the business allocation, not the totals
    beta_walk = _econ_assumptions(ctx)["beta_walk"]
    return {a.key: a for a in [
        beta_walk,
        Assumption(key="beta_trail_access_km", value=0.333, low=0.25, high=0.45,
                   basis="Iacono, Krizek & El-Geneidy (MnDOT 2008-11) Table 2, "
                         "'Trail Trips' row: distance decay 0.333/km from "
                         "residence to trail entrance, N=1,967, R2=0.93 "
                         "(Hennepin County trail-user survey) — the best-"
                         "powered curve in the report; ~50% weight at 2 km, "
                         "~20% at 5 km. Local: docs/references/"
                         "iacono-krizek-elgeneidy-2008-mndot-distance-decay.pdf",
                   rationale="defines the trail's user catchment around access "
                             "points; a network-shape parameter, so it carries "
                             "no slider terms — changing it requires a full "
                             "rerun"),
        Assumption(key="trail_user_days_per_capita", value=12.0, low=6.0, high=20.0,
                   basis="NCDOT/ITRE (2018) NCDOT 2015-44: annual trips / one-"
                         "mile-band population — American Tobacco Trail ~13 "
                         "(480,800 trips, 840 people/mi2), Little Sugar Creek "
                         "~14 (382,600 trips, 3,348/mi2), Brevard ~10 (76,000 "
                         "trips, town of ~7,700); bounds widened for the "
                         "roughness of the band-population derivation. Duck "
                         "Trail excluded (beach-tourism regime). Local: docs/"
                         "references/ncdot-itre-2018-shared-use-paths-economic-"
                         "impact.pdf",
                   rationale="annual trail user-days generated per decay-"
                             "weighted catchment resident"),
        Assumption(key="trail_spend_per_user_day", value=7.5, low=6.0, high=11.0,
                   basis="NCDOT/ITRE (2018) Table 26 direct expenditure per "
                         "trip: American Tobacco $6.24, Little Sugar Creek "
                         "$7.27, Brevard $10.93; Duck Trail ($25.00) excluded "
                         "as a destination/tourism regime. Four-trail intercept "
                         "surveys + infrared counts. Local: docs/references/"
                         "ncdot-itre-2018-shared-use-paths-economic-impact.pdf",
                   rationale="dollars a trail user-day leaves at nearby "
                             "businesses (ordinary urban greenway regime)"),
        Assumption(key="trail_property_premium", value=0.03, low=0.0, high=0.05,
                   basis="Crompton & Nicholls (2019, JPRA 37(3)): 20 hedonic "
                         "analyses, typical 3-5% premium for homes near "
                         "trails; null-result cases (Indianapolis; NCDOT's own "
                         "American Tobacco Trail regression, 0.7-2.6% n.s.) "
                         "set the 0 floor; destination mega-trails (Chicago "
                         "606 ~22%) are a different regime and excluded. "
                         "Local: docs/references/crompton-nicholls-2019-"
                         "greenways-property-values.pdf",
                   rationale="capitalization premium applied to assessed value "
                             "in the proximity band; hold to the lower half of "
                             "the interval for unpaved or low-quality "
                             "facilities"),
    ]}


def _not_computed(reason: str) -> tuple[ModuleResult, dict]:
    return (ModuleResult(module="trail", metrics=[],
                         narrative_notes=[f"Not computed: {reason}"],
                         assumptions=[]), {})


def _trail_line(spec):
    from shapely.geometry import shape
    if spec.geometry is None:
        return None
    geom = shape(spec.geometry)
    if geom.geom_type not in ("LineString", "MultiLineString"):
        return None
    return geom


def _is_trail_project(spec) -> bool:
    if spec.project_type == "park":
        return True
    if spec.project_type != "street_multimodal":
        return False
    corridor = spec.proposed.corridor
    return corridor is not None and any(
        any(w in f.lower() for w in _TRAIL_FACILITY_WORDS)
        for f in corridor.facilities)


def _access_points(ctx, line_4326) -> list:
    """Walk-graph nodes within ACCESS_NODE_BUFFER_M of the trail, thinned to
    roughly one per ACCESS_SPACING_M along the line."""
    import numpy as np
    import osmnx as ox
    from shapely.ops import transform as shp_transform

    line = shp_transform(ctx.transformer().transform, line_4326)
    nodes = ox.convert.graph_to_gdfs(ctx.walk_graph, edges=False)[["geometry"]]
    nodes = nodes.to_crs(ctx.cfg.crs_projected)
    near = nodes[nodes.distance(line) <= ACCESS_NODE_BUFFER_M * M_TO_FT]
    if not len(near):
        return []
    # greedy spacing along the line: sort candidates by their projected
    # position, keep one per spacing bucket
    positions = near.geometry.apply(lambda p: line.project(p))
    order = positions.sort_values()
    spacing_ft = ACCESS_SPACING_M * M_TO_FT
    kept, last = [], -1e18
    for node, pos in order.items():
        if pos - last >= spacing_ft:
            kept.append(node)
            last = pos
    if len(kept) > MAX_ACCESS_POINTS:
        step = len(kept) / MAX_ACCESS_POINTS
        kept = [kept[int(i * step)] for i in range(MAX_ACCESS_POINTS)]
    return kept


def _catchment_and_capture(ctx, access_nodes, beta_km: Assumption,
                           beta_walk: Assumption):
    """Per-access-point Dijkstras over the walk network (edge length, meters)
    give both the catchment (km decay from residence to nearest access point)
    and the business capture times (walk minutes from the assigned access
    point). Returns (catchment Interval, per-block detail, retail frame,
    per-business probability rows at the three beta_walk slots)."""
    import networkx as nx
    import numpy as np
    import osmnx as ox

    graph = ctx.walk_graph
    blocks = ctx.blocks
    block_nodes = ox.distance.nearest_nodes(graph, list(blocks["lon"]),
                                            list(blocks["lat"]))
    retail = ctx.pois[ctx.pois["taxonomy"].isin(RETAIL_CLASSES)].reset_index(drop=True)
    retail_nodes = ox.distance.nearest_nodes(graph, list(retail.geometry.x),
                                             list(retail.geometry.y))

    n_blocks, n_retail = len(blocks), len(retail)
    block_m = np.full((len(access_nodes), n_blocks), np.inf)
    retail_m = np.full((len(access_nodes), n_retail), np.inf)
    for k, source in enumerate(access_nodes):
        dist = nx.single_source_dijkstra_path_length(graph, source, weight="length")
        block_m[k] = [dist.get(n, np.inf) for n in block_nodes]
        retail_m[k] = [dist.get(n, np.inf) for n in retail_nodes]

    # each block belongs to its nearest access point
    d_m = block_m.min(axis=0)
    assigned = block_m.argmin(axis=0)
    pop = blocks["pop"].to_numpy(dtype=float)
    d_km = d_m / 1000.0

    def weighted(beta_value: float) -> np.ndarray:
        with np.errstate(over="ignore"):
            return pop * np.exp(-beta_value * d_km)

    w_val, w_low, w_high = (weighted(beta_km.value), weighted(beta_km.high),
                            weighted(beta_km.low))
    catchment = Interval(float(w_val.sum()), float(w_low.sum()),
                         float(w_high.sum()))

    # spend allocation: access points weighted by their share of the central
    # catchment; businesses by walk-decay Huff from each access point. The
    # probability rows sum to 1 per slot (or the reachable renormalization),
    # so allocate_spend conserves the channel total.
    finite = np.isfinite(d_km)
    share = np.zeros(len(access_nodes))
    for k in range(len(access_nodes)):
        share[k] = w_val[(assigned == k) & finite].sum()
    total_share = share.sum()
    p_slots = [np.zeros(n_retail) for _ in range(3)]
    if total_share > 0 and n_retail:
        share = share / total_share
        attractiveness = np.ones(n_retail)
        retail_min = retail_m * WALK_MIN_PER_M
        for slot, beta in enumerate((beta_walk.value, beta_walk.high,
                                     beta_walk.low)):
            for k in range(len(access_nodes)):
                if share[k] <= 0:
                    continue
                p = huff.huff_probabilities(attractiveness, retail_min[k],
                                            beta=beta)
                p_slots[slot] += share[k] * p

    detail = {"lon": blocks["lon"].to_numpy(), "lat": blocks["lat"].to_numpy(),
              "weight": w_val, "km": d_km}
    return catchment, detail, retail, p_slots


def _premium_band(ctx, line_4326):
    """(band polygon projected->4326, parcel_count, assessed_total) for the
    parcels intersecting the trail's premium band."""
    import geopandas as gpd
    from shapely.ops import transform as shp_transform
    import pyproj

    line = shp_transform(ctx.transformer().transform, line_4326)
    band = line.buffer(TRAIL_PREMIUM_BAND_FT)
    parcels = ctx.parcels
    projected = parcels.to_crs(ctx.cfg.crs_projected)
    mask = projected.intersects(band)
    hits = parcels[mask.to_numpy()]
    if "assessed_total" not in hits.columns:
        # the parcels context can be built without the assessment join —
        # the premium channel degrades to a note rather than guessing
        return None, int(mask.sum()), 0.0
    assessed = float(hits["assessed_total"].fillna(0).sum())
    to4326 = pyproj.Transformer.from_crs(ctx.cfg.crs_projected, "EPSG:4326",
                                         always_xy=True)
    band_4326 = shp_transform(to4326.transform, band.simplify(10 * M_TO_FT))
    return band_4326, int(mask.sum()), assessed


def _line_layer(line_4326, role: str) -> dict:
    from shapely.geometry import mapping
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": mapping(line_4326.simplify(0.00005)),
        "properties": {"role": role},
    }]}


def _access_layer(ctx, access_nodes) -> dict:
    graph = ctx.walk_graph
    features = []
    for node in access_nodes:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(graph.nodes[node]["x"], 6),
                                         round(graph.nodes[node]["y"], 6)]},
            "properties": {"role": "trail_access"},
        })
    return {"type": "FeatureCollection", "features": features}


def _capture_layer(retail, alloc) -> dict:
    features = []
    for i, row in retail.iterrows():
        usd = float(alloc[i])
        if usd < MIN_POINT_USD:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(float(row.geometry.x), 6),
                                         round(float(row.geometry.y), 6)]},
            "properties": {"name": str(row.get("name", "")),
                           "trail_usd": round(usd)},
        })
    return {"type": "FeatureCollection", "features": features}


def _catchment_layer(detail) -> dict:
    import numpy as np
    order = np.argsort(-detail["weight"])[:CATCHMENT_TOP_POINTS]
    features = []
    for i in order:
        if detail["weight"][i] <= 0:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(float(detail["lon"][i]), 5),
                                         round(float(detail["lat"][i]), 5)]},
            "properties": {"weighted_pop": round(float(detail["weight"][i]), 1),
                           "km_to_access": round(float(detail["km"][i]), 2)},
        })
    return {"type": "FeatureCollection", "features": features}


def _band_layer(band_4326, parcel_count: int, assessed: float) -> dict:
    from shapely.geometry import mapping
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": mapping(band_4326),
        "properties": {"role": "trail_premium_band",
                       "parcel_count": parcel_count,
                       "assessed_total": round(assessed)},
    }]}


def run(spec, ctx, prior=None):
    if not _is_trail_project(spec):
        return _not_computed(
            f"trail module applies to park/trail projects (this project is "
            f"{spec.project_type} without trail facilities)")
    line = _trail_line(spec)
    if line is None:
        return _not_computed(
            "trail module requires a linear trail geometry — resolve the "
            "corridor at extract/confirm or supply one with "
            "`impact-confirm --geometry`")

    a = _assumptions(ctx)
    notes = [
        "Trail estimates are screening ranges for an ORDINARY urban greenway: "
        "user-day and spending anchors come from the NCDOT/ITRE four-trail "
        "study, and destination-trail behavior (overnight tourism) is "
        "deliberately out of scope. If this trail plausibly draws overnight "
        "visitors, these figures are conservative.",
    ]

    access_nodes = _access_points(ctx, line)
    if not access_nodes:
        return _not_computed("the trail line touches no walk-network nodes — "
                             "check the resolved geometry")

    catchment, detail, retail, p_slots = _catchment_and_capture(
        ctx, access_nodes, a["beta_trail_access_km"], a["beta_walk"])

    user_days = catchment * Interval.from_assumption(a["trail_user_days_per_capita"])
    spending = user_days * Interval.from_assumption(a["trail_spend_per_user_day"])

    iacono_prov = prov(
        "Iacono, Krizek & El-Geneidy (MnDOT 2008-11), Table 2 trail-access "
        "decay (Hennepin County trail-user survey)",
        "https://mdl.mndot.gov/_flysystem/fedora/2023-01/200811.pdf", "2008")
    ncdot_prov = prov(
        "NCDOT/ITRE (2018), Evaluating the Economic Impact of Shared Use "
        "Paths in North Carolina (NCDOT 2015-44), Table 26 + count program",
        "https://itre.ncsu.edu/focus/bike-ped/sup-economic-impacts", "2018")
    osm_prov = prov("OpenStreetMap walk network + Census 2020 block population",
                    "https://www.openstreetmap.org", "current",
                    f"{len(access_nodes)} access points, one per "
                    f"~{ACCESS_SPACING_M:.0f} m of trail")

    metrics: list[MetricValue] = []
    metrics.append(metric(
        "Trail catchment population (decay-weighted)", catchment, "residents",
        [iacono_prov, osm_prov], [a["beta_trail_access_km"]],
        "sum over census blocks of pop x exp(-0.333/km x walk-network km to "
        "the nearest trail access point); the decay parameter is a network "
        "shape, so this metric has no slider terms"))
    metrics.append(metric(
        "Annual trail user-days", user_days, "user-days/yr",
        [ncdot_prov], [a["beta_trail_access_km"], a["trail_user_days_per_capita"]],
        "catchment population x annual user-days per catchment resident",
        adjust=[term(user_days.value, trail_user_days_per_capita=1.0)]))
    metrics.append(metric(
        "Annual trail-user spending at nearby businesses", spending, "$/yr",
        [ncdot_prov], [a["beta_trail_access_km"], a["trail_user_days_per_capita"],
                       a["trail_spend_per_user_day"]],
        "annual user-days x direct spending per user-day (NCDOT four-trail "
        "range, destination trails excluded); allocated to businesses by "
        "walk-decay Huff from the access points", headline=True,
        adjust=[term(spending.value, trail_user_days_per_capita=1.0,
                     trail_spend_per_user_day=1.0)]))

    # per-business allocation (three slots so top businesses carry bounds)
    import numpy as np
    alloc_slots = [p_slots[0] * spending.value, p_slots[1] * spending.low,
                   p_slots[2] * spending.high]
    alloc = alloc_slots[0]
    if alloc.sum() > 0:
        top = np.argsort(-alloc)[:5]
        for i in top:
            if alloc[i] <= 0:
                continue
            name = str(retail.iloc[i].get("name", "")) or "unnamed business"
            metrics.append(MetricValue(
                name=f"Annual trail-user capture: {name}",
                value=float(alloc[i]), unit="$/yr",
                low=float(alloc_slots[1][i]), high=float(alloc_slots[2][i]),
                provenance=[ncdot_prov],
                method="trail spending x access-point catchment shares x "
                       "walk-decay Huff probability of this business",
                assumptions=["beta_walk", "trail_user_days_per_capita",
                             "trail_spend_per_user_day"],
            ))
    else:
        notes.append("No retail businesses are walk-reachable from the trail "
                     "access points — the spending total stands, but no "
                     "per-business allocation is shown.")

    # channel (b): property capitalization -> RE tax increment
    band_4326, parcel_count, assessed = _premium_band(ctx, line)
    layers = {
        "trail_line": _line_layer(line, "trail"),
        "trail_access_points": _access_layer(ctx, access_nodes),
        "trail_catchment": _catchment_layer(detail),
        "city_boundary": _city_boundary_layer(ctx.boundary),
    }
    if alloc.sum() > 0:
        layers["trail_capture_points"] = _capture_layer(retail, alloc)

    if parcel_count and assessed > 0:
        layers["trail_premium_band"] = _band_layer(band_4326, parcel_count, assessed)
        parcels_prov = prov(
            "City parcel layer with assessments (context parcels)",
            "https://data.fairfaxva.gov", "current",
            f"{parcel_count} parcels within {TRAIL_PREMIUM_BAND_FT:.0f} ft "
            "of the trail line")
        crompton_prov = prov(
            "Crompton & Nicholls (2019), The Impact of Greenways and Trails "
            "on Proximate Property Values: An Updated Review, JPRA 37(3)",
            "https://js.sagamorepub.com/index.php/jpra/article/view/9906", "2019")
        av_band = Interval.point(assessed)
        metrics.append(metric(
            "Assessed value within the trail premium band", av_band, "$",
            [parcels_prov], [],
            f"sum of assessed_total for parcels within "
            f"{TRAIL_PREMIUM_BAND_FT:.0f} ft (~1/3 mi) of the trail"))
        uplift = av_band * Interval.from_assumption(a["trail_property_premium"])
        metrics.append(metric(
            "Trail property value uplift (capitalization)", uplift, "$",
            [crompton_prov, parcels_prov], [a["trail_property_premium"]],
            "assessed value in the premium band x trail property premium "
            "(one-time capitalization into home values; 0 floor reflects "
            "null findings for low-profile trails)",
            adjust=[term(uplift.value, trail_property_premium=1.0)]))
        try:
            re_rate = require_rate(ctx.cfg, "tax.real_estate_rate_per_100")
            tax = uplift * (re_rate.value / 100.0)
            metrics.append(metric(
                "Annual real estate tax increment (trail premium)", tax, "$/yr",
                [crompton_prov, parcels_prov,
                 prov("City real estate tax rate", re_rate.source or "",
                      re_rate.fy or "")],
                [a["trail_property_premium"]],
                "property value uplift x RE rate / 100 — recurring only if "
                "the premium capitalizes into assessments", headline=True,
                adjust=[term(tax.value, trail_property_premium=1.0)]))
        except MissingRateError as exc:
            notes.append(f"Not computed: tax.real_estate_rate_per_100 — {exc}")
        notes.append(
            "The property-premium channel is a capitalization estimate, not "
            "cash: it becomes recurring tax revenue only as assessments "
            "reflect the premium, and the 3-5% literature range comes from "
            "trails people actually value — hold to the low half for "
            "unpaved or disconnected facilities.")
    elif band_4326 is None:
        notes.append(
            "Not computed: property premium — the parcels context layer "
            f"carries no assessed values ({parcel_count} parcels fall within "
            "the band). Rebuild the parcels layer with the assessment source "
            "configured to enable this channel.")
    else:
        notes.append("Not computed: property premium — no assessed parcels "
                     "found within the trail band (check the parcels context "
                     "layer)")

    result = ModuleResult(module="trail", metrics=metrics,
                          map_layer_labels=list(layers),
                          narrative_notes=notes,
                          assumptions=list(a.values()))
    return result, layers
