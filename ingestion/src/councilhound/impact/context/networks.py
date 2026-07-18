"""OSMnx street networks + node-level context weights.

Walk and drive graphs are built from the city boundary buffered ~3 km (so
isochrones and Huff impedances don't hit an artificial edge at the city
line), stored as GraphML. Node weights (population within 400 m, POI counts
by taxonomy class within 400 m) feed the foot-traffic betweenness sampling
in the economic module; they're cached as a parquet keyed off the graph +
census vintages recorded in the manifest.
"""
from __future__ import annotations

import logging
from datetime import date

from councilhound.impact.cache import Manifest, context_dir
from councilhound.impact.provenance import prov

log = logging.getLogger(__name__)

BUFFER_M = 3_000
WALK_SPEED_KMH = 4.8  # brief §6.2 walking speed


def _graph_path(slug: str, kind: str):
    return context_dir(slug) / f"{kind}_graph.graphml"


def load_graph(ctx, kind: str):
    """kind: 'walk' | 'drive'. Built once, then loaded from GraphML."""
    import osmnx as ox

    slug = ctx.cfg.slug
    path = _graph_path(slug, kind)
    if not path.exists():
        log.info("building %s graph (boundary + %dm buffer)...", kind, BUFFER_M)
        # buffer in the projected CRS, then back to 4326 for the Overpass query
        import geopandas as gpd
        boundary = gpd.GeoSeries([ctx.boundary], crs="EPSG:4326")
        buffered = boundary.to_crs(ctx.cfg.crs_projected).buffer(BUFFER_M * 3.28084)
        polygon = buffered.to_crs("EPSG:4326").iloc[0]
        graph = ox.graph_from_polygon(polygon, network_type=kind, simplify=True)
        # travel time per edge: minutes, by mode
        if kind == "walk":
            for _, _, data in graph.edges(data=True):
                data["travel_min"] = (data.get("length", 0) / 1000) / WALK_SPEED_KMH * 60
        else:
            graph = ox.routing.add_edge_speeds(graph)
            graph = ox.routing.add_edge_travel_times(graph)
            for _, _, data in graph.edges(data=True):
                data["travel_min"] = data.get("travel_time", 0) / 60
        ox.save_graphml(graph, path)
        Manifest(slug).record(
            f"{kind}_graph",
            prov(f"OpenStreetMap via OSMnx ({kind} network)",
                 "https://www.openstreetmap.org", date.today().isoformat(),
                 f"boundary buffered {BUFFER_M} m; travel_min on edges").model_dump(),
            {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges()},
        )
        return graph
    return ox.load_graphml(path)


def load_node_weights(ctx):
    """DataFrame indexed by walk-graph node id: population within 400 m
    (area-apportioned from block groups) and POI count within 400 m per
    taxonomy class. Used as trip-endpoint weights for betweenness sampling."""
    import geopandas as gpd
    import osmnx as ox
    import pandas as pd

    slug = ctx.cfg.slug
    path = context_dir(slug) / "node_weights.parquet"
    if path.exists():
        return pd.read_parquet(path)

    graph = ctx.walk_graph
    crs = ctx.cfg.crs_projected
    nodes = ox.convert.graph_to_gdfs(graph, edges=False)[["geometry"]].to_crs(crs)
    discs = nodes.copy()
    discs["geometry"] = discs.geometry.buffer(400 * 3.28084)  # 400 m in US ft

    # population: share of each block group's population proportional to the
    # fraction of the BG's area covered by the node's 400 m disc
    bg = ctx.census_bg.to_crs(crs)
    bg["bg_area"] = bg.geometry.area
    inter = gpd.overlay(
        discs.reset_index()[["osmid", "geometry"]],
        bg[["geoid", "population", "bg_area", "geometry"]],
        how="intersection", keep_geom_type=False,
    )
    inter["pop_share"] = inter["population"] * inter.geometry.area / inter["bg_area"]
    pop = inter.groupby("osmid")["pop_share"].sum().rename("pop_400m")

    pois = ctx.pois.to_crs(crs)
    joined = gpd.sjoin(pois[["taxonomy", "geometry"]], discs.reset_index()[["osmid", "geometry"]],
                       predicate="within")
    poi_counts = (joined.groupby(["osmid", "taxonomy"]).size().unstack(fill_value=0)
                  .add_prefix("poi_"))

    out = pd.concat([pop, poi_counts], axis=1).reindex(nodes.index).fillna(0)
    out.to_parquet(path)
    Manifest(slug).record(
        "node_weights",
        prov("Derived: ACS block groups + merged POI layer over OSM walk nodes",
             "(derived)", date.today().isoformat(),
             "population area-apportioned to 400 m node discs").model_dump(),
        {"nodes": len(out), "total_pop_weight": float(out["pop_400m"].sum())},
    )
    return out
