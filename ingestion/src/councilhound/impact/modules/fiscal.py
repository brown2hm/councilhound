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
from councilhound.impact.provenance import (Interval, metric, prov, term,
                                            terms_pow_extend, terms_scale)
from councilhound.impact.schemas import Assumption, MetricValue, ModuleResult

log = logging.getLogger(__name__)

COMP_LOOKBACK_YEARS = 15


def _assumptions() -> dict[str, Assumption]:
    return {a.key: a for a in [
        Assumption(key="commercial_value_per_sqft", value=275.0, low=200.0, high=400.0,
                   basis="screening range for new ground-floor commercial assessed value",
                   rationale="assessed $/sqft applied to proposed retail space; refine "
                             "with commercial comps in a follow-up"),
        Assumption(key="students_per_unit", value=0.10, low=0.05, high=0.15,
                   basis="high-rise/small-unit multifamily student generation rates "
                         "(below garden-apartment averages per the Rutgers demographic "
                         "multipliers); university-adjacent renter pools skew to "
                         "single/roommate households over families",
                   rationale="drives the school-cost component when the education "
                             "transfer and enrollment are pinned (school-split cost "
                             "model); otherwise informs the school note only"),
        Assumption(key="marginal_cost_factor", value=0.40, low=0.25, high=0.60,
                   basis="marginal-cost framing: fixed services (roads, admin) don't "
                         "scale with infill residents",
                   rationale="share of the NON-school per-capita cost that scales at "
                             "the margin (school costs follow the student estimate "
                             "directly under the school-split model)"),
        # rough-estimate inputs: the three below exist only to keep the revenue
        # side from silently reading as zero for taxes the city does levy —
        # their metrics are labeled "rough estimate" and carry wide bounds
        Assumption(key="vehicles_per_household", value=1.4, low=1.0, high=1.8,
                   basis="ACS vehicles-available norms for multifamily renter "
                         "households in Northern Virginia (below the ~1.8 "
                         "citywide all-tenure average)",
                   rationale="rough-estimate input: converts new households to "
                             "taxable vehicles for the personal property levy"),
        Assumption(key="avg_vehicle_assessed_value", value=14000.0, low=9000.0, high=20000.0,
                   basis="typical assessed (trade-in basis) vehicle values in "
                         "NoVA jurisdictions' recent personal-property rolls",
                   rationale="rough-estimate input: average taxable value per "
                             "vehicle; no project-specific fleet data exists"),
        Assumption(key="retail_sales_per_sqft", value=400.0, low=250.0, high=600.0,
                   basis="industry gross-sales ranges for ground-floor "
                         "neighborhood retail and full-service restaurants",
                   rationale="rough-estimate input: annual gross receipts per "
                             "sqft for the BPOL base; the low bound absorbs "
                             "vacancy and lease-up"),
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


def _terms_of(m: MetricValue):
    """A metric's adjustment terms, degrading to a constant term so that
    composite metrics keep the sum(terms) == value invariant even when a
    component isn't adjustable."""
    return m.adjust if m.adjust else [term(m.value)]


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
    av_terms = None
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
            av_terms = [term(residential.value),
                        term(commercial.value, commercial_value_per_sqft=1.0)]
            metrics.append(metric(
                "Projected assessed value", projected_av, "$",
                [comp_prov], [a["commercial_value_per_sqft"]],
                "median comp $/unit x units (25th-75th pct bounds) + retail sqft x $/sqft",
                adjust=av_terms))
        elif comps is not None:
            notes.append(f"LOW CONFIDENCE: only {len(comps)} multifamily comps found "
                         "(<3) — projected value not computed; extend the lookback or "
                         "add comps manually")

    # 3. recurring revenue
    if projected_av is not None and re_rate is not None:
        projected_tax = projected_av * (re_rate.value / 100.0)
        tax_terms = terms_scale(av_terms, re_rate.value / 100.0)
        metrics.append(metric("Projected real estate tax", projected_tax, "$/yr",
                              [comp_prov, rate_prov], [a["commercial_value_per_sqft"]],
                              "projected assessed value x RE rate / 100",
                              adjust=tax_terms))
        if site_av is not None:
            metrics.append(metric("Real estate tax increase", projected_tax - site_av * (re_rate.value / 100.0),
                                  "$/yr", [comp_prov, rate_prov, site_prov], [],
                                  "projected minus current RE tax", headline=True,
                                  adjust=tax_terms + [term(-site_av.value * re_rate.value / 100.0)]))
        if acres:
            metrics.append(metric("Projected value per acre", projected_av * (1 / acres),
                                  "$/acre", [comp_prov], [], "projected AV / site acres"))

    # personal property: per-household budget actuals when pinned (preferred),
    # else a rate-based vehicle estimate — explicitly labeled a rough estimate
    households_m = _prior_metric(prior, "New households")
    pp_actuals = cfg.tax.personal_property_per_household
    if households_m and pp_actuals.value is not None:
        households = _interval_from_metric(households_m)
        metrics.append(metric(
            "Personal property tax (new households)", households * pp_actuals.value, "$/yr",
            [prov("City budget per-household personal property actuals",
                  pp_actuals.source or "", pp_actuals.fy or "")],
            [], "new households x per-household personal property revenue",
            adjust=terms_scale(_terms_of(households_m), pp_actuals.value)))
    elif households_m:
        pp_rate = _rate(cfg, "tax.personal_property_rate_per_100", notes)
        if pp_rate:
            households = _interval_from_metric(households_m)
            vehicles = households * Interval.from_assumption(a["vehicles_per_household"])
            pp_est = (vehicles * Interval.from_assumption(a["avg_vehicle_assessed_value"])
                      * (pp_rate.value / 100.0))
            pp_terms = terms_pow_extend(
                terms_scale(_terms_of(households_m),
                            a["vehicles_per_household"].value
                            * a["avg_vehicle_assessed_value"].value
                            * pp_rate.value / 100.0),
                vehicles_per_household=1.0, avg_vehicle_assessed_value=1.0)
            metrics.append(metric(
                "Personal property tax on resident vehicles (rough estimate)",
                pp_est, "$/yr",
                [prov("City personal property tax rate", pp_rate.source or "",
                      pp_rate.fy or "",
                      "PPTRA car-tax relief is a fixed state block grant, so "
                      "marginal vehicles yield the city the full levy")],
                [a["vehicles_per_household"], a["avg_vehicle_assessed_value"]],
                "ROUGH ESTIMATE: new households x assumed vehicles per household "
                "x assumed value per vehicle x PP rate / 100 — no project-specific "
                "vehicle data; treat as order-of-magnitude", adjust=pp_terms))
            notes.append(
                "Personal property tax is a rough estimate: the city rate is "
                "pinned, but vehicles per household and average vehicle value "
                "are assumptions, not observed data. Pinning per-household "
                "budget actuals would replace this estimate.")

    # BPOL on the project's own commercial space — same rough-estimate framing
    bpol_rate = _rate(cfg, "tax.bpol_retail_rate_per_100", notes)
    retail_sqft = spec.proposed.retail_sqft or 0
    if bpol_rate and retail_sqft:
        receipts = (Interval.point(retail_sqft)
                    * Interval.from_assumption(a["retail_sales_per_sqft"]))
        metrics.append(metric(
            "BPOL business license tax on project retail (rough estimate)",
            receipts * (bpol_rate.value / 100.0), "$/yr",
            [prov("City BPOL rate schedule (budget Rates & Levies)",
                  bpol_rate.source or "", bpol_rate.fy or "",
                  "retail-sales rate applied to the whole space; the "
                  "repair/personal/business-services classification is taxed "
                  "at $0.27 per $100, slightly above the retail rate")],
            [a["retail_sales_per_sqft"]],
            "ROUGH ESTIMATE: proposed retail sqft x assumed gross sales per "
            "sqft x BPOL retail rate / 100 — actual receipts depend on tenants",
            adjust=[term(retail_sqft * a["retail_sales_per_sqft"].value
                         * bpol_rate.value / 100.0, retail_sales_per_sqft=1.0)]))
        notes.append(
            "BPOL revenue is a rough estimate: the city rate schedule is "
            "pinned, but tenant gross receipts are assumed from a sales-per-"
            "sqft range.")

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
                "(cross-module link from the economic Huff run)",
            adjust=terms_scale(_terms_of(food_away_m),
                               in_city_food_m.value * meals_rate.value)))
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
            sales_terms = []
            for m in spend_ms:
                sales_terms += terms_scale(_terms_of(m),
                                           in_city_all_m.value * sales_rate.value)
            metrics.append(metric(
                "Local sales tax share on captured in-city retail",
                base * sales_rate.value, "$/yr",
                [prov("Local-option sales tax share", sales_rate.source or "",
                      sales_rate.fy or "")],
                [], "in-city captured retail spend x local sales tax share",
                adjust=sales_terms))

    # 4. cost side — a range, never a point. When the education transfer and
    # enrollment are pinned, costs use the school-split model: school costs
    # are driven by the project's own student estimate (per-pupil tuition),
    # and only NON-school costs are allocated per resident. This is the
    # Burchell & Listokin per-capita-multiplier refinement, and it fixes the
    # average-cost distortion where a development adding few students is
    # still billed the school-heavy citywide average for every resident.
    gf = _rate(cfg, "budget.general_fund_expenditure", notes)
    pop = _rate(cfg, "budget.population_basis", notes)
    residents_m = _prior_metric(prior, "New residents")
    if gf and pop and residents_m:
        residents = _interval_from_metric(residents_m)
        students = Interval.point(units) * Interval.from_assumption(a["students_per_unit"])
        edu = cfg.budget.education_transfer
        enroll = cfg.budget.school_enrollment
        school_split = edu.value is not None and enroll.value is not None

        if school_split:
            nonschool_percap = (gf.value - edu.value) / pop.value
            # per-pupil cost is NET of state education revenue when pinned:
            # basic aid and the education sales tax follow ADM, so a new
            # student brings that revenue with them — only the local share
            # is a cost to city taxpayers
            state_school = cfg.budget.state_school_revenue
            state_offset = state_school.value or 0.0
            per_pupil = (edu.value - state_offset) / enroll.value
            resident_cost = residents * nonschool_percap
            school_cost = students * per_pupil
            naive = resident_cost + school_cost
            school_note = (f"schools: (${edu.value:,.0f} tuition - "
                           f"${state_offset:,.0f} state education revenue) / "
                           f"{enroll.value:,.0f} students = ${per_pupil:,.0f} "
                           f"net local cost per pupil"
                           if state_offset else
                           f"schools: ${edu.value:,.0f} / {enroll.value:,.0f} "
                           f"students = ${per_pupil:,.0f} per pupil (gross — "
                           "state education revenue not pinned)")
            budget_prov = prov(
                "City General Fund budget + school tuition contract",
                gf.source or "", gf.fy or "",
                f"non-school: (${gf.value:,.0f} - ${edu.value:,.0f}) / "
                f"{pop.value:,.0f} residents = ${nonschool_percap:,.0f} per "
                f"capita; {school_note} ({edu.fy or ''})")
            school_terms = [term(school_cost.value, students_per_unit=1.0)]
            resident_terms = terms_scale(_terms_of(residents_m), nonschool_percap)
            naive_terms = resident_terms + school_terms
            naive_method = ("residents x non-school GF per capita + estimated "
                            "students x per-pupil tuition (school costs follow "
                            "the project's own student estimate, not the "
                            "citywide average)")
            # schools scale with actual students in BOTH framings; the
            # marginal factor discounts only the non-school share
            marginal = resident_cost * Interval.from_assumption(a["marginal_cost_factor"]) + school_cost
            marginal_terms = terms_pow_extend(
                terms_scale(resident_terms, a["marginal_cost_factor"].value),
                marginal_cost_factor=1.0) + school_terms
            marginal_method = ("non-school per-capita cost x marginal factor + "
                               "students x per-pupil tuition (schools scale "
                               "with actual students; fixed services don't)")
            notes.append(
                "School costs use the split model: {:.0f} students ({:.0f}-{:.0f}) "
                "x ${:,.0f} {} per pupil ≈ ${:,.0f}/yr in both cost framings — a "
                "development generating fewer students carries proportionally "
                "lower costs instead of the school-heavy citywide average.".format(
                    students.value, students.low, students.high, per_pupil,
                    "net local cost" if state_offset else "(gross)",
                    school_cost.value))
            # published as its own metric so the narrative can cite the
            # school component and its bounds without deriving arithmetic
            metrics.append(metric(
                "Annual school cost within the service-cost estimates",
                school_cost, "$/yr", [budget_prov], [a["students_per_unit"]],
                "estimated students x net local cost per pupil; included "
                "identically in both cost framings",
                adjust=list(school_terms)))
        else:
            per_capita = gf.value / pop.value
            naive = residents * per_capita
            budget_prov = prov("City General Fund budget", gf.source or "", gf.fy or "",
                               f"${gf.value:,.0f} / {pop.value:,.0f} residents = "
                               f"${per_capita:,.0f} per capita")
            naive_terms = terms_scale(_terms_of(residents_m), per_capita)
            naive_method = ("new residents x GF expenditure per capita "
                            "(upper-bound framing; includes fixed costs that "
                            "don't scale)")
            marginal = naive * Interval.from_assumption(a["marginal_cost_factor"])
            marginal_terms = terms_pow_extend(
                terms_scale(naive_terms, a["marginal_cost_factor"].value),
                marginal_cost_factor=1.0)
            marginal_method = ("naive cost x marginal factor: schools/parks "
                               "scale, existing road frontage and admin mostly "
                               "don't")
            notes.append(
                "School impact within the cost range: {} units x {} students/unit "
                "(bounds {}-{}) ≈ {:.0f} students ({:.0f}-{:.0f}). Pin "
                "budget.education_transfer and budget.school_enrollment to switch "
                "to the school-split cost model.".format(
                    units, a["students_per_unit"].value,
                    a["students_per_unit"].low, a["students_per_unit"].high,
                    students.value, students.low, students.high))

        metrics.append(metric(
            "Annual service cost — naive per-capita method", naive, "$/yr",
            [budget_prov], [a["students_per_unit"]] if school_split else [],
            naive_method, adjust=naive_terms))
        metrics.append(metric(
            "Annual service cost — marginal framing", marginal, "$/yr",
            [budget_prov],
            [a["marginal_cost_factor"]] + ([a["students_per_unit"]] if school_split else []),
            marginal_method, adjust=marginal_terms))
        metrics.append(metric(
            "Estimated K-12 students", students, "students",
            [prov("Rutgers CUPR residential demographic multipliers "
                  "(Listokin et al. 2006), high-rise multifamily",
                  "https://cupr.rutgers.edu", "2006")],
            [a["students_per_unit"]],
            ("units x students per unit; drives the school-cost component of "
             "both cost framings" if school_split else
             "units x students per unit; reported alongside the cost range but "
             "not entering either cost method (per-capita costing already "
             "embeds average school costs)"),
            adjust=[term(students.value, students_per_unit=1.0)]))

        # net fiscal impact: INCREMENTAL revenue minus the cost range. The RE
        # component prefers the tax increase over the projected total — the
        # site's current tax is revenue the city already collects, so only
        # the increase belongs in a net-impact figure.
        re_component = (next((x for x in metrics if x.name == "Real estate tax increase"), None)
                        or next((x for x in metrics if x.name == "Projected real estate tax"), None))
        # the per-household and vehicle-estimate PP lines are mutually
        # exclusive above, so listing both cannot double count
        revenue_names = ("Personal property tax (new households)",
                         "Personal property tax on resident vehicles (rough estimate)",
                         "BPOL business license tax on project retail (rough estimate)",
                         "Meals tax on captured in-city dining",
                         "Local sales tax share on captured in-city retail")
        revenue = _interval_from_metric(re_component) if re_component else None
        revenue_terms = list(_terms_of(re_component)) if re_component else []
        for name in revenue_names:
            m = next((x for x in metrics if x.name == name), None)
            if m:
                interval = _interval_from_metric(m)
                revenue = interval if revenue is None else revenue + interval
                revenue_terms += _terms_of(m)
        if revenue is not None:
            # per-method nets published explicitly so the narrative can cite
            # either framing without deriving arithmetic of its own
            for method_name, cost, cost_terms, note in (
                ("naive per-capita method", naive, naive_terms,
                 "upper-bound cost framing; allocates fixed citywide costs"),
                ("marginal framing", marginal, marginal_terms,
                 "only services that scale with new residents"),
            ):
                net = revenue - cost
                net_assumptions = [a["marginal_cost_factor"]]
                if school_split:
                    net_assumptions.append(a["students_per_unit"])
                metrics.append(metric(
                    f"Net annual fiscal impact — {method_name}", net, "$/yr",
                    [budget_prov], net_assumptions,
                    f"incremental new recurring revenue minus service cost ({note})",
                    headline=True,
                    adjust=revenue_terms + terms_scale(cost_terms, -1.0)))
            net_low = revenue.low - naive.high      # most conservative
            net_high = revenue.high - marginal.low  # most favorable
            net_mid = revenue.value - (naive.value + marginal.value) / 2
            mid_terms = (revenue_terms + terms_scale(naive_terms, -0.5)
                         + terms_scale(marginal_terms, -0.5))
            metrics.append(MetricValue(
                name="Net annual fiscal impact (range across both cost methods)",
                value=round(net_mid), unit="$/yr", low=round(net_low), high=round(net_high),
                provenance=[budget_prov],
                assumptions=["marginal_cost_factor"],
                method="incremental new recurring revenue minus service-cost range "
                       "(naive per-capita upper, marginal lower)",
                adjust=mid_terms))
            notes.append("The net fiscal range spans both cost framings on purpose: "
                         "the naive per-capita method overstates costs for infill "
                         "(it allocates fixed citywide costs to new residents); the "
                         "marginal framing understates them if service capacity "
                         "expansions are triggered.")
            notes.append("The revenue side includes the rough-estimate personal "
                         "property and BPOL lines: leaving them at zero would "
                         "understate revenue for taxes the city does levy, but "
                         "both carry wide assumption-driven bounds.")

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
