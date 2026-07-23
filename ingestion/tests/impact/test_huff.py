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


def test_joint_mode_probabilities_sum_to_one():
    A = np.array([3.0, 2.0, 7.0])
    walk = np.array([4.0, 8.0, 25.0])
    drive = np.array([2.0, 3.0, 6.0])
    p_total, p_walk = huff.joint_mode_probabilities(A, walk, drive, walk_pref=0.6)
    assert p_total.sum() == pytest.approx(1.0)
    assert np.all(p_walk <= p_total + 1e-12)


def test_joint_mode_walk_share_at_zero_time_is_walk_pref():
    A = np.array([5.0])
    zero = np.array([0.0])
    p_total, p_walk = huff.joint_mode_probabilities(A, zero, zero, walk_pref=0.6)
    assert p_walk[0] / p_total[0] == pytest.approx(0.6)


def test_joint_mode_far_walk_loses_to_drive():
    A = np.array([1.0, 1.0])
    walk = np.array([1.0, 60.0])   # near vs. an hour's walk
    drive = np.array([3.0, 6.0])   # both a short drive
    p_total, p_walk = huff.joint_mode_probabilities(A, walk, drive, walk_pref=0.6)
    near_walk_share = p_walk[0] / p_total[0]
    far_walk_share = p_walk[1] / p_total[1]
    assert near_walk_share > 0.5
    assert far_walk_share < 0.02
    # the far destination still captures meaningfully overall — by car
    assert p_total[1] > 0.15


def test_multimode_probabilities_sum_to_one():
    A = np.array([3.0, 2.0, 7.0])
    modes = [(0.5, 0.10, np.array([4.0, 8.0, 25.0])),
             (0.1, 0.10, np.array([1.5, 3.0, 8.0])),
             (0.4, 0.15, np.array([2.0, 3.0, 6.0]))]
    p_total, per_mode = huff.joint_multimode_probabilities(A, modes)
    assert p_total.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(sum(per_mode), p_total, rtol=1e-12)


def test_multimode_shares_at_zero_time_equal_prefs():
    A = np.array([5.0])
    zero = np.array([0.0])
    modes = [(0.5, 0.10, zero), (0.1, 0.10, zero), (0.4, 0.15, zero)]
    p_total, per_mode = huff.joint_multimode_probabilities(A, modes)
    for (pref, _, _), p in zip(modes, per_mode):
        assert p[0] / p_total[0] == pytest.approx(pref)


def test_multimode_unreachable_mode_reallocates():
    A = np.array([1.0, 1.0])
    inf = np.array([np.inf, np.inf])
    near = np.array([2.0, 4.0])
    modes = [(0.5, 0.10, inf), (0.5, 0.15, near)]
    p_total, (p_dead, p_live) = huff.joint_multimode_probabilities(A, modes)
    assert p_total.sum() == pytest.approx(1.0)
    assert p_dead.sum() == 0.0
    assert p_live.sum() == pytest.approx(1.0)


def test_two_mode_wrapper_equals_direct_multimode_call():
    """joint_mode_probabilities must stay byte-equivalent to the n-mode
    generalization — the wrapper guarantee that keeps the pinned 2-mode
    tests meaningful."""
    A = np.array([3.0, 2.0, 7.0])
    walk = np.array([4.0, 8.0, 25.0])
    drive = np.array([2.0, 3.0, 6.0])
    p_total_w, p_walk_w = huff.joint_mode_probabilities(
        A, walk, drive, walk_pref=0.6, beta_walk=0.10, beta_drive=0.15)
    p_total_m, (p_walk_m, _) = huff.joint_multimode_probabilities(
        A, [(0.6, 0.10, walk), (0.4, 0.15, drive)])
    np.testing.assert_allclose(p_total_w, p_total_m, rtol=1e-15)
    np.testing.assert_allclose(p_walk_w, p_walk_m, rtol=1e-15)


def test_multimode_splitting_drive_pref_preserves_walk_probabilities():
    """Carving a bike mode out of the drive remainder must not change the
    walk mode's zero-impedance semantics: at t=0 everywhere, walk share
    stays exactly the walk pref."""
    A = np.array([2.0, 5.0])
    zero = np.array([0.0, 0.0])
    p_total, (p_walk, p_bike, p_drive) = huff.joint_multimode_probabilities(
        A, [(0.6, 0.10, zero), (0.02, 0.10, zero), (0.38, 0.15, zero)])
    np.testing.assert_allclose(p_walk / p_total, 0.6, rtol=1e-12)
    np.testing.assert_allclose(p_bike / p_total, 0.02, rtol=1e-12)


def test_ces_income_scaling():
    spend = category_spend_per_household(CES_AVG_PRETAX_INCOME)  # scale = 1
    assert spend["grocery"] == pytest.approx(CATEGORY_SPEND["grocery"][0])
    double = category_spend_per_household(2 * CES_AVG_PRETAX_INCOME)
    assert double["restaurant_bar"] == pytest.approx(2 * CATEGORY_SPEND["restaurant_bar"][0])
