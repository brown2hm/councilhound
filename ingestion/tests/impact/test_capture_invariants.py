"""Module-level Huff invariants on a synthetic destination table (numpy only):
total capture = total spend, and total per-mode (walk/bike) dollars bounded
by spend x that mode's preference — the brief's M3 acceptance pinned at the
module seam, extended for the walk/bike/drive joint choice."""
import numpy as np
import pytest

from councilhound.impact.modules.economic import RETAIL_CLASSES, _assumptions, _capture
from councilhound.impact.provenance import Interval


class _Ctx:
    pass  # _assumptions doesn't touch ctx


def _dest():
    """Six POIs (one per class) at varied times + the own-retail entry."""
    taxonomy = np.append(np.array(RETAIL_CLASSES, dtype=object), "__own__")
    return {
        "n": len(taxonomy),
        "taxonomy": taxonomy,
        "walk_min": np.array([5.0, 8.0, 12.0, 3.0, 20.0, 15.0, 0.0]),
        "drive_min": np.array([2.0, 3.0, 4.0, 1.5, 6.0, 5.0, 0.0]),
        "bike_min": np.array([1.7, 2.7, 4.0, 1.0, 6.7, 5.0, 0.0]),
        "in_city": np.array([True, True, False, True, False, True, True]),
        "own_retail_equiv": {"restaurant_bar": 2.0, "retail_convenience": 1.0},
    }


def _spend():
    return {c: Interval(100_000.0 * (i + 1), 80_000.0 * (i + 1), 120_000.0 * (i + 1))
            for i, c in enumerate(RETAIL_CLASSES)}


def test_capture_sums_to_spend_per_slot():
    a = _assumptions(_Ctx())
    spend = _spend()
    capture, walk_dollars, bike_dollars, _, _, _ = _capture(_dest(), spend, a)
    for slot, pick in ((0, "value"), (1, "low"), (2, "high")):
        expected = sum(getattr(spend[c], pick) for c in RETAIL_CLASSES)
        assert capture[slot].sum() == pytest.approx(expected, rel=1e-9)


def test_walk_dollars_bounded_by_mode_split_budget():
    """Joint mode choice: walking loses to driving with distance, so walk
    dollars stay strictly below spend x walk preference when travel costs
    anything…"""
    from councilhound.impact.modules.economic import _walk_share_for

    a = _assumptions(_Ctx())
    spend = _spend()
    _, walk_dollars, _, _, _, _ = _capture(_dest(), spend, a)
    budget = sum(spend[c].value * _walk_share_for(c, a).value for c in RETAIL_CLASSES)
    assert 0 < walk_dollars[0].sum() < budget


def test_bike_dollars_decrease_as_bike_times_grow():
    """Bike has NO walk-style budget bound: at mid distances it wins trips
    from the drive remainder (bike utility decays slower than drive there),
    which is the intended 3-4x-reach behavior. The pinned bike invariant is
    monotonicity instead: longer bike times mean strictly fewer bike
    dollars, with the lost share going back to the other modes."""
    a = _assumptions(_Ctx())
    spend = _spend()
    _, _, bike_near, _, _, _ = _capture(_dest(), spend, a)
    slow = _dest()
    slow["bike_min"] = slow["bike_min"] * 3.0
    capture_slow, _, bike_far, _, _, _ = _capture(slow, spend, a)
    assert 0 < bike_far[0].sum() < bike_near[0].sum()
    # conservation is untouched by the slowdown
    expected = sum(spend[c].value for c in RETAIL_CLASSES)
    assert capture_slow[0].sum() == pytest.approx(expected, rel=1e-9)


def test_mode_dollars_equal_budget_at_zero_travel_time():
    """…and each mode's dollars equal its budget exactly when every
    destination is at t=0 (mode preference is defined as the zero-impedance
    mode share)."""
    from councilhound.impact.modules.economic import _bike_share_for, _walk_share_for

    a = _assumptions(_Ctx())
    spend = _spend()
    dest = _dest()
    dest["walk_min"][:] = 0.0
    dest["drive_min"][:] = 0.0
    dest["bike_min"][:] = 0.0
    _, walk_dollars, bike_dollars, _, _, _ = _capture(dest, spend, a)
    walk_budget = sum(spend[c].value * _walk_share_for(c, a).value for c in RETAIL_CLASSES)
    bike_budget = sum(spend[c].value * _bike_share_for(c, a).value for c in RETAIL_CLASSES)
    assert walk_dollars[0].sum() == pytest.approx(walk_budget, rel=1e-9)
    assert bike_dollars[0].sum() == pytest.approx(bike_budget, rel=1e-9)


def test_far_destinations_get_effectively_no_walk_or_bike_dollars():
    a = _assumptions(_Ctx())
    dest = _dest()
    dest["walk_min"][2] = 90.0  # a 90-minute walk; drive stays short
    dest["bike_min"][2] = 60.0  # an hour's ride
    capture, walk_dollars, bike_dollars, _, _, _ = _capture(dest, _spend(), a)
    # that business still captures (by car) but walk-/bike-in are slivers
    assert capture[0][2] > 0
    assert walk_dollars[0][2] < 0.01 * capture[0][2]
    assert bike_dollars[0][2] < 0.01 * capture[0][2]


def test_mode_dollars_never_exceed_capture_totals():
    a = _assumptions(_Ctx())
    capture, walk_dollars, bike_dollars, _, _, _ = _capture(_dest(), _spend(), a)
    assert walk_dollars[0].sum() < capture[0].sum()
    assert bike_dollars[0].sum() < capture[0].sum()
    assert walk_dollars[0].sum() + bike_dollars[0].sum() < capture[0].sum()


def test_walk_and_bike_shares_leave_positive_drive_remainder():
    """The bike preference is carved from the drive remainder: even at the
    high bounds, walk + bike must leave drive a positive share in every
    category — otherwise the joint choice's third mode goes negative."""
    from councilhound.impact.modules.economic import _bike_share_for, _walk_share_for

    a = _assumptions(_Ctx())
    for category in RETAIL_CLASSES:
        ws, bs = _walk_share_for(category, a), _bike_share_for(category, a)
        assert ws.high + bs.high < 1.0
