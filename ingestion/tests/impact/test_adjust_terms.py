"""Adjustment-term model: the exact client-side recompute published with each
metric for the interactive assumptions page.

Two layers of guarantees:
- algebra helpers preserve values and compose exponents correctly;
- the per-category capture decomposition sums to the aggregate capture, and
  evaluating terms at shifted assumption centrals reproduces a direct rerun
  (Huff probabilities are independent of the demand-side assumptions, so the
  power-law model is exact, not an approximation).

evaluate.py additionally asserts sum(terms) == value on every real run.
"""
import numpy as np
import pytest

from councilhound.impact.modules import ces_shares
from councilhound.impact.modules.economic import RETAIL_CLASSES, _assumptions, _capture
from councilhound.impact.provenance import term, terms_pow_extend, terms_scale, terms_value
from tests.impact.test_capture_invariants import _dest, _spend


def _eval_terms(terms, baseline, adjusted):
    """The frontend's recompute: sum of value x prod((a/a0)^e)."""
    total = 0.0
    for t in terms:
        factor = 1.0
        for key, e in t.exps.items():
            factor *= (adjusted.get(key, baseline[key]) / baseline[key]) ** e
        total += t.value * factor
    return total


def test_terms_algebra_preserves_value_and_exponents():
    ts = [term(100.0, occupancy_rate=1.0), term(50.0, ces_scale=1.0)]
    assert terms_value(ts) == 150.0

    scaled = terms_scale(ts, 0.5)
    assert terms_value(scaled) == 75.0
    assert scaled[0].exps == {"occupancy_rate": 1.0}  # exponents untouched

    extended = terms_pow_extend(ts, occupancy_rate=-1.0, marginal_cost_factor=1.0)
    assert terms_value(extended) == 150.0  # extension never changes the value
    assert extended[0].exps["occupancy_rate"] == 0.0  # 1 + (-1)
    assert extended[0].exps["marginal_cost_factor"] == 1.0
    assert extended[1].exps == {"ces_scale": 1.0, "occupancy_rate": -1.0,
                                "marginal_cost_factor": 1.0}


def test_per_category_capture_decomposition_sums_to_total():
    a = _assumptions(None)
    capture, walk, bike, _, _, by_cat = _capture(_dest(), _spend(), a)
    cat_total = sum(by_cat["capture"][c] for c in RETAIL_CLASSES)
    walk_total = sum(by_cat["walk"][c] for c in RETAIL_CLASSES)
    bike_total = sum(by_cat["bike"][c] for c in RETAIL_CLASSES)
    np.testing.assert_allclose(cat_total, capture[0], rtol=1e-9)
    np.testing.assert_allclose(walk_total, walk[0], rtol=1e-9)
    np.testing.assert_allclose(bike_total, bike[0], rtol=1e-9)


def test_demand_terms_reproduce_direct_rerun_at_shifted_assumptions():
    """Scale occupancy/ces/premium, rerun _capture directly, and check the
    power-law term model lands on the same aggregate capture."""
    a = _assumptions(None)
    dest = _dest()
    spend = _spend()
    _, _, _, _, _, by_cat = _capture(dest, spend, a)

    baseline = {"occupancy_rate": a["occupancy_rate"].value,
                "ces_scale": a["ces_scale"].value,
                "income_premium_new_construction":
                    a["income_premium_new_construction"].value}
    adjusted = {"occupancy_rate": baseline["occupancy_rate"] * 0.93,
                "ces_scale": baseline["ces_scale"] * 1.10,
                "income_premium_new_construction":
                    baseline["income_premium_new_construction"] * 1.08}

    terms = []
    bike_terms = []
    shifted_spend = {}
    for category in RETAIL_CLASSES:
        eps = ces_shares.CATEGORY_ELASTICITY[category]
        terms.append(term(float(by_cat["capture"][category].sum()),
                          occupancy_rate=1.0, ces_scale=1.0,
                          income_premium_new_construction=eps))
        bike_terms.append(term(float(by_cat["bike"][category].sum()),
                               occupancy_rate=1.0, ces_scale=1.0,
                               income_premium_new_construction=eps))
        # the demand a direct rerun would see under the shifted assumptions
        factor = ((adjusted["occupancy_rate"] / baseline["occupancy_rate"])
                  * (adjusted["ces_scale"] / baseline["ces_scale"])
                  * (adjusted["income_premium_new_construction"]
                     / baseline["income_premium_new_construction"]) ** eps)
        shifted_spend[category] = spend[category].scale(factor)

    direct, _, direct_bike, _, _, _ = _capture(dest, shifted_spend, a)
    assert _eval_terms(terms, baseline, adjusted) == pytest.approx(
        float(direct[0].sum()), rel=1e-9)
    # the bike-arriving decomposition is the same power law: mode
    # probabilities are independent of the demand-side assumptions
    assert _eval_terms(bike_terms, baseline, adjusted) == pytest.approx(
        float(direct_bike[0].sum()), rel=1e-9)


def test_labels_survive_scale_and_extend():
    """Composite metrics scale and negate borrowed terms; a term that loses
    its label on the way into a net becomes an unreadable ledger row."""
    from councilhound.impact.provenance import terms_relabel

    ts = [term(100.0, "Revenue line", occupancy_rate=1.0), term(50.0)]
    assert [t.label for t in terms_scale(ts, -1.0)] == ["Revenue line", None]
    assert [t.label for t in terms_pow_extend(ts, ces_scale=1.0)] == ["Revenue line", None]
    # negation preserves the name but flips the sign — that is what puts a
    # cost on the subtract side of the ledger with its identity intact
    assert terms_scale(ts, -1.0)[0].value == -100.0
    # relabel stamps a borrowed decomposition with the consumer's name
    assert [t.label for t in terms_relabel(ts, "School cost")] == ["School cost", "School cost"]


def test_label_keyword_cannot_collide_with_an_assumption_key():
    """`_label` is positional-or-underscored precisely so a key named
    'label' would still land in exps, not in the term's name."""
    t = term(10.0, label=2.0)
    assert t.label is None
    assert t.exps == {"label": 2.0}


def test_capture_terms_carry_category_labels():
    """The per-category pieces of the mode metrics are the ledger rows."""
    from councilhound.impact.modules.economic import CATEGORY_LABELS
    a = _assumptions(None)
    _, _, _, _, _, by_cat = _capture(_dest(), _spend(), a)
    labelled = [term(float(by_cat["walk"][c].sum()), CATEGORY_LABELS[c])
                for c in RETAIL_CLASSES]
    assert all(t.label for t in labelled)
    assert "Restaurants & bars" in [t.label for t in labelled]
