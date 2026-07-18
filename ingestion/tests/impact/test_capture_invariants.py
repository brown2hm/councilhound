"""Module-level Huff invariants on a synthetic destination table (numpy only):
total capture = total spend, and total walk-arriving dollars = sum of
spend x walk share — the brief's M3 acceptance pinned at the module seam."""
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
        "in_city": np.array([True, True, False, True, False, True, True]),
        "own_retail_equiv": {"restaurant_bar": 2.0, "retail_convenience": 1.0},
    }


def _spend():
    return {c: Interval(100_000.0 * (i + 1), 80_000.0 * (i + 1), 120_000.0 * (i + 1))
            for i, c in enumerate(RETAIL_CLASSES)}


def test_capture_sums_to_spend_per_slot():
    a = _assumptions(_Ctx())
    spend = _spend()
    capture, walk_dollars, _, _ = _capture(_dest(), spend, a)
    for slot, pick in ((0, "value"), (1, "low"), (2, "high")):
        expected = sum(getattr(spend[c], pick) for c in RETAIL_CLASSES)
        assert capture[slot].sum() == pytest.approx(expected, rel=1e-9)


def test_walk_dollars_sum_to_spend_times_walk_share():
    from councilhound.impact.modules.economic import _walk_share_for

    a = _assumptions(_Ctx())
    spend = _spend()
    _, walk_dollars, _, _ = _capture(_dest(), spend, a)
    for slot, spend_pick, ws_pick in ((0, "value", "value"), (1, "low", "low"),
                                      (2, "high", "high")):
        expected = sum(getattr(spend[c], spend_pick)
                       * getattr(_walk_share_for(c, a), ws_pick)
                       for c in RETAIL_CLASSES)
        assert walk_dollars[slot].sum() == pytest.approx(expected, rel=1e-9)


def test_walk_dollars_never_exceed_capture_totals():
    a = _assumptions(_Ctx())
    capture, walk_dollars, _, _ = _capture(_dest(), _spend(), a)
    assert walk_dollars[0].sum() < capture[0].sum()
