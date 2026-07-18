"""Exact marginal foot-traffic flows on a hand-computed toy graph."""
import math

import pytest

nx = pytest.importorskip("networkx")

from councilhound.impact.modules.economic import marginal_edge_flows  # noqa: E402


def _toy_graph():
    """O -> M -> D1 and O -> M -> D2: both destinations share edge (O, M)."""
    g = nx.MultiDiGraph()
    for u, v, minutes in [("O", "M", 5.0), ("M", "D1", 5.0), ("M", "D2", 5.0),
                          ("M", "D3", 20.0)]:
        g.add_edge(u, v, travel_min=minutes)
    return g


def test_flows_split_by_weight_at_equal_times():
    g = _toy_graph()
    # D1 and D2 at equal times: decay cancels, split purely by weight 3:1
    flows = marginal_edge_flows(g, "O", {"D1": 3.0, "D2": 1.0}, beta=0.1,
                                total_trips=100.0)
    assert flows[("O", "M")] == pytest.approx(100.0)  # shared edge carries all
    assert flows[("M", "D1")] == pytest.approx(75.0)
    assert flows[("M", "D2")] == pytest.approx(25.0)


def test_distance_decay_shifts_flows():
    g = _toy_graph()
    # equal weights, D3 is 15 min farther than D1 (t=25 vs t=10)
    beta = 0.1
    flows = marginal_edge_flows(g, "O", {"D1": 1.0, "D3": 1.0}, beta=beta,
                                total_trips=100.0)
    u1, u3 = math.exp(-beta * 10), math.exp(-beta * 25)
    assert flows[("M", "D1")] == pytest.approx(100.0 * u1 / (u1 + u3))
    assert flows[("M", "D3")] == pytest.approx(100.0 * u3 / (u1 + u3))
    assert flows[("O", "M")] == pytest.approx(100.0)


def test_unreachable_and_zero_weight_destinations_ignored():
    g = _toy_graph()
    g.add_node("island")
    flows = marginal_edge_flows(g, "O", {"D1": 1.0, "island": 5.0, "D2": 0.0},
                                beta=0.1, total_trips=60.0)
    assert flows[("M", "D1")] == pytest.approx(60.0)
    assert ("M", "D2") not in flows


def test_origin_excluded_and_empty_weights_yield_no_flows():
    g = _toy_graph()
    assert marginal_edge_flows(g, "O", {"O": 5.0}, beta=0.1, total_trips=10.0) == {}
    assert marginal_edge_flows(g, "O", {}, beta=0.1, total_trips=10.0) == {}


def test_deterministic():
    g = _toy_graph()
    kwargs = dict(dest_weights={"D1": 2.0, "D2": 1.0, "D3": 4.0},
                  beta=0.12, total_trips=123.4)
    assert (marginal_edge_flows(g, "O", **kwargs)
            == marginal_edge_flows(g, "O", **kwargs))
