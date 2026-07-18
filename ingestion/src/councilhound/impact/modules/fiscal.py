"""Fiscal module: revenue/cost ranges + value-per-acre (brief §6.3).

Every rate comes from the jurisdiction YAML with provenance (pinned by
impact-setup-jurisdiction); an unpinned rate degrades its metrics to
"not computed — reason" instead of guessing. Costs are always a range with
both methods labeled (naive per-capita vs. marginal framing) — never a
point estimate. The meals/sales-tax lines consume the economic module's
in-city capture shares (the intentional cross-module link).
"""
from __future__ import annotations

import logging
from datetime import date

from councilhound.impact.jurisdiction import MissingRateError, require_rate
from councilhound.impact.provenance import Interval, metric, prov
from councilhound.impact.schemas import Assumption, MetricValue, ModuleResult

log = logging.getLogger(__name__)

COMP_LOOKBACK_YEARS = 15


def _assumptions() -> dict[str, Assumption]:
    return {a.key: a for a in [
        Assumption(key="commercial_value_per_sqft", value=275.0, low=200.0, high=400.0,
                   basis="screening range for new ground-floor commercial assessed value",
                   rationale="assessed $/sqft applied to proposed retail space; refine "
                             "with commercial comps in a follow-up"),
        Assumption(key="students_per_unit", value=0.175, low=0.10, high=0.25,
                   basis="multifamily student generation rates in NoVA jurisdiction "
                         "studies (range per methodology brief)",
                   rationale="school-age adjustment applied to the naive per-capita cost"),
        Assumption(key="marginal_cost_factor", value=0.40, low=0.25, high=0.60,
                   basis="marginal-cost framing: fixed services (roads, admin) don't "
                         "scale with infill residents",
                   rationale="share of average per-capita cost that scales at the margin"),
    ]}


def _rate(cfg, dotted, notes):
    try:
        return require_rate(cfg, dotted)
    except MissingRateError as exc:
        notes.append(f"Not computed: {dotted} — {exc}")
        return None


def _prior_metric(prior, name):
    for result in prior or []:
        for m in result.metrics:
            if m.name == name:
                return m
    return None


def _interval_from_metric(m: MetricValue) -> Interval:
    return Interval(m.value, m.low if m.low is not None else m.value,
                    m.high if m.high is not None else m.value)


def _site_assessment(spec, notes):
    """Current assessed value: prefer the extracted (document-stated) value,
    else sum WebPro records for the resolved parcels."""
    if spec.existing.assessed_value:
        return (Interval.point(spec.existing.assessed_value),
                prov("Project documents (extracted spec)", spec.source_url, "current"))
    if not spec.parcels:
        notes.append("Not computed: baseline revenue — no assessed value in documents "
                     "and no resolved parcels to look up")
        return None, None
    from councilhound.impact.context.assessments import WebProClient
    client = WebProClient()
    total = 0.0
    found = []
    for pin in spec.parcels:
        record = client.assessment_for_pin(pin)
        if record and record.get("total_value"):
            total += record["total_value"]
            found.append(pin)
    if not found:
        notes.append("Not computed: baseline revenue — assessment lookups failed for "
                     f"parcels {spec.parcels}")
        return None, None
    return (Interval.point(total),
            prov("City of Fairfax Real Estate Assessment Database (Patriot WebPro)",
                 "https://realestate.fairfaxva.gov", str(date.today().year),
                 f"parcels {', '.join(found)}"))


def run(spec, ctx, prior=None):
    a = _assumptions()
    notes: list[str] = []
    metrics: list[MetricValue] = []
    cfg = ctx.cfg

    re_rate = _rate(cfg, "tax.real_estate_rate_per_100", notes)
    rate_prov = (prov("City real estate tax rate", re_rate.source or "", re_rate.fy or "")
                 if re_rate else None)

    units = spec.proposed.units or 0
    acres = spec.proposed.acres
    site_av, site_prov = _site_assessment(spec, notes)

    # 1. baseline revenue
    if site_av is not None and re_rate is not None:
        baseline_tax = site_av * (re_rate.value / 100.0)
        metrics.append(metric("Current real estate tax (site)", baseline_tax, "$/yr",
                              [site_prov, rate_prov], [],
                              "current assessed value x RE rate / 100"))
        if acres:
            metrics.append(metric("Current value per acre", site_av * (1 / acres), "$/acre",
                                  [site_prov], [], "assessed value / site acres"))

    # 2. projected assessed value from multifamily comps
    projected_av = None
    comp_prov = None
    if units:
        comps = _comps(notes)
        if comps is not None and len(comps) >= 3:
            import statistics
            per_unit = sorted(c["per_unit_value"] for c in comps)
            median = statistics.median(per_unit)
            q1, q3 = per_unit[0], per_unit[-1]
            if len(per_unit) >= 4:
                quart = statistics.quantiles(per_unit, n=4)
                q1, q3 = quart[0], quart[2]
            comp_prov = prov(
                "City of Fairfax Real Estate Assessment Database (Patriot WebPro), "
                f"multifamily comps built since {date.today().year - COMP_LOOKBACK_YEARS}",
                "https://realestate.fairfaxva.gov", str(date.today().year),
                "comps: " + "; ".join(
                    f"{c['pin']} ({c['year_built']}, {c['residential_units']} units, "
                    f"${c['per_unit_value']:,.0f}/unit)" for c in comps),
            )
            residential = Interval(median * units, q1 * units, q3 * units)
            commercial = (Interval.point(spec.proposed.retail_sqft or 0)
                          * Interval.from_assumption(a["commercial_value_per_sqft"]))
            projected_av = residential + commercial
            metrics.append(metric(
                "Projected assessed value", projected_av, "$",
                [comp_prov], [a["commercial_value_per_sqft"]],
                "median comp $/unit x units (25th-75th pct bounds) + retail sqft x $/sqft",
                headline=True))
        elif comps is not None:
            notes.append(f"LOW CONFIDENCE: only {len(comps)} multifamily comps found "
                         "(<3) — projected value not computed; extend the lookback or "
                         "add comps manually")

    # 3. recurring revenue
    if projected_av is not None and re_rate is not None:
        projected_tax = projected_av * (re_rate.value / 100.0)
        metrics.append(metric("Projected real estate tax", projected_tax, "$/yr",
                              [comp_prov, rate_prov], [a["commercial_value_per_sqft"]],
                              "projected assessed value x RE rate / 100", headline=True))
        if site_av is not None:
            metrics.append(metric("Real estate tax increase", projected_tax - site_av * (re_rate.value / 100.0),
                                  "$/yr", [comp_prov, rate_prov, site_prov], [],
                                  "projected minus current RE tax"))
        if acres:
            metrics.append(metric("Projected value per acre", projected_av * (1 / acres),
                                  "$/acre", [comp_prov], [], "projected AV / site acres",
                                  headline=True))

    households_m = _prior_metric(prior, "New households")
    pp_rate = _rate(cfg, "tax.personal_property_per_household", notes)
    if households_m and pp_rate:
        households = _interval_from_metric(households_m)
        metrics.append(metric(
            "Personal property tax (new households)", households * pp_rate.value, "$/yr",
            [prov("City budget per-household personal property actuals",
                  pp_rate.source or "", pp_rate.fy or "")],
            [], "new households x per-household personal property revenue"))

    meals_rate = _rate(cfg, "tax.meals_tax_rate", notes)
    food_away_m = _prior_metric(prior, "New annual spending: restaurant_bar")
    in_city_food_m = _prior_metric(prior, "In-city capture share: food_away")
    if meals_rate and food_away_m and in_city_food_m:
        meals_base = (_interval_from_metric(food_away_m)
                      * _interval_from_metric(in_city_food_m))
        metrics.append(metric(
            "Meals tax on captured in-city dining", meals_base * meals_rate.value, "$/yr",
            [prov("City meals tax rate", meals_rate.source or "", meals_rate.fy or "")],
            [], "restaurant spending x in-city capture share x meals tax rate "
                "(cross-module link from the economic Huff run)", headline=True))
    elif meals_rate and not food_away_m:
        notes.append("Meals tax not computed: economic module results unavailable")

    sales_rate = _rate(cfg, "tax.sales_tax_local_share", notes)
    in_city_all_m = _prior_metric(prior, "In-city capture share: all_retail")
    if sales_rate and in_city_all_m:
        retail_categories = ("grocery", "retail_comparison", "retail_convenience")
        spend_ms = [_prior_metric(prior, f"New annual spending: {c}") for c in retail_categories]
        if all(spend_ms):
            taxable = sum((_interval_from_metric(m) for m in spend_ms[1:]),
                          _interval_from_metric(spend_ms[0]))
            base = taxable * _interval_from_metric(in_city_all_m)
            metrics.append(metric(
                "Local sales tax share on captured in-city retail",
                base * sales_rate.value, "$/yr",
                [prov("Local-option sales tax share", sales_rate.source or "",
                      sales_rate.fy or "")],
                [], "in-city captured retail spend x local sales tax share"))
    notes.append("BPOL (business license) revenue on the new commercial space is not "
                 "computed — the BPOL rate schedule is not pinned in this version.")

    # 4. cost side — a range, never a point
    gf = _rate(cfg, "budget.general_fund_expenditure", notes)
    pop = _rate(cfg, "budget.population_basis", notes)
    residents_m = _prior_metric(prior, "New residents")
    if gf and pop and residents_m:
        per_capita = gf.value / pop.value
        residents = _interval_from_metric(residents_m)
        naive = residents * per_capita
        budget_prov = prov("City General Fund budget", gf.source or "", gf.fy or "",
                           f"${gf.value:,.0f} / {pop.value:,.0f} residents = "
                           f"${per_capita:,.0f} per capita")
        metrics.append(metric(
            "Annual service cost — naive per-capita method", naive, "$/yr",
            [budget_prov], [a["students_per_unit"]],
            "new residents x GF expenditure per capita (upper-bound framing; "
            "includes fixed costs that don't scale)"))
        marginal = naive * Interval.from_assumption(a["marginal_cost_factor"])
        metrics.append(metric(
            "Annual service cost — marginal framing", marginal, "$/yr",
            [budget_prov], [a["marginal_cost_factor"]],
            "naive cost x marginal factor: schools/parks scale, existing road "
            "frontage and admin mostly don't"))
        notes.append(
            f"School impact within the cost range: {units} units x "
            f"{a['students_per_unit'].value} students/unit "
            f"(bounds {a['students_per_unit'].low}-{a['students_per_unit'].high}) "
            "≈ {:.0f} students ({:.0f}-{:.0f}).".format(
                units * a["students_per_unit"].value,
                units * a["students_per_unit"].low,
                units * a["students_per_unit"].high))

        # net fiscal impact: revenue metrics minus the cost range
        revenue_names = ("Projected real estate tax",
                         "Personal property tax (new households)",
                         "Meals tax on captured in-city dining",
                         "Local sales tax share on captured in-city retail")
        revenue = None
        for name in revenue_names:
            m = next((x for x in metrics if x.name == name), None)
            if m:
                interval = _interval_from_metric(m)
                revenue = interval if revenue is None else revenue + interval
        if revenue is not None:
            net_low = revenue.low - naive.high      # most conservative
            net_high = revenue.high - marginal.low  # most favorable
            net_mid = revenue.value - (naive.value + marginal.value) / 2
            metrics.append(MetricValue(
                name="Net annual fiscal impact (range across both cost methods)",
                value=round(net_mid), unit="$/yr", low=round(net_low), high=round(net_high),
                provenance=[budget_prov],
                assumptions=["marginal_cost_factor", "students_per_unit"],
                method="total new recurring revenue minus service-cost range "
                       "(naive per-capita upper, marginal lower)", headline=True))
            notes.append("The net fiscal range spans both cost framings on purpose: "
                         "the naive per-capita method overstates costs for infill "
                         "(it allocates fixed citywide costs to new residents); the "
                         "marginal framing understates them if service capacity "
                         "expansions are triggered.")

    result = ModuleResult(module="fiscal", metrics=metrics,
                          narrative_notes=notes, assumptions=list(a.values()))
    return result, {}


def _comps(notes):
    from councilhound.impact.context.assessments import WebProClient
    try:
        return WebProClient().multifamily_comps(
            built_since=date.today().year - COMP_LOOKBACK_YEARS)
    except Exception as exc:
        log.warning("comp query failed: %s", exc)
        notes.append(f"Not computed: projected assessed value — comp query failed ({exc})")
        return None
