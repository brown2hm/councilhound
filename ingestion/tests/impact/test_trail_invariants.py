"""Trail module invariants: gates, the literature-anchored assumption block,
the spending chain's interval ordering, access-point allocation conservation,
and the exact premium -> tax identity."""
import math

import pytest

from councilhound.impact.modules import trail
from councilhound.impact.provenance import Interval, term
from councilhound.impact.schemas import ProjectSpec


class _Ctx:
    pass  # _assumptions doesn't touch ctx


def _spec(**overrides):
    base = dict(
        name="Test trail", jurisdiction="fairfax_city_va",
        city_project_slug="test", source_url="https://example.gov",
        project_type="park", status="active",
        geometry={"type": "LineString",
                  "coordinates": [[-77.30, 38.85], [-77.29, 38.85]]},
    )
    base.update(overrides)
    return ProjectSpec(**base)


def test_gate_wrong_project_type():
    result, layers = trail.run(_spec(project_type="commercial"), None)
    assert result.module == "trail"
    assert result.metrics == []
    assert layers == {}
    assert any("Not computed" in n for n in result.narrative_notes)


def test_gate_requires_line_geometry():
    result, _ = trail.run(_spec(geometry=None), None)
    assert result.metrics == []
    assert any("linear trail geometry" in n for n in result.narrative_notes)


def test_street_multimodal_with_trail_facility_passes_gate():
    spec = _spec(project_type="street_multimodal", geometry=None,
                 proposed={"corridor": {"facilities": ["shared use path"]}})
    result, _ = trail.run(spec, None)
    # passes the project-type gate, then stops at the geometry gate
    assert any("linear trail geometry" in n for n in result.narrative_notes)


def test_trail_access_decay_anchor():
    """The Iacono trail-access curve: beta 0.333/km -> ~51% weight at 2 km,
    ~19% at 5 km (N=1,967, R2=0.93 — the reason this anchor was chosen)."""
    a = trail._assumptions(_Ctx())
    beta = a["beta_trail_access_km"].value
    assert beta == pytest.approx(0.333)
    assert math.exp(-beta * 2.0) == pytest.approx(0.514, abs=0.005)
    assert math.exp(-beta * 5.0) == pytest.approx(0.189, abs=0.005)


def test_assumption_anchors_match_transcribed_ncdot_values():
    """NCDOT Table 26 direct $/trip: ATT 6.24, LSC 7.27, Brevard 10.93 — all
    inside the spend band; Duck (25.00) excluded. Premium floor is zero."""
    a = trail._assumptions(_Ctx())
    spend = a["trail_spend_per_user_day"]
    for observed in (6.24, 7.27, 10.93):
        assert spend.low <= observed <= spend.high
    assert not (spend.low <= 25.00 <= spend.high)  # destination regime out
    assert a["trail_user_days_per_capita"].low <= 10 <= a["trail_user_days_per_capita"].high
    assert a["trail_property_premium"].low == 0.0
    assert a["trail_property_premium"].high == pytest.approx(0.05)


def test_spending_chain_interval_ordering():
    a = trail._assumptions(_Ctx())
    catchment = Interval(3_000.0, 2_000.0, 4_500.0)
    user_days = catchment * Interval.from_assumption(a["trail_user_days_per_capita"])
    spending = user_days * Interval.from_assumption(a["trail_spend_per_user_day"])
    for x in (user_days, spending):
        assert x.low <= x.value <= x.high
    assert spending.value == pytest.approx(
        catchment.value * a["trail_user_days_per_capita"].value
        * a["trail_spend_per_user_day"].value, rel=1e-12)


def test_access_point_allocation_conserves_totals():
    """The composition used in _catchment_and_capture: access-point shares
    (summing to 1) x per-access-point Huff probabilities (each summing to 1)
    must itself sum to 1, so allocate_spend conserves the channel total."""
    np = pytest.importorskip("numpy")
    from councilhound.impact.modules import huff

    attractiveness = np.ones(4)
    times = [np.array([2.0, 5.0, 9.0, 30.0]), np.array([7.0, 3.0, 4.0, 12.0])]
    shares = np.array([0.65, 0.35])
    combined = sum(share * huff.huff_probabilities(attractiveness, t, beta=0.10)
                   for share, t in zip(shares, times))
    assert combined.sum() == pytest.approx(1.0, rel=1e-12)
    alloc = huff.allocate_spend(500_000.0, combined)
    assert alloc.sum() == pytest.approx(500_000.0, rel=1e-12)


def test_premium_tax_identity_and_terms():
    """tax = AV x premium x rate/100 exactly, and the single-assumption
    adjust term reproduces a shifted-premium rerun."""
    a = trail._assumptions(_Ctx())
    av = Interval.point(250_000_000.0)
    rate = 1.03  # $ per $100
    uplift = av * Interval.from_assumption(a["trail_property_premium"])
    tax = uplift * (rate / 100.0)
    assert tax.value == pytest.approx(
        250_000_000.0 * a["trail_property_premium"].value * rate / 100.0, rel=1e-12)
    assert tax.low == 0.0  # the zero floor propagates end-to-end

    t = term(tax.value, trail_property_premium=1.0)
    shifted = a["trail_property_premium"].value * 0.5
    recomputed = t.value * (shifted / a["trail_property_premium"].value)
    direct = 250_000_000.0 * shifted * rate / 100.0
    assert recomputed == pytest.approx(direct, rel=1e-12)
