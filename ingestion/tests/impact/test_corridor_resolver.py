"""Corridor resolution on a toy named-street graph: snap between cross
streets, suffix-tolerant name matching, full-street fallback, and the
failure modes that route users to the --geometry override."""
import pytest

nx = pytest.importorskip("networkx")
pytest.importorskip("shapely")

from shapely.geometry import box

from councilhound.impact.intake.corridors import (
    CorridorResolutionError, resolve_corridor)


class _Ctx:
    """Toy walk graph: Main Street runs west-east through nodes 1..5 at
    y=0 (100 m per edge); A Street crosses at node 2, B Street at node 4."""

    def __init__(self):
        g = nx.MultiDiGraph()
        step = 0.001  # ~100 m of longitude at this scale, cosmetically
        for i in range(1, 6):
            g.add_node(i, x=i * step, y=0.0)
        g.add_node(10, x=2 * step, y=0.001)
        g.add_node(11, x=4 * step, y=0.001)
        for u, v in ((1, 2), (2, 3), (3, 4), (4, 5)):
            g.add_edge(u, v, name="Main Street", length=100.0)
            g.add_edge(v, u, name="Main Street", length=100.0)  # reciprocal
        g.add_edge(2, 10, name="A Street", length=80.0)
        g.add_edge(10, 2, name="A Street", length=80.0)
        g.add_edge(4, 11, name="B Street", length=80.0)
        g.add_edge(11, 4, name="B Street", length=80.0)
        self.walk_graph = g
        self.boundary = box(0.0, -0.01, 0.0045, 0.01)  # nodes 1-4 inside


def test_resolve_between_cross_streets():
    geometry, length_ft, method = resolve_corridor(
        _Ctx(), "Main Street", "A Street", "B Street")
    assert method == "street_name_between_cross_streets"
    assert geometry["type"] == "LineString"
    # nodes 2 -> 3 -> 4: two 100 m edges
    assert length_ft == pytest.approx(200.0 * 3.28084, rel=1e-9)


def test_suffix_abbreviations_match_osm_names():
    """Council documents say 'Main St between A St and B St'; OSM spells
    streets out — the resolver's normalization must bridge that."""
    geometry, length_ft, method = resolve_corridor(_Ctx(), "Main St", "A St", "B St")
    assert method == "street_name_between_cross_streets"
    assert length_ft == pytest.approx(200.0 * 3.28084, rel=1e-9)


def test_unknown_street_raises_with_remediation():
    with pytest.raises(CorridorResolutionError, match="--geometry"):
        resolve_corridor(_Ctx(), "Oak Avenue", None, None)


def test_unknown_cross_street_raises():
    with pytest.raises(CorridorResolutionError, match="no street named"):
        resolve_corridor(_Ctx(), "Main Street", "A Street", "Nonexistent Road")


def test_name_gap_fallback_snaps_nearby_cross_street():
    """OSM often breaks a junction with unnamed crossing segments; a cross
    street whose named edges stop just short of the corridor must still
    resolve, via the nearest corridor node within tolerance."""
    ctx = _Ctx()
    g = ctx.walk_graph
    # "C Street" ends ~55 m north of Main Street node 3 (0.0005 deg lat)
    g.add_node(12, x=3 * 0.001, y=0.0005)
    g.add_node(13, x=3 * 0.001, y=0.002)
    g.add_edge(12, 13, name="C Street", length=150.0)
    g.add_edge(13, 12, name="C Street", length=150.0)
    geometry, length_ft, method = resolve_corridor(ctx, "Main Street", "A Street", "C Street")
    assert method == "street_name_between_cross_streets"
    # snapped endpoint is node 3: one 100 m edge from node 2
    assert length_ft == pytest.approx(100.0 * 3.28084, rel=1e-9)


def test_mid_street_tag_gap_is_bridged():
    """A renamed middle block (one-way pairs, route-number tags) must not
    break the corridor: the path bridges it over the full graph with the
    off-name penalty, and the bridged length still counts."""
    ctx = _Ctx()
    g = ctx.walk_graph
    for u, v in ((3, 4), (4, 3)):  # rename one middle block
        for key in list(g[u][v]):
            g[u][v][key]["name"] = "Route 236"
    geometry, length_ft, method = resolve_corridor(
        ctx, "Main Street", "A Street", "B Street")
    assert method == "street_name_between_cross_streets"
    assert length_ft == pytest.approx(200.0 * 3.28084, rel=1e-9)


def test_far_disconnected_cross_street_still_raises():
    ctx = _Ctx()
    g = ctx.walk_graph
    g.add_node(20, x=0.05, y=0.05)  # ~7 km away, beyond tolerance
    g.add_node(21, x=0.05, y=0.06)
    g.add_edge(20, 21, name="D Street", length=100.0)
    with pytest.raises(CorridorResolutionError, match="share no intersection"):
        resolve_corridor(ctx, "Main Street", "A Street", "D Street")


def test_full_street_fallback_clips_to_boundary():
    geometry, length_ft, method = resolve_corridor(_Ctx(), "Main Street", None, None)
    assert method == "street_name_full"
    assert geometry["type"] == "LineString"
    # node 5 sits outside the boundary box: 3 edges remain, not 4
    assert length_ft == pytest.approx(300.0 * 3.28084, rel=1e-9)
