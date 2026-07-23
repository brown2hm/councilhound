"""Corridor geometry resolution: match a named street (optionally bounded by
cross streets) to walk-graph edges and merge them into one LineString.

The walk graph is the reference network — it carries every named street,
including segments closed to cars — and the result lands on spec.geometry in
EPSG:4326 exactly like a parcel polygon does. The designed recovery path when
name-snapping fails is `impact-confirm --geometry <file.geojson>`, which
replaces this resolution entirely.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

SIMPLIFY_DEG = 0.00005
M_TO_FT = 3.28084
# OSM often interrupts a street's NAMED edges at junctions with unnamed
# crossing/plaza segments, so a cross street's named nodes can sit a short
# block away from the corridor. Within this tolerance the nearest corridor
# node stands in for the missing shared node; the human reviews the resolved
# length at confirm.
CROSS_TOLERANCE_M = 200.0
# Real corridors change OSM tags mid-street (one-way pairs, plaza segments,
# route-number renames), so the between-cross-streets path routes over the
# FULL walk graph with off-name edges penalized: it follows the physical
# street across tag gaps but never detours when named edges exist.
OFF_NAME_PENALTY = 5.0
MAX_OFF_NAME_FRACTION = 0.5

# common suffix abbreviations in council documents vs. OSM's spelled-out names
_SUFFIXES = {
    "st": "street", "rd": "road", "ave": "avenue", "av": "avenue",
    "blvd": "boulevard", "dr": "drive", "ln": "lane", "pkwy": "parkway",
    "hwy": "highway", "ct": "court", "pl": "place", "cir": "circle",
    "ter": "terrace", "sq": "square",
}


class CorridorResolutionError(Exception):
    """Raised when a corridor cannot be snapped to the street network; the
    message names the remediation (hand-supplied geometry at confirm)."""


def _norm(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return " ".join(_SUFFIXES.get(t, t) for t in tokens)


def _edge_streets(data) -> list[str]:
    name = data.get("name")
    if not name:
        return []
    return [s.strip() for s in (name if isinstance(name, list) else [name])
            if isinstance(s, str) and s.strip()]


def _nodes_touching(graph, street_norm: str) -> set:
    nodes: set = set()
    for u, v, data in graph.edges(data=True):
        if any(_norm(s) == street_norm for s in _edge_streets(data)):
            nodes.add(u)
            nodes.add(v)
    return nodes


def _endpoint_nodes(graph, named_nodes: set, street_name: str, cross: str) -> set:
    """Corridor nodes standing for the corridor/cross-street junction:
    exact shared nodes when the names meet, else the nearest corridor node
    within CROSS_TOLERANCE_M (the OSM name-gap fallback)."""
    import math

    cross_nodes = _nodes_touching(graph, _norm(cross))
    if not cross_nodes:
        raise CorridorResolutionError(
            f"no street named {cross!r} in the walk network — check the "
            "cross-street name or supply the corridor with "
            "`impact-confirm --geometry <file.geojson>`")
    exact = cross_nodes & named_nodes
    if exact:
        return exact
    best_node, best_m = None, float("inf")
    for n in named_nodes:
        x1, y1 = graph.nodes[n]["x"], graph.nodes[n]["y"]
        kx = math.cos(math.radians(y1)) * 111_320.0
        for c in cross_nodes:
            d = math.hypot((graph.nodes[c]["x"] - x1) * kx,
                           (graph.nodes[c]["y"] - y1) * 110_540.0)
            if d < best_m:
                best_node, best_m = n, d
    if best_m > CROSS_TOLERANCE_M:
        raise CorridorResolutionError(
            f"{street_name!r} and {cross!r} share no intersection in the walk "
            f"network (nearest named nodes are {best_m:,.0f} m apart) — check "
            "the cross-street names or supply the corridor with "
            "`impact-confirm --geometry <file.geojson>`")
    log.info("cross street %r joins %r via name-gap fallback (%.0f m)",
             cross, street_name, best_m)
    return {best_node}


def _edge_coords(graph, u, v, data) -> list[tuple[float, float]]:
    geom = data.get("geometry")
    if geom is not None:
        return list(geom.coords)
    return [(graph.nodes[u]["x"], graph.nodes[u]["y"]),
            (graph.nodes[v]["x"], graph.nodes[v]["y"])]


def resolve_corridor(ctx, street_name: str, from_street: str | None = None,
                     to_street: str | None = None) -> tuple[dict, float, str]:
    """(GeoJSON LineString EPSG:4326, length_ft, method).

    With both cross streets: shortest path along the named street between the
    two intersections. Without them: the whole named street clipped to the
    city boundary (method 'street_name_full', lower confidence — the human
    sees the method note at confirm)."""
    import networkx as nx
    from shapely.geometry import LineString, MultiLineString, mapping
    from shapely.ops import linemerge

    graph = ctx.walk_graph
    target = _norm(street_name)
    if not target:
        raise CorridorResolutionError("empty corridor street name")

    # undirected view of just the named street's edges, deduped across the
    # MultiDiGraph's reciprocal walk edges
    named = nx.Graph()
    for u, v, data in graph.edges(data=True):
        if not any(_norm(s) == target for s in _edge_streets(data)):
            continue
        length = float(data.get("length", 0.0))
        if named.has_edge(u, v) and named[u][v]["length"] <= length:
            continue
        named.add_edge(u, v, length=length,
                       coords=_edge_coords(graph, u, v, data))
    if named.number_of_edges() == 0:
        raise CorridorResolutionError(
            f"no street named {street_name!r} in the walk network — supply the "
            "corridor with `impact-confirm --geometry <file.geojson>`")

    if from_street and to_street:
        ends = []
        for cross in (from_street, to_street):
            ends.append(_endpoint_nodes(graph, set(named.nodes), street_name, cross))

        def on_name(data) -> bool:
            return any(_norm(s) == target for s in _edge_streets(data))

        def weight(u, v, keyed):
            # networkx hands callables the {key: attrs} dict of parallel
            # edges on multigraphs — take the cheapest parallel edge
            best_w = None
            for data in keyed.values():
                length = float(data.get("length", 0.0))
                w = length if on_name(data) else length * OFF_NAME_PENALTY
                if best_w is None or w < best_w:
                    best_w = w
            return best_w

        best = None  # (cost, path)
        for a in ends[0]:
            costs, paths = nx.single_source_dijkstra(graph, a, weight=weight)
            for b in ends[1]:
                if b in costs and (best is None or costs[b] < best[0]):
                    best = (costs[b], paths[b])
        if best is None or best[0] <= 0:
            raise CorridorResolutionError(
                f"the {from_street!r} and {to_street!r} intersections are not "
                f"connected along {street_name!r} — supply the corridor with "
                "`impact-confirm --geometry <file.geojson>`")
        _, path = best
        pieces, length_m, off_m = [], 0.0, 0.0
        for u, v in zip(path[:-1], path[1:]):
            # prefer the named parallel edge, then the shortest
            choice = None
            for data in (graph.get_edge_data(u, v) or {}).values():
                rank = (0 if on_name(data) else 1, float(data.get("length", 0.0)))
                if choice is None or rank < choice[0]:
                    choice = (rank, data)
            (off_rank, _), data = choice
            segment = float(data.get("length", 0.0))
            length_m += segment
            if off_rank:
                off_m += segment
            pieces.append(LineString(_edge_coords(graph, u, v, data)))
        if off_m > MAX_OFF_NAME_FRACTION * length_m:
            raise CorridorResolutionError(
                f"the resolved path between {from_street!r} and {to_street!r} "
                f"runs mostly off {street_name!r} ({off_m:,.0f} of "
                f"{length_m:,.0f} m) — check the names or supply the corridor "
                "with `impact-confirm --geometry <file.geojson>`")
        if off_m:
            log.info("bridged %.0f m of OSM name gaps along %r", off_m, street_name)
        method = "street_name_between_cross_streets"
    else:
        # whole named street, clipped to the city: keep nodes inside the
        # boundary, then take the longest connected run
        from shapely.geometry import Point
        inside = [n for n in named.nodes
                  if ctx.boundary.contains(Point(graph.nodes[n]["x"],
                                                 graph.nodes[n]["y"]))]
        sub = named.subgraph(inside)
        if sub.number_of_edges() == 0:
            raise CorridorResolutionError(
                f"street {street_name!r} exists but not inside the city boundary")
        component = max(nx.connected_components(sub),
                        key=lambda c: sum(d["length"]
                                          for _, _, d in sub.subgraph(c).edges(data=True)))
        comp = sub.subgraph(component)
        pieces = [LineString(d["coords"]) for _, _, d in comp.edges(data=True)]
        length_m = sum(d["length"] for _, _, d in comp.edges(data=True))
        method = "street_name_full"

    merged = linemerge(MultiLineString(pieces))
    if merged.geom_type == "MultiLineString":
        # disjoint digitization gaps: keep the longest merged run
        merged = max(merged.geoms, key=lambda g: g.length)
    merged = merged.simplify(SIMPLIFY_DEG)
    return mapping(merged), length_m * M_TO_FT, method
