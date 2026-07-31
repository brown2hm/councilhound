"""Fiscal module: the revenue ledger, the cost framings, and the guards that
keep a wrong input from passing silently.

This module had no tests at all while it produced the report's headline
numbers. The cases below are anchored on defects found by comparing City
Centre West against the applicant's fiscal impact analysis and the city staff
report: apartment comps priced onto for-sale condos, proposed office space
entering no computation, on-site commercial taxes missing entirely, and a
baseline built from one parcel of a three-parcel assembly.
"""
import pytest

from councilhound.impact.jurisdiction import PinnedValue
from councilhound.impact.modules import fiscal
from councilhound.impact.provenance import Interval, metric, prov, term
from councilhound.impact.schemas import ProjectSpec

# ---------------------------------------------------------------- fixtures


def _Pinned(value, source="https://example/rates", fy="FY2027"):
    # require_rate() type-checks PinnedValue, so a stand-in class reads as
    # "unpinned" and every rate-dependent metric silently disappears
    return PinnedValue(value=value, source=source, fy=fy)


class _Tax:
    # instance attributes, so a test that unpins a rate cannot leak into others
    def __init__(self):
        self.real_estate_rate_per_100 = _Pinned(1.0725)
        self.meals_tax_rate = _Pinned(0.045)
        self.sales_tax_local_share = _Pinned(0.01)
        self.personal_property_per_household = _Pinned(None)
        self.personal_property_rate_per_100 = _Pinned(4.13)
        self.bpol_retail_rate_per_100 = _Pinned(0.20)
        self.bpol_office_rate_per_100 = _Pinned(0.40)
        self.bpp_rate_per_100 = _Pinned(4.13)


class _Budget:
    def __init__(self):
        self.general_fund_expenditure = _Pinned(207_912_496)
        self.population_basis = _Pinned(25_026)
        self.education_transfer = _Pinned(76_429_791)
        self.school_enrollment = _Pinned(3_103)
        self.state_school_revenue = _Pinned(14_492_271)


class _Cfg:
    slug = "testville"
    crs_projected = "EPSG:2283"

    def __init__(self):
        self.tax = _Tax()
        self.budget = _Budget()
        self.assessment_lucs = {"apartment": "352", "condo": "353"}


class _Ctx:
    def __init__(self, parcels=None):
        self.cfg = _Cfg()
        self._parcels = parcels

    @property
    def parcels(self):
        if self._parcels is None:
            raise RuntimeError("parcel layer not built")
        return self._parcels


def _spec(external_estimates=None, assumption_overrides=None, **proposed):
    program = {"units": 79, "retail_sqft": 7731.0, "office_sqft": 36862.0,
               "acres": 1.78, "stories": 8}
    program.update(proposed)
    # model_validate, not attribute assignment: the real path validates and
    # coerces nested models, and dicts assigned after construction would stay
    # dicts (pydantic does not validate on assignment here)
    return ProjectSpec.model_validate({
        "name": "Test Project", "jurisdiction": "testville",
        "city_project_slug": "test-project", "source_url": "https://example/project",
        "project_type": "mixed_use", "status": "Approved",
        "parcels": ["57 4 02 076"],
        "existing": {"sqft": 19469.0, "units": 0, "assessed_value": 2_016_200.0},
        "proposed": program,
        "external_estimates": external_estimates or [],
        "assumption_overrides": assumption_overrides or {},
    })


def _comps(*per_unit_values):
    return [{"pin": f"00 0 00 {i:03d}", "year_built": 2020,
             "residential_units": 100, "total_value": v * 100,
             "per_unit_value": float(v)}
            for i, v in enumerate(per_unit_values, 1)]


def _prior_economic():
    """The economic-module metrics the fiscal module consumes."""
    site = prov("Project documents", "https://example/project", "current")
    return [type("R", (), {"metrics": [
        metric("New households", Interval(75.0, 71.0, 77.0), "households", [site],
               [], "m", adjust=[term(75.0, "Households")]),
        metric("New residents", Interval(135.0, 107.0, 169.0), "residents", [site],
               [], "m", adjust=[term(135.0, "Residents")]),
        metric("New annual spending: restaurant_bar", Interval(512_465.0, 373_356.0, 658_119.0),
               "$/yr", [site], [], "m", adjust=[term(512_465.0, "Restaurant spend")]),
        metric("New annual spending: grocery", Interval(573_186.0, 437_739.0, 705_721.0),
               "$/yr", [site], [], "m", adjust=[term(573_186.0, "Grocery spend")]),
        metric("New annual spending: retail_comparison", Interval(646_379.0, 465_404.0, 838_886.0),
               "$/yr", [site], [], "m", adjust=[term(646_379.0, "Comparison spend")]),
        metric("New annual spending: retail_convenience", Interval(105_244.0, 78_967.0, 131_643.0),
               "$/yr", [site], [], "m", adjust=[term(105_244.0, "Convenience spend")]),
        metric("In-city capture share: food_away", Interval(0.686, 0.638, 0.734),
               "fraction", [site], [], "m"),
        metric("In-city capture share: all_retail", Interval(0.630, 0.597, 0.676),
               "fraction", [site], [], "m"),
        metric("Annual capture: project's own ground-floor retail",
               Interval(8227.0, 4874.0, 10444.0), "$/yr", [site], [], "m",
               adjust=[term(8227.0, "Own retail capture")]),
    ]})()]


def _run(spec, ctx=None, comps=None, prior=None, monkeypatch=None):
    ctx = ctx or _Ctx()
    monkeypatch.setattr(fiscal, "_comps", lambda spec, ctx, notes: comps)
    return fiscal.run(spec, ctx, prior=prior if prior is not None else _prior_economic())


def _by_name(result):
    return {m.name: m for m in result.metrics}


# ------------------------------------------------------- assessed value


def test_projected_value_includes_residential_retail_and_office(monkeypatch):
    """Office square footage used to enter no computation at all: tens of
    thousands of proffered square feet were assessed at zero."""
    result, _ = _run(_spec(), comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    av = _by_name(result)["Projected assessed value"]
    labels = {t.label for t in av.adjust}
    assert labels == {"Residential value", "Ground-floor commercial value",
                      "Office/non-retail commercial value"}
    office_term = next(t for t in av.adjust if t.label.startswith("Office"))
    assert office_term.value == pytest.approx(36862.0 * 300.0)
    assert av.value == pytest.approx(sum(t.value for t in av.adjust))


def test_office_sqft_moves_the_projected_value(monkeypatch):
    comps = _comps(360_000, 400_000, 460_000)
    with_office, _ = _run(_spec(), comps=comps, monkeypatch=monkeypatch)
    without, _ = _run(_spec(office_sqft=0.0), comps=comps, monkeypatch=monkeypatch)
    delta = (_by_name(with_office)["Projected assessed value"].value
             - _by_name(without)["Projected assessed value"].value)
    assert delta == pytest.approx(36862.0 * 300.0)


def test_residential_value_per_unit_is_a_published_assumption(monkeypatch):
    """It is the single largest input to the result; it must be adjustable and
    sensitivity-rankable, not buried in comp arithmetic."""
    result, _ = _run(_spec(), comps=_comps(300_000, 360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    keys = {a.key for a in result.assumptions}
    assert "residential_value_per_unit" in keys
    seeded = next(a for a in result.assumptions if a.key == "residential_value_per_unit")
    assert seeded.value == pytest.approx(380_000)  # median of the four comps
    assert seeded.low < seeded.value < seeded.high
    av = _by_name(result)["Projected assessed value"]
    assert "residential_value_per_unit" in av.assumptions
    res_term = next(t for t in av.adjust if t.label == "Residential value")
    assert res_term.exps["residential_value_per_unit"] == 1.0


def test_screening_default_used_and_flagged_when_comps_missing(monkeypatch):
    result, _ = _run(_spec(), comps=None, monkeypatch=monkeypatch)
    seeded = next(a for a in result.assumptions if a.key == "residential_value_per_unit")
    assert seeded.value == pytest.approx(360_000)  # rental default
    assert any("SCREENING DEFAULT" in n for n in result.narrative_notes)


def test_for_sale_tenure_raises_the_default_and_student_yield(monkeypatch):
    rental, _ = _run(_spec(tenure="rental"), comps=None, monkeypatch=monkeypatch)
    for_sale, _ = _run(_spec(tenure="for_sale"), comps=None, monkeypatch=monkeypatch)

    def value(result, key):
        return next(a for a in result.assumptions if a.key == key).value

    assert value(for_sale, "residential_value_per_unit") > value(rental, "residential_value_per_unit")
    assert value(for_sale, "students_per_unit") > value(rental, "students_per_unit")
    # one key per concept: tenure changes the default, never the key set
    assert ({a.key for a in rental.assumptions} == {a.key for a in for_sale.assumptions})


def test_assumption_override_replaces_the_default(monkeypatch):
    """The reviewer's escape hatch: applicant per-unit values comps can't see."""
    spec = _spec(assumption_overrides={"residential_value_per_unit": {
        "value": 2_030_000, "low": 1_854_752, "high": 2_266_919,
        "rationale": "applicant FIA unit pricing"}})
    result, _ = _run(spec, comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    seeded = next(a for a in result.assumptions if a.key == "residential_value_per_unit")
    assert seeded.value == pytest.approx(2_030_000)
    assert any("overridden by hand" in n for n in result.narrative_notes)
    av = _by_name(result)["Projected assessed value"]
    assert av.value == pytest.approx(79 * 2_030_000 + 7731 * 275 + 36862 * 300)


# ------------------------------------------------------- revenue ledger


def test_every_revenue_line_reaches_the_net(monkeypatch):
    """Regression for the silent enrolment gate: revenue lines used to be
    picked up by matching a hard-coded tuple of metric names, so a new line
    was computed, displayed, and then omitted from the net."""
    result, _ = _run(_spec(), comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    by_name = _by_name(result)
    naive = by_name["Net annual fiscal impact — naive per-capita method"]
    cost = by_name["Annual service cost — naive per-capita method"]

    excluded = {
        "Current real estate tax (site)", "Current value per acre",
        "Projected assessed value", "Projected real estate tax",
        "Projected value per acre",
        "Annual school cost within the service-cost estimates",
        "Annual service cost — naive per-capita method",
        "Annual service cost — marginal framing",
        "Estimated K-12 students",
    }
    revenue_metrics = [m for name, m in by_name.items()
                       if m.unit == "$/yr" and name not in excluded
                       and not name.startswith("Net annual fiscal impact")
                       and not name.startswith("External estimate")]
    assert naive.value == pytest.approx(sum(m.value for m in revenue_metrics) - cost.value,
                                        rel=1e-9)


def test_onsite_commercial_taxes_are_displacement_adjusted(monkeypatch):
    """Gross on-site receipts overstate the city's gain: sales captured from
    existing city businesses stop being taxed at the old location."""
    result, _ = _run(_spec(), comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    by_name = _by_name(result)
    meals = by_name["Meals tax on the project's own restaurants (net-new, rough estimate)"]
    assert "net_new_share" in meals.assumptions
    # 7,731 sqft x $400/sqft, less the $8,227 already counted resident-side,
    # x 50% restaurant share x 4.5% meals tax x 30% net-new
    expected = (7731 * 400 - 8227) * 0.50 * 0.045 * 0.30
    assert meals.value == pytest.approx(expected)
    assert meals.value == pytest.approx(sum(t.value for t in meals.adjust))


def test_onsite_base_excludes_resident_capture_already_counted(monkeypatch):
    """The double-count guard: new residents' spending at the project's own
    ground floor is counted at full weight in the resident-side lines, so it
    must not also flow through the displacement-discounted on-site lines."""
    comps = _comps(360_000, 400_000, 460_000)
    with_prior, _ = _run(_spec(), comps=comps, prior=_prior_economic(),
                         monkeypatch=monkeypatch)
    by_name = _by_name(with_prior)
    sales = by_name["Local sales tax on the project's own retail (net-new, rough estimate)"]
    assert sales.value == pytest.approx((7731 * 400 - 8227) * 0.01 * 0.30)
    # the resident-side line is untouched by the new on-site term
    resident = by_name["Local sales tax share on captured in-city retail"]
    assert resident.value == pytest.approx(
        (573_186.0 + 646_379.0 + 105_244.0) * 0.630 * 0.01)
    assert any("already counted in full" in n for n in with_prior.narrative_notes)


def test_office_bpol_and_bpp_are_computed(monkeypatch):
    result, _ = _run(_spec(), comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    by_name = _by_name(result)
    office_bpol = by_name["BPOL business license tax on project office (rough estimate)"]
    assert office_bpol.value == pytest.approx(36862 * 500 * 0.40 / 100)
    # not displacement-adjusted: professional demand is regional
    assert "net_new_share" not in office_bpol.assumptions
    bpp = by_name["Business tangible property tax (rough estimate)"]
    assert bpp.value == pytest.approx((7731 + 36862) * 8.0 * 4.13 / 100)


def test_unpinned_rates_degrade_to_notes(monkeypatch):
    ctx = _Ctx()
    ctx.cfg.tax.bpol_office_rate_per_100 = _Pinned(None)
    ctx.cfg.tax.bpp_rate_per_100 = _Pinned(None)
    result, _ = _run(_spec(), ctx=ctx, comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    names = set(_by_name(result))
    assert "BPOL business license tax on project office (rough estimate)" not in names
    assert "Business tangible property tax (rough estimate)" not in names
    assert any("bpol_office_rate_per_100" in n for n in result.narrative_notes)


# --------------------------------------------------------------- baseline


def test_baseline_fills_missing_parcels_from_the_bulk_layer(monkeypatch):
    """Partial success used to be silent: with one of three parcels resolving,
    the baseline came back confidently wrong."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    layer = gpd.GeoDataFrame(
        {"pin": ["57 4 02    076", "57 4 02    072", "57 4 02    071"],
         "assessed_total": [3_185_200.0, 1_545_500.0, 2_252_600.0]},
        geometry=[Point(0, 0), Point(1, 1), Point(2, 2)], crs="EPSG:4326")
    ctx = _Ctx(parcels=layer)

    class _Client:
        def assessment_for_pin(self, pin):
            if "076" in pin:
                return {"total_value": 2_016_200.0}
            return None

    import councilhound.impact.context.assessments as assessments
    monkeypatch.setattr(assessments, "WebProClient", lambda: _Client())

    spec = _spec()
    spec.parcels = ["57-4-02-076", "57-4-02-072", "57-4-02-071"]
    spec.existing.assessed_value = None
    notes = []
    site_av, site_prov = fiscal._site_assessment(spec, ctx, notes)
    # WebPro for 076, bulk layer for the other two
    assert site_av.value == pytest.approx(2_016_200.0 + 1_545_500.0 + 2_252_600.0)
    assert any("bulk parcel layer" in n for n in notes)
    assert any("disagree" in n for n in notes)  # 2.02M vs 3.19M on parcel 076
    assert "GeoHub" in site_prov.source_name


def test_baseline_warns_when_a_parcel_has_no_value(monkeypatch):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    layer = gpd.GeoDataFrame({"pin": ["57 4 02 076"], "assessed_total": [2_016_200.0]},
                             geometry=[Point(0, 0)], crs="EPSG:4326")
    ctx = _Ctx(parcels=layer)

    class _Client:
        def assessment_for_pin(self, pin):
            return None

    import councilhound.impact.context.assessments as assessments
    monkeypatch.setattr(assessments, "WebProClient", lambda: _Client())

    spec = _spec()
    spec.parcels = ["57 4 02 076", "57 4 02 999"]
    spec.existing.assessed_value = None
    notes = []
    site_av, _ = fiscal._site_assessment(spec, ctx, notes)
    assert site_av.value == pytest.approx(2_016_200.0)
    assert any("57 4 02 999" in n and "incomplete" in n for n in notes)


# ------------------------------------------------- external benchmarking


def test_external_estimates_are_published_and_compared(monkeypatch):
    spec = _spec(external_estimates=[
        {"source": "July 11 2023 staff report", "kind": "staff_report",
         "net_annual_low": 543_000, "net_annual_high": 741_000,
         "quote": "ranges from $543,000 and $741,000 annually"},
    ])
    result, _ = _run(spec, comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    by_name = _by_name(result)
    external = by_name["External estimate: city staff report — net annual fiscal impact"]
    assert (external.low, external.high) == (543_000, 741_000)
    # never adjustable and never merged into our figures
    assert external.adjust is None
    assert "not computed by this pipeline" in external.method
    assert any(n.startswith("BENCHMARK:") for n in result.narrative_notes)


def test_cost_basis_sanity_gate_fires_on_undervaluation(monkeypatch):
    """The check that would have caught the original defect: $30.6M of assessed
    value against a $136.3M stated construction cost."""
    spec = _spec(external_estimates=[
        {"source": "April 2023 fiscal impact analysis", "kind": "applicant_fia",
         "construction_cost": 136_330_000,
         "quote": "Project Cost / Basis (rounded) $136,330,000"},
    ])
    result, _ = _run(spec, comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    assert any(n.startswith("SANITY:") and "residential_value_per_unit" in n
               for n in result.narrative_notes)


def test_no_sanity_note_when_value_tracks_cost(monkeypatch):
    spec = _spec(external_estimates=[
        {"source": "applicant FIA", "kind": "applicant_fia",
         "construction_cost": 45_000_000, "quote": "cost basis $45,000,000"},
    ])
    result, _ = _run(spec, comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    assert not any(n.startswith("SANITY:") for n in result.narrative_notes)


# ------------------------------------------------------- adjust invariant


def test_every_metric_decomposition_sums_to_its_value(monkeypatch):
    """The same invariant evaluate.py asserts on every real run."""
    spec = _spec(external_estimates=[
        {"source": "staff report", "kind": "staff_report",
         "net_annual_low": 543_000, "net_annual_high": 741_000, "quote": "q"},
    ])
    result, _ = _run(spec, comps=_comps(360_000, 400_000, 460_000),
                     monkeypatch=monkeypatch)
    for m in result.metrics:
        if not m.adjust:
            continue
        assert sum(t.value for t in m.adjust) == pytest.approx(
            m.value, abs=max(1e-6 * abs(m.value), 0.51)), m.name
