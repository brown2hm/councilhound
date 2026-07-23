"""Bike-lane module: economic screening for street/multimodal corridor
projects (new bike facilities along a named street).

`run(spec, ctx, prior=None) -> (ModuleResult, {label: geojson})`.

Mechanism + literature bounds: the model is a bike-access mechanism — who can
newly reach the corridor by bike, and what do bike visits spend — while the
honesty lives in the `induced_corridor_visit_share` assumption, whose BOUNDS
are calibrated so corridor-level results stay inside the observed corridor
natural experiments (Liu & Shi 2020; Arancibia et al. 2019; Volker & Handy
2021). Its center is a screening default; its bounds carry the claim.

Pipeline: corridor line -> bike-graph nodes within CORRIDOR_NODE_BUFFER_M ->
multi-source Dijkstra over bike travel_min -> decay-weighted catchment
population (beta_bike) -> induced daily bike visits -> annual spending by
establishment group (Clifton et al. 2013 per-trip means) -> per-business
allocation + calibration diagnostic against a rough corridor sales baseline.
"""
from __future__ import annotations

import logging

from councilhound.impact.provenance import Interval, metric, prov, term
from councilhound.impact.schemas import Assumption, MetricValue, ModuleResult
from councilhound.impact.modules.economic import (
    RETAIL_CLASSES, _assumptions as _econ_assumptions, _city_boundary_layer)

log = logging.getLogger(__name__)

M_TO_FT = 3.28084
CORRIDOR_NODE_BUFFER_M = 50.0    # bike-graph nodes "on" the corridor
CORRIDOR_POI_BUFFER_M = 100.0    # businesses fronting/abutting the corridor
CATCHMENT_TOP_POINTS = 500       # map-layer budget: largest-weight blocks only
MIN_POINT_USD = 100              # trim the long tail out of the capture layer

# calibration-diagnostic baseline only (module constants, not Assumptions —
# the diagnostic flags implausibility, it is not a published estimate):
# typical inline suite x industry gross sales per sqft ~= $0.8M/business-yr
DIAG_SUITE_SQFT = 2000.0
DIAG_SALES_PER_SQFT = 400.0
DIAG_UPLIFT_CEILING = 0.50  # Liu & Shi Minneapolis food +52% vs +22% control

_BIKE_FACILITY_WORDS = ("bike", "bicycle", "cycle")

# establishment groups for the Clifton per-trip spend means
_SPEND_GROUP = {
    "restaurant_bar": "restaurant",
    "retail_convenience": "convenience",
}
SPEND_GROUPS = ("restaurant", "convenience", "other_retail")


def _spend_group(taxonomy: str) -> str:
    return _SPEND_GROUP.get(taxonomy, "other_retail")


def _assumptions(ctx) -> dict[str, Assumption]:
    # beta_bike is shared with the economic module verbatim (the bundle
    # dedupes assumptions by key) — import it so the two cannot drift
    beta_bike = _econ_assumptions(ctx)["beta_bike"]
    return {a.key: a for a in [
        beta_bike,
        Assumption(key="bike_trips_per_resident_day", value=0.035, low=0.02, high=0.05,
                   basis="FHWA (2020) NHTS brief (2017 NHTS): bikes ~1% of "
                         "person-trips nationally (walking ~10%; the walk module "
                         "uses 1.0 walk trips/resident-day) -> 0.02-0.05 bike "
                         "trips/resident-day; college towns run 5-10x, scale via "
                         "ACS bike-commute share. Local: docs/references/"
                         "fhwa-2020-nhts-nonmotorized-brief.pdf",
                   rationale="latent daily bike trips per catchment resident — "
                             "the dominant demand lever of the corridor model"),
        Assumption(key="induced_corridor_visit_share", value=0.10, low=0.03, high=0.20,
                   basis="bounds chosen so the implied corridor food/retail sales "
                         "uplift stays inside observed corridor natural "
                         "experiments: Liu & Shi (2020, NITC-RR-1031/1161; 14 "
                         "corridors, 6 cities, sales-tax data — Minneapolis "
                         "Central Ave food sales +52% vs +22% control, Seattle "
                         "Broadway food-service employment +31% vs 2.5-16% "
                         "controls); Arancibia et al. (2019, JAPA 85(4)) Bloor "
                         "St: customer counts and spending rose, vacancies "
                         "stable; Volker & Handy (2021, Transport Reviews "
                         "41(4)): 23 studies, positive-or-null for food/retail. "
                         "Local: docs/references/liu-shi-2020-nitc-street-"
                         "improvements-business-impacts.pdf, arancibia-2019-"
                         "japa-bloor-bike-lanes.pdf",
                   rationale="share of catchment residents' latent daily bike "
                             "trips newly ending at corridor businesses because "
                             "the facility exists (induced cycling and route "
                             "shift combined); the model's honesty knob — its "
                             "bounds, not its center, carry the claim"),
        Assumption(key="bike_spend_per_trip_restaurant", value=12.0, low=8.0, high=17.0,
                   basis="Clifton et al. (2013) Table 3, cyclist expenditure per "
                         "trip: restaurant $10.97 (N=29), bar $16.90 (N=20); "
                         "center between the two for a mixed corridor. Local: "
                         "docs/references/clifton-2013-consumer-behavior-travel-"
                         "choices.pdf",
                   rationale="dollars per induced bike visit at corridor "
                             "food/drink establishments"),
        Assumption(key="bike_spend_per_trip_convenience", value=8.0, low=5.0, high=11.0,
                   basis="Clifton et al. (2013) Table 3, cyclist expenditure per "
                         "trip at convenience stores: $7.95 (N=19) — the highest "
                         "of any mode; bounds bracket the cross-mode spread "
                         "($6.02 walk - $7.61 auto)",
                   rationale="dollars per induced bike visit at corridor "
                             "convenience retail"),
        Assumption(key="bike_spend_per_trip_other_retail", value=10.0, low=5.0, high=20.0,
                   basis="not directly surveyed by Clifton et al. (2013): "
                         "bounded below by the convenience per-trip mean "
                         "($7.95) and above by sit-down spending ($16.90 bar); "
                         "the carry-capacity constraint caps comparison-goods "
                         "baskets (drivers out-spend cyclists at supermarkets)",
                   rationale="dollars per induced bike visit at grocery/"
                             "comparison/services/entertainment establishments"),
    ]}


def _not_computed(reason: str) -> tuple[ModuleResult, dict]:
    return (ModuleResult(module="bike_lane", metrics=[],
                         narrative_notes=[f"Not computed: {reason}"],
                         assumptions=[]), {})


def _spending(trips: Interval, mix: dict[str, float], a: dict[str, Assumption]):
    """(spend_by_group, group_terms, total): induced visits split over the
    corridor's establishment-group mix, priced per trip. Pure Interval math —
    conservation (groups sum to total) and the power-law terms are pinned by
    unit tests."""
    spend_by_group: dict[str, Interval] = {}
    group_terms = []
    total = None
    for g in SPEND_GROUPS:
        share = mix.get(g, 0.0)
        if share <= 0:
            continue
        s = (trips * share * 365.0
             * Interval.from_assumption(a[f"bike_spend_per_trip_{g}"]))
        spend_by_group[g] = s
        group_terms.append(term(s.value, bike_trips_per_resident_day=1.0,
                                induced_corridor_visit_share=1.0,
                                **{f"bike_spend_per_trip_{g}": 1.0}))
        total = s if total is None else total + s
    return spend_by_group, group_terms, total


def _corridor_line(spec):
    from shapely.geometry import shape
    if spec.geometry is None:
        return None
    geom = shape(spec.geometry)
    if geom.geom_type not in ("LineString", "MultiLineString"):
        return None
    return geom


def _has_bike_facility(spec) -> bool:
    corridor = spec.proposed.corridor
    if corridor is None:
        return False
    return any(any(w in f.lower() for w in _BIKE_FACILITY_WORDS)
               for f in corridor.facilities)


def _corridor_nodes(ctx, line_4326) -> list:
    """Bike-graph nodes within CORRIDOR_NODE_BUFFER_M of the corridor line."""
    import osmnx as ox
    from shapely.ops import transform as shp_transform

    line = shp_transform(ctx.transformer().transform, line_4326)
    nodes = ox.convert.graph_to_gdfs(ctx.bike_graph, edges=False)[["geometry"]]
    nodes = nodes.to_crs(ctx.cfg.crs_projected)
    hits = nodes[nodes.distance(line) <= CORRIDOR_NODE_BUFFER_M * M_TO_FT]
    return list(hits.index)


def _corridor_businesses(ctx, line_4326):
    """Retail POIs within CORRIDOR_POI_BUFFER_M of the corridor line."""
    from shapely.ops import transform as shp_transform

    line = shp_transform(ctx.transformer().transform, line_4326)
    pois = ctx.pois
    retail = pois[pois["taxonomy"].isin(RETAIL_CLASSES)]
    projected = retail.to_crs(ctx.cfg.crs_projected)
    mask = projected.distance(line) <= CORRIDOR_POI_BUFFER_M * M_TO_FT
    return retail[mask.to_numpy()].reset_index(drop=True)


def _catchment(ctx, corridor_nodes, beta: Assumption):
    """Decay-weighted catchment population as an Interval over beta's bounds,
    plus per-block detail at the central beta for the map layer.

    Steeper decay -> smaller catchment, so the Interval's low evaluates at
    beta.high and its high at beta.low."""
    import networkx as nx
    import numpy as np
    import osmnx as ox

    graph = ctx.bike_graph
    dist = nx.multi_source_dijkstra_path_length(graph, set(corridor_nodes),
                                                weight="travel_min")
    blocks = ctx.blocks
    nearest = ox.distance.nearest_nodes(graph, list(blocks["lon"]),
                                        list(blocks["lat"]))
    t = np.array([dist.get(n, np.inf) for n in nearest])
    pop = blocks["pop"].to_numpy(dtype=float)

    def weighted(beta_value: float) -> float:
        with np.errstate(over="ignore"):
            return float((pop * np.exp(-beta_value * t)).sum())

    interval = Interval(weighted(beta.value), weighted(beta.high),
                        weighted(beta.low))
    detail = {"lon": blocks["lon"].to_numpy(), "lat": blocks["lat"].to_numpy(),
              "pop": pop, "minutes": t,
              "weight": pop * np.exp(-beta.value * t)}
    return interval, detail


def _corridor_layer(line_4326) -> dict:
    from shapely.geometry import mapping
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": mapping(line_4326.simplify(0.00005)),
        "properties": {"role": "bike_corridor"},
    }]}


def _capture_points_layer(businesses, alloc) -> dict:
    features = []
    for i, row in businesses.iterrows():
        usd = float(alloc[i])
        if usd < MIN_POINT_USD:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(float(row.geometry.x), 6),
                                         round(float(row.geometry.y), 6)]},
            "properties": {"name": str(row.get("name", "")),
                           "bike_new_usd": round(usd)},
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
                           "bike_min": round(float(detail["minutes"][i]), 1)},
        })
    return {"type": "FeatureCollection", "features": features}


def run(spec, ctx, prior=None):
    if spec.project_type != "street_multimodal":
        return _not_computed(
            f"bike_lane module applies to street_multimodal projects "
            f"(this project is {spec.project_type})")
    line = _corridor_line(spec)
    if line is None:
        return _not_computed(
            "no corridor line geometry — resolve the corridor at extract/"
            "confirm or supply one with `impact-confirm --geometry`")
    if not _has_bike_facility(spec):
        return _not_computed(
            "no bike facility among the corridor facilities — add e.g. "
            "'protected bike lane' to proposed.corridor.facilities in the "
            "spec YAML if the documents support it")

    a = _assumptions(ctx)
    notes = [
        "Corridor bike capture is a screening estimate: a bike-access "
        "mechanism (decay-weighted catchment x latent bike trips x induced "
        "visit share x per-trip spending) whose induced-share bounds are "
        "calibrated to observed corridor natural experiments. It ranks "
        "plausible magnitudes with sensitivity bounds — it is not a "
        "prediction.",
    ]

    corridor_nodes = _corridor_nodes(ctx, line)
    if not corridor_nodes:
        return _not_computed("the corridor line touches no bike-network nodes "
                             "— check the resolved geometry")
    catchment, detail = _catchment(ctx, corridor_nodes, a["beta_bike"])
    businesses = _corridor_businesses(ctx, line)

    trips = (catchment
             * Interval.from_assumption(a["bike_trips_per_resident_day"])
             * Interval.from_assumption(a["induced_corridor_visit_share"]))

    osm_prov = prov("OpenStreetMap bike network + Census 2020 block population",
                    "https://www.openstreetmap.org", "current",
                    f"multi-source Dijkstra from {len(corridor_nodes)} corridor "
                    "nodes; exp(-beta_bike * t) decay weight per block")
    clifton_prov = prov(
        "Clifton et al. (2013), Consumer Behavior and Travel Choices "
        "(PSU/NITC), Table 3 cyclist expenditures per trip",
        "https://nitc.trec.pdx.edu/research/project/411", "2013")

    metrics: list[MetricValue] = []
    metrics.append(metric(
        "Bike catchment population (decay-weighted)", catchment, "residents",
        [osm_prov], [a["beta_bike"]],
        "sum over census blocks of pop x exp(-beta_bike x bike minutes to "
        "the corridor); beta_bike is a network parameter, so this metric has "
        "no slider terms (changing it requires a full rerun)"))
    metrics.append(metric(
        "Induced bike visits per day (corridor)", trips, "visits/day",
        [osm_prov, clifton_prov],
        [a["beta_bike"], a["bike_trips_per_resident_day"],
         a["induced_corridor_visit_share"]],
        "catchment population x latent bike trips per resident-day x induced "
        "corridor visit share",
        adjust=[term(trips.value, bike_trips_per_resident_day=1.0,
                     induced_corridor_visit_share=1.0)]))

    layers = {
        "bike_corridor": _corridor_layer(line),
        "bike_catchment": _catchment_layer(detail),
        "city_boundary": _city_boundary_layer(ctx.boundary),
    }

    if len(businesses) == 0:
        notes.append("No retail businesses within "
                     f"{CORRIDOR_POI_BUFFER_M:.0f} m of the corridor — the "
                     "spending channel is not computed; the catchment metrics "
                     "above still describe who the facility newly serves.")
        result = ModuleResult(module="bike_lane", metrics=metrics,
                              map_layer_labels=list(layers),
                              narrative_notes=notes,
                              assumptions=list(a.values()))
        return result, layers

    # spending: split induced visits over the corridor's establishment-group
    # mix (POI count shares), priced by the Clifton per-trip means
    import numpy as np
    groups = businesses["taxonomy"].map(_spend_group)
    mix = {g: float((groups == g).mean()) for g in SPEND_GROUPS}
    spend_by_group, group_terms, total = _spending(trips, mix, a)

    spend_assumptions = [a["beta_bike"], a["bike_trips_per_resident_day"],
                         a["induced_corridor_visit_share"],
                         *[a[f"bike_spend_per_trip_{g}"] for g in SPEND_GROUPS
                           if mix[g] > 0]]
    mechanism = ("induced daily bike visits x corridor establishment-group "
                 "mix (POI count shares) x cyclist spend per trip x 365; "
                 "allocated evenly within each group")
    metrics.append(metric(
        "New annual spending at corridor businesses", total, "$/yr",
        [clifton_prov, osm_prov], spend_assumptions, mechanism, headline=True,
        adjust=group_terms))
    for g, s in spend_by_group.items():
        metrics.append(metric(
            f"New annual corridor spending: {g}", s, "$/yr",
            [clifton_prov], [a[f"bike_spend_per_trip_{g}"],
                             a["induced_corridor_visit_share"]],
            mechanism,
            adjust=[term(s.value, bike_trips_per_resident_day=1.0,
                         induced_corridor_visit_share=1.0,
                         **{f"bike_spend_per_trip_{g}": 1.0})]))

    # per-business allocation (even within group) for the map + top names
    alloc = np.zeros(len(businesses))
    for g, s in spend_by_group.items():
        members = np.where((groups == g).to_numpy())[0]
        if len(members):
            alloc[members] = s.value / len(members)
    top = np.argsort(-alloc)[:5]
    for i in top:
        if alloc[i] <= 0:
            continue
        name = str(businesses.iloc[i].get("name", "")) or "unnamed business"
        g = _spend_group(businesses.iloc[i]["taxonomy"])
        s = spend_by_group[g]
        members = int((groups == g).sum())
        metrics.append(MetricValue(
            name=f"Annual corridor capture: {name}",
            value=float(alloc[i]), unit="$/yr",
            low=s.low / members, high=s.high / members,
            provenance=[clifton_prov], method=mechanism,
            assumptions=["induced_corridor_visit_share",
                         f"bike_spend_per_trip_{g}"],
        ))

    # calibration diagnostic: implied sales uplift across corridor businesses
    # vs. a rough baseline (module constants, labeled as such) — flags when
    # the mechanism escapes the corridor-study envelope
    baseline = len(businesses) * DIAG_SUITE_SQFT * DIAG_SALES_PER_SQFT
    uplift = total * (1.0 / baseline)
    metrics.append(metric(
        "Implied corridor sales uplift (diagnostic)", uplift,
        "fraction of baseline sales",
        [prov("Diagnostic baseline: corridor business count x typical "
              f"{DIAG_SUITE_SQFT:.0f} sqft suite x ${DIAG_SALES_PER_SQFT:.0f}"
              "/sqft gross sales", "", "screening constant")],
        spend_assumptions,
        "new corridor spending / rough baseline corridor sales; compares the "
        "mechanism's output to the corridor natural-experiment envelope "
        "(roughly 0-50% observed sales/employment gains)"))
    if uplift.value > DIAG_UPLIFT_CEILING:
        notes.append(
            f"CONSISTENCY FLAG: implied corridor sales uplift is "
            f"{uplift.value:.0%}, above the ~{DIAG_UPLIFT_CEILING:.0%} ceiling "
            "observed in corridor natural experiments (Liu & Shi 2020) — the "
            "catchment or induced-share assumptions are too aggressive for "
            "this corridor; revisit them before leaning on the spending "
            "figures.")

    layers["bike_capture_points"] = _capture_points_layer(businesses, alloc)

    result = ModuleResult(module="bike_lane", metrics=metrics,
                          map_layer_labels=list(layers),
                          narrative_notes=notes,
                          assumptions=list(a.values()))
    return result, layers
