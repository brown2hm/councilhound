"""Huff math against a hand-computed 3-destination toy case (numpy only)."""
import math

import numpy as np
import pytest

from councilhound.impact.modules import huff
from councilhound.impact.modules.ces_shares import (
    CATEGORY_SPEND, CES_AVG_PRETAX_INCOME, category_spend_per_household,
)


def test_toy_three_destination_case():
    # A = [4, 9, 1], walk times = [5, 10, 20] min, alpha=1, beta=0.1
    A = np.array([4.0, 9.0, 1.0])
    t = np.array([5.0, 10.0, 20.0])
    u = [4 * math.exp(-0.5), 9 * math.exp(-1.0), 1 * math.exp(-2.0)]
    expected = np.array(u) / sum(u)
    p = huff.huff_probabilities(A, t, alpha=1.0, beta=0.10)
    assert p == pytest.approx(expected, rel=1e-12)
    assert p.sum() == pytest.approx(1.0)


def test_zero_attractiveness_gets_zero_probability():
    p = huff.huff_probabilities([0.0, 5.0], [1.0, 100.0])
    assert p[0] == 0.0
    assert p[1] == pytest.approx(1.0)


def test_unreachable_destination_infinite_time():
    p = huff.huff_probabilities([5.0, 5.0], [np.inf, 10.0])
    assert p[0] == 0.0
    assert p[1] == pytest.approx(1.0)


def test_all_unreachable_returns_zeros():
    p = huff.huff_probabilities([1.0, 1.0], [np.inf, np.inf])
    assert p.sum() == 0.0


def test_blend_preserves_total_probability():
    A = np.array([3.0, 2.0, 7.0])
    walk = np.array([4.0, 8.0, 25.0])
    drive = np.array([2.0, 3.0, 6.0])
    p = huff.blended_probabilities(A, walk, drive, walk_share=0.6)
    assert p.sum() == pytest.approx(1.0)


def test_blend_falls_back_when_one_mode_unreachable():
    A = np.array([1.0, 1.0])
    p = huff.blended_probabilities(A, np.array([np.inf, np.inf]),
                                   np.array([5.0, 10.0]), walk_share=0.6)
    assert p.sum() == pytest.approx(1.0)  # pure drive


def test_allocation_sums_to_category_spend():
    A = np.array([4.0, 9.0, 1.0])
    t = np.array([5.0, 10.0, 20.0])
    p = huff.huff_probabilities(A, t)
    flows = huff.allocate_spend(1_000_000.0, p)
    assert flows.sum() == pytest.approx(1_000_000.0)


def test_ces_income_scaling():
    spend = category_spend_per_household(CES_AVG_PRETAX_INCOME)  # scale = 1
    assert spend["grocery"] == pytest.approx(CATEGORY_SPEND["grocery"][0])
    double = category_spend_per_household(2 * CES_AVG_PRETAX_INCOME)
    assert double["restaurant_bar"] == pytest.approx(2 * CATEGORY_SPEND["restaurant_bar"][0])
