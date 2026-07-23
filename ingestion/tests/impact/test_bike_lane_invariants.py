"""Bike-lane module invariants: gates degrade to notes, spending conserves
across groups, and the adjust-term power law reproduces a direct rerun."""
import pytest

from councilhound.impact.modules import bike_lane
from councilhound.impact.provenance import Interval
from councilhound.impact.schemas import ProjectSpec


class _Ctx:
    pass  # _assumptions doesn't touch ctx


def _spec(**overrides):
    base = dict(
        name="Test corridor", jurisdiction="fairfax_city_va",
        city_project_slug="test", source_url="https://example.gov",
        project_type="street_multimodal", status="active",
        geometry={"type": "LineString",
                  "coordinates": [[-77.30, 38.85], [-77.29, 38.85]]},
        proposed={"corridor": {"facilities": ["protected bike lane"],
                               "street_name": "Main Street"}},
    )
    base.update(overrides)
    return ProjectSpec(**base)


def _eval_terms(terms, baseline, adjusted):
    total = 0.0
    for t in terms:
        factor = 1.0
        for key, e in t.exps.items():
            factor *= (adjusted.get(key, baseline[key]) / baseline[key]) ** e
        total += t.value * factor
    return total


def test_gate_wrong_project_type():
    result, layers = bike_lane.run(_spec(project_type="residential"), None)
    assert result.module == "bike_lane"
    assert result.metrics == []
    assert layers == {}
    assert any("Not computed" in n for n in result.narrative_notes)


def test_gate_polygon_geometry():
    pytest.importorskip("shapely")
    polygon = {"type": "Polygon",
               "coordinates": [[[-77.3, 38.85], [-77.29, 38.85],
                                [-77.29, 38.86], [-77.3, 38.85]]]}
    result, _ = bike_lane.run(_spec(geometry=polygon), None)
    assert result.metrics == []
    assert any("no corridor line geometry" in n for n in result.narrative_notes)


def test_gate_no_bike_facility():
    pytest.importorskip("shapely")
    spec = _spec(proposed={"corridor": {"facilities": ["sidewalk widening"],
                                        "street_name": "Main Street"}})
    result, _ = bike_lane.run(spec, None)
    assert result.metrics == []
    assert any("no bike facility" in n for n in result.narrative_notes)


def test_spending_conserves_across_groups():
    a = bike_lane._assumptions(_Ctx())
    trips = Interval(120.0, 60.0, 240.0)
    mix = {"restaurant": 0.5, "convenience": 0.25, "other_retail": 0.25}
    by_group, terms, total = bike_lane._spending(trips, mix, a)
    for pick in ("value", "low", "high"):
        assert sum(getattr(s, pick) for s in by_group.values()) == pytest.approx(
            getattr(total, pick), rel=1e-9)
    assert sum(t.value for t in terms) == pytest.approx(total.value, rel=1e-9)


def test_spending_skips_empty_groups():
    a = bike_lane._assumptions(_Ctx())
    trips = Interval(100.0, 50.0, 200.0)
    by_group, terms, total = bike_lane._spending(
        trips, {"restaurant": 1.0, "convenience": 0.0, "other_retail": 0.0}, a)
    assert set(by_group) == {"restaurant"}
    assert total.value == pytest.approx(by_group["restaurant"].value)


def test_spending_terms_reproduce_direct_rerun():
    """The published power law is exact: scaling the demand assumptions and
    re-evaluating the terms equals recomputing the spending directly."""
    a = bike_lane._assumptions(_Ctx())
    mix = {"restaurant": 0.6, "convenience": 0.2, "other_retail": 0.2}
    catchment = 5_000.0  # beta-only quantity: constant under slider moves
    baseline = {k: a[k].value for k in (
        "bike_trips_per_resident_day", "induced_corridor_visit_share",
        "bike_spend_per_trip_restaurant", "bike_spend_per_trip_convenience",
        "bike_spend_per_trip_other_retail")}
    adjusted = {k: v * f for (k, v), f in zip(
        baseline.items(), (1.2, 0.8, 1.1, 0.9, 1.05))}

    def trips_for(values):
        rate = values["bike_trips_per_resident_day"]
        share = values["induced_corridor_visit_share"]
        return Interval.point(catchment * rate * share)

    _, terms, _ = bike_lane._spending(trips_for(baseline), mix, a)

    shifted = dict(a)
    for g in bike_lane.SPEND_GROUPS:
        key = f"bike_spend_per_trip_{g}"
        shifted[key] = a[key].model_copy(update={
            "value": adjusted[key], "low": 0.0, "high": adjusted[key] * 10})
    _, _, direct_total = bike_lane._spending(trips_for(adjusted), mix, shifted)
    assert _eval_terms(terms, baseline, adjusted) == pytest.approx(
        direct_total.value, rel=1e-9)


def test_assumption_anchors_match_transcribed_literature():
    """Pin the transcribed values so silent edits show up in review: Clifton
    Table 3 ($10.97 restaurant / $16.90 bar / $7.95 convenience) and the
    NHTS-derived trip rate."""
    a = bike_lane._assumptions(_Ctx())
    assert a["bike_spend_per_trip_restaurant"].low <= 10.97 <= a["bike_spend_per_trip_restaurant"].high
    assert a["bike_spend_per_trip_restaurant"].low <= 16.90 <= 17.0  # bar mean inside the band
    assert a["bike_spend_per_trip_convenience"].low <= 7.95 <= a["bike_spend_per_trip_convenience"].high
    assert a["bike_trips_per_resident_day"].value == pytest.approx(0.035)
    assert a["induced_corridor_visit_share"].low == pytest.approx(0.03)
    assert a["induced_corridor_visit_share"].high == pytest.approx(0.20)
    # beta_bike must be the SAME object contract as the economic module's
    from councilhound.impact.modules.economic import _assumptions as econ
    assert a["beta_bike"] == econ(_Ctx())["beta_bike"]
