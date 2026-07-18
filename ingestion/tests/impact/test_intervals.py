"""Interval arithmetic + sensitivity ranking (no heavy deps)."""
import pytest

from councilhound.impact.provenance import Interval, rank_assumptions_by_sensitivity
from councilhound.impact.schemas import Assumption


def test_point_and_ordering():
    with pytest.raises(ValueError):
        Interval(1.0, 2.0, 0.5)
    p = Interval.point(3.0)
    assert (p.low, p.value, p.high) == (3.0, 3.0, 3.0)


def test_add_sub_mul_div():
    a = Interval(10, 8, 12)
    b = Interval(2, 1, 3)
    s = a + b
    assert (s.low, s.value, s.high) == (9, 12, 15)
    d = a - b
    assert (d.low, d.value, d.high) == (5, 8, 11)
    m = a * b
    assert (m.low, m.value, m.high) == (8, 20, 36)
    q = a / b
    assert (q.low, q.value, q.high) == (8 / 3, 5, 12)


def test_scalar_ops_and_zero_division():
    a = Interval(10, 8, 12)
    assert (a * 2).high == 24
    assert (2 * a).low == 16
    assert (a + 1).value == 11
    with pytest.raises(ZeroDivisionError):
        a / Interval(0.5, -1, 1)


def test_chained_formula_propagation():
    # new_residents = units * occupancy * hh_size — bounds compound
    units = Interval.point(261)
    occ = Interval(0.95, 0.90, 0.97)
    hh = Interval(2.0, 1.7, 2.3)
    res = units * occ * hh
    assert res.value == pytest.approx(261 * 0.95 * 2.0)
    assert res.low == pytest.approx(261 * 0.90 * 1.7)
    assert res.high == pytest.approx(261 * 0.97 * 2.3)


def test_power_monotonic_endpoints():
    r = Interval(1.5, 1.2, 1.8)
    p = r ** 0.45
    assert p.value == pytest.approx(1.5 ** 0.45)
    assert p.low == pytest.approx(1.2 ** 0.45)
    assert p.high == pytest.approx(1.8 ** 0.45)
    assert (r ** 0).value == 1.0
    with pytest.raises(ValueError):
        Interval(0.5, -0.1, 1.0) ** 0.5
    with pytest.raises(ValueError):
        r ** -1.0


def test_sensitivity_ranking_orders_by_impact():
    a1 = Assumption(key="occupancy", value=0.95, low=0.90, high=0.97, basis="b", rationale="r")
    a2 = Assumption(key="hh_size", value=2.0, low=1.7, high=2.3, basis="b", rationale="r")
    defaults = {"occupancy": 0.95, "hh_size": 2.0}

    def recompute(key, value):
        vals = dict(defaults, **{key: value})
        return 261 * vals["occupancy"] * vals["hh_size"]

    ranked = rank_assumptions_by_sensitivity(261 * 0.95 * 2.0, [a1, a2], recompute)
    # hh_size swings +/-0.3 around 2.0 (15%) vs occupancy's ~7% swing
    assert ranked[0][0].key == "hh_size"
    assert ranked[0][1] > ranked[1][1] > 0
