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

from councilhound.impact.assumption_util import apply_overrides, is_for_sale
from councilhound.impact.jurisdiction import MissingRateError, require_rate
from councilhound.impact.pins import norm_pin
from councilhound.impact.provenance import (Interval, metric, prov, term,
                                            terms_pow_extend, terms_relabel,
                                            terms_scale)
from councilhound.impact.schemas import Assumption, MetricValue, ModuleResult

log = logging.getLogger(__name__)

COMP_LOOKBACK_YEARS = 15


def _residential_value_assumption(spec, comps, notes) -> tuple[Assumption, object | None]:
    """The assessed value of one new dwelling unit, seeded from comps.

    This used to be raw comp arithmetic inside the AV computation, which made
    the single largest input to the fiscal result invisible: it carried no
    assumption key, so it was neither adjustable in the assumptions lab nor
    ranked by sensitivity, and nothing flagged that apartment comps were being
    applied to for-sale condominiums. It is now an ordinary Assumption whose
    default happens to come from comps.
    """
    for_sale = is_for_sale(spec)
    if comps and len(comps) >= 3:
        import statistics
        per_unit = sorted(c["per_unit_value"] for c in comps)
        median = statistics.median(per_unit)
        q1, q3 = per_unit[0], per_unit[-1]
        if len(per_unit) >= 4:
            quart = statistics.quantiles(per_unit, n=4)
            q1, q3 = quart[0], quart[2]
        klass = "condominium" if for_sale else "apartment"
        # condo summary pages don't always expose a parsed PIN or year built;
        # fall back to the account number rather than printing "None (None"
        def describe(c):
            ident = c.get("pin") or f"acct {c.get('account')}"
            bits = [str(c["year_built"])] if c.get("year_built") else []
            units = c.get("residential_units")
            if units and units > 1:
                bits.append(f"{units} units")
            bits.append(f"${c['per_unit_value']:,.0f}/unit")
            return f"{ident} ({', '.join(bits)})"

        # a large comp set (condo classes run to hundreds of accounts) would
        # bloat the provenance note; summarize past a readable handful
        listed = "; ".join(describe(c) for c in comps[:12])
        if len(comps) > 12:
            listed += f"; ... and {len(comps) - 12} more"
        comp_prov = prov(
            "City of Fairfax Real Estate Assessment Database (Patriot WebPro), "
            f"{klass} comps built since {date.today().year - COMP_LOOKBACK_YEARS}",
            "https://realestate.fairfaxva.gov", str(date.today().year),
            f"{len(comps)} {klass} comps: {listed}",
        )
        return (Assumption(key="residential_value_per_unit",
                           value=median, low=q1, high=q3, basis=comp_prov,
                           rationale=f"median assessed value per unit across {len(comps)} "
                                     f"{klass}-class comps, 25th-75th percentile bounds"),
                comp_prov)

    # no usable comps: a screening default, deliberately wide, plus a note
    # demanding review. Tenure matters enormously here — a for-sale condo
    # assesses at several times an apartment building's per-unit value.
    default = dict(value=750_000.0, low=450_000.0, high=1_200_000.0) if for_sale \
        else dict(value=360_000.0, low=275_000.0, high=450_000.0)
    klass = "for-sale condominium" if for_sale else "rental multifamily"
    notes.append(
        f"Projected assessed value uses a SCREENING DEFAULT of "
        f"${default['value']:,.0f}/unit ({klass}), not comps"
        + (f" — only {len(comps)} usable comp(s) found" if comps else
           " — no comps available")
        + ". Set `assumption_overrides.residential_value_per_unit` in the spec "
        "YAML if better per-unit values are known.")
    return (Assumption(key="residential_value_per_unit", **default,
                       basis=f"screening range for new {klass} assessed value per unit",
                       rationale="no usable assessment comps for this product class; "
                                 "wide bounds signal that this is a placeholder for "
                                 "human review, not an estimate"),
            None)


def _assumptions(spec, comps, notes) -> tuple[dict[str, Assumption], object | None]:
    """Fiscal assumptions, tenure-branched then human-overridden.

    Tenure changes a default's VALUE, never its key: bundle dedupe and the
    frontend's assumption labels are both keyed, so per-tenure keys would be
    dead knobs in the assumptions lab.
    """
    residential, comp_prov = _residential_value_assumption(spec, comps, notes)
    # for-sale product skews slightly more family-ward than small-unit rental.
    # Centrals recalibrated 2026-08-22 from the Rutgers literature midpoints
    # (0.12/0.10) toward local evidence: benchmarking against City of Fairfax
    # staff fiscal estimates (WillowWood Jul 2024, Davies Jun 2025) implies
    # 0.057-0.073 students/unit for new multifamily; values sit above that
    # implied range on purpose, moving only partway from the literature.
    students = (dict(value=0.10, low=0.05, high=0.16) if is_for_sale(spec)
                else dict(value=0.08, low=0.05, high=0.12))
    students_basis = (
        "owner-occupied condominium student generation (Rutgers demographic "
        "multipliers for owner-occupied multifamily run above small-unit "
        "rental rates, below garden-apartment and single-family rates), "
        "shaded down toward City of Fairfax staff fiscal-estimate benchmarks"
        if is_for_sale(spec) else
        "high-rise/small-unit multifamily student generation rates "
        "(below garden-apartment averages per the Rutgers demographic "
        "multipliers, shaded down toward the 0.06-0.07 implied by City of "
        "Fairfax staff fiscal estimates for comparable projects); "
        "university-adjacent renter pools skew to single/roommate "
        "households over families")
    out = {a.key: a for a in [
        residential,
        Assumption(key="commercial_value_per_sqft", value=275.0, low=200.0, high=400.0,
                   basis="screening range for new ground-floor commercial assessed value",
                   rationale="assessed $/sqft applied to proposed retail space; refine "
                             "with commercial comps in a follow-up"),
        Assumption(key="office_value_per_sqft", value=300.0, low=200.0, high=450.0,
                   basis="screening range for new-construction office/institutional "
                         "assessed value per sqft in Northern Virginia",
                   rationale="assessed $/sqft applied to proposed non-retail commercial "
                             "space (office, medical, bank). Previously omitted, which "
                             "valued every proposed office at zero"),
        Assumption(key="office_receipts_per_sqft", value=500.0, low=300.0, high=800.0,
                   basis="professional and business-services gross receipts per leased "
                         "sqft (revenue per employee / sqft per employee)",
                   rationale="rough-estimate input: the BPOL base for office tenants"),
        Assumption(key="bpp_value_per_sqft", value=8.0, low=4.0, high=15.0,
                   basis="assessed business tangible property (furniture, fixtures, "
                         "equipment) per sqft of occupied commercial space",
                   rationale="rough-estimate input: the business tangible personal "
                             "property base across proposed retail and office space"),
        Assumption(key="net_new_share", value=0.30, low=0.15, high=0.50,
                   basis="retail-displacement findings in the fiscal-impact literature: "
                         "most sales at a new in-town store are captured from existing "
                         "businesses in the same jurisdiction rather than created",
                   rationale="share of the project's own on-site receipts that is NEW to "
                             "the city (new resident and visitor demand, plus sales "
                             "recaptured from outside) rather than displaced from "
                             "existing city businesses; displaced sales move the tax "
                             "base, they do not add to it"),
        Assumption(key="onsite_restaurant_share_of_retail", value=0.50, low=0.30, high=0.70,
                   basis="ground-floor tenant mixes in comparable mixed-use projects",
                   rationale="share of the project's ground-floor space occupied by "
                             "restaurants (the meals-tax base) rather than shop retail"),
        Assumption(key="students_per_unit", **students,
                   basis=students_basis,
                   rationale="drives the school-cost component when the education "
                             "transfer and enrollment are pinned (school-split cost "
                             "model); otherwise informs the school note only"),
        Assumption(key="marginal_cost_factor", value=0.35, low=0.25, high=0.55,
                   basis="marginal-cost framing: fixed services (roads, admin) don't "
                         "scale with infill residents. Central recalibrated 2026-08-22 "
                         "from the 0.40 literature midpoint toward the 0.30-0.34 "
                         "implied by City of Fairfax staff fiscal estimates "
                         "(WillowWood Jul 2024, Davies Jun 2025)",
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
    return apply_overrides(out, spec, notes), comp_prov


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


def _terms_of(m: MetricValue, label: str | None = None):
    """A metric's adjustment terms, degrading to a constant term so that
    composite metrics keep the sum(terms) == value invariant even when a
    component isn't adjustable. `label` renames the borrowed terms for the
    consuming metric's ledger — a revenue line pulled into a net should read
    as that revenue line, not as the donor's internal split."""
    terms = m.adjust if m.adjust else [term(m.value)]
    return terms_relabel(terms, label) if label else terms


def _giscama_values(ctx, pins) -> dict[str, float]:
    """Assessed totals for `pins` from the bulk parcel layer, keyed by the
    canonical PIN form. The layer already carries assessed_total at a ~99.6%
    join rate, so it is a free cross-check on the per-parcel WebPro pulls and
    the fallback when one of them fails."""
    try:
        parcels = ctx.parcels
    except Exception as exc:  # layer unbuilt or unreadable — not fatal here
        log.warning("parcel layer unavailable for assessment cross-check: %s", exc)
        return {}
    if "assessed_total" not in parcels.columns:
        return {}
    wanted = {norm_pin(p) for p in pins}
    out: dict[str, float] = {}
    for pin, value in zip(parcels["pin"], parcels["assessed_total"]):
        key = norm_pin(pin)
        if key in wanted and value is not None and value == value:  # not NaN
            out[key] = float(value)
    return out


def _site_assessment(spec, ctx, notes):
    """Current assessed value: prefer the extracted (document-stated) value,
    else sum per-parcel WebPro records for the resolved parcels, filling any
    parcel WebPro misses from the bulk layer.

    Partial success used to be silent: with one of three parcels resolving,
    the baseline came back confidently wrong and the RE tax increase was
    overstated by the missing parcels' current tax. Every parcel is now
    accounted for or named in a note.
    """
    if spec.existing.assessed_value:
        return (Interval.point(spec.existing.assessed_value),
                prov("Project documents (extracted spec)", spec.source_url, "current"))
    if not spec.parcels:
        notes.append("Not computed: baseline revenue — no assessed value in documents "
                     "and no resolved parcels to look up")
        return None, None
    from councilhound.impact.context.assessments import WebProClient
    client = WebProClient()
    bulk = _giscama_values(ctx, spec.parcels)
    webpro: dict[str, float] = {}
    for pin in spec.parcels:
        try:
            record = client.assessment_for_pin(pin)
        except Exception as exc:
            log.warning("WebPro lookup failed for %s: %s", pin, exc)
            record = None
        if record and record.get("total_value"):
            webpro[norm_pin(pin)] = float(record["total_value"])

    total = 0.0
    from_webpro, from_bulk, missing = [], [], []
    for pin in spec.parcels:
        key = norm_pin(pin)
        if key in webpro:
            total += webpro[key]
            from_webpro.append(pin)
        elif key in bulk:
            total += bulk[key]
            from_bulk.append(pin)
        else:
            missing.append(pin)

    if not from_webpro and not from_bulk:
        notes.append("Not computed: baseline revenue — assessment lookups failed for "
                     f"parcels {spec.parcels}")
        return None, None
    if from_bulk:
        notes.append(
            f"baseline assessed value: {len(from_webpro)} parcel(s) from WebPro, "
            f"{len(from_bulk)} from the bulk parcel layer ({', '.join(from_bulk)}) — "
            "the bulk layer's vintage may lag the current assessment roll")
    if missing:
        notes.append(
            f"WARNING: no assessed value found for parcel(s) {', '.join(missing)} — "
            "the baseline (and so the real estate tax increase) is incomplete")

    # cross-check where both sources cover the same parcels: a >10% gap is
    # usually a vintage difference, and the reader should know which is which
    shared = set(webpro) & set(bulk)
    if shared:
        w_sum = sum(webpro[k] for k in shared)
        b_sum = sum(bulk[k] for k in shared)
        if b_sum and abs(w_sum - b_sum) / b_sum > 0.10:
            notes.append(
                f"assessment sources disagree on {len(shared)} parcel(s): WebPro "
                f"${w_sum:,.0f} vs bulk parcel layer ${b_sum:,.0f} "
                f"({abs(w_sum - b_sum) / b_sum:.0%}); WebPro is used as the "
                "assessment database of record")

    source_name = "City of Fairfax Real Estate Assessment Database (Patriot WebPro)"
    if from_bulk and not from_webpro:
        source_name = "City of Fairfax bulk parcel/assessment layer (GeoHub)"
    elif from_bulk:
        source_name += " + bulk parcel/assessment layer (GeoHub)"
    return (Interval.point(total),
            prov(source_name, "https://realestate.fairfaxva.gov",
                 str(date.today().year),
                 f"parcels {', '.join(from_webpro + from_bulk)}"))


def run(spec, ctx, prior=None):
    notes: list[str] = []
    metrics: list[MetricValue] = []
    cfg = ctx.cfg
    # comps first: they seed the residential value-per-unit assumption
    comps = _comps(spec, ctx, notes) if spec.proposed.units else None
    a, comp_prov = _assumptions(spec, comps, notes)

    # revenue registry. Membership used to be a hard-coded tuple of metric
    # names matched by string, so a new revenue line silently never reached
    # the net. Every recurring-revenue metric is now added through
    # add_revenue() and the nets iterate what was actually registered.
    revenue_lines: list[MetricValue] = []

    def add_revenue(m: MetricValue) -> MetricValue:
        metrics.append(m)
        revenue_lines.append(m)
        return m

    re_rate = _rate(cfg, "tax.real_estate_rate_per_100", notes)
    rate_prov = (prov("City real estate tax rate", re_rate.source or "", re_rate.fy or "")
                 if re_rate else None)

    units = spec.proposed.units or 0
    acres = spec.proposed.acres
    site_av, site_prov = _site_assessment(spec, ctx, notes)

    # 1. baseline revenue
    if site_av is not None and re_rate is not None:
        baseline_tax = site_av * (re_rate.value / 100.0)
        metrics.append(metric("Current real estate tax (site)", baseline_tax, "$/yr",
                              [site_prov, rate_prov], [],
                              "current assessed value x RE rate / 100"))
        if acres:
            metrics.append(metric("Current value per acre", site_av * (1 / acres), "$/acre",
                                  [site_prov], [], "assessed value / site acres"))

    # 2. projected assessed value: residential + ground-floor retail + office.
    # All three components matter — proposed office space used to be omitted
    # entirely, valuing tens of thousands of square feet of proffered
    # commercial floor area at zero.
    projected_av = None
    av_terms = None
    retail_sqft = spec.proposed.retail_sqft or 0
    office_sqft = spec.proposed.office_sqft or 0
    av_assumptions = []
    if units or retail_sqft or office_sqft:
        residential = (Interval.point(units)
                       * Interval.from_assumption(a["residential_value_per_unit"]))
        commercial = (Interval.point(retail_sqft)
                      * Interval.from_assumption(a["commercial_value_per_sqft"]))
        office = (Interval.point(office_sqft)
                  * Interval.from_assumption(a["office_value_per_sqft"]))
        projected_av = residential + commercial + office
        av_terms = [term(residential.value, "Residential value",
                         residential_value_per_unit=1.0),
                    term(commercial.value, "Ground-floor commercial value",
                         commercial_value_per_sqft=1.0),
                    term(office.value, "Office/non-retail commercial value",
                         office_value_per_sqft=1.0)]
        av_assumptions = [a["residential_value_per_unit"],
                          a["commercial_value_per_sqft"],
                          a["office_value_per_sqft"]]
        metrics.append(metric(
            "Projected assessed value", projected_av, "$",
            [p for p in (comp_prov,) if p], av_assumptions,
            "units x assessed value per unit + retail sqft x $/sqft "
            "+ office sqft x $/sqft",
            adjust=av_terms))

    # 3. recurring revenue
    if projected_av is not None and re_rate is not None:
        projected_tax = projected_av * (re_rate.value / 100.0)
        rate_factor = re_rate.value / 100.0
        tax_terms = [
            term(residential.value * rate_factor, "Projected RE tax — residential",
                 residential_value_per_unit=1.0),
            term(commercial.value * rate_factor, "Projected RE tax — retail",
                 commercial_value_per_sqft=1.0),
            term(office.value * rate_factor, "Projected RE tax — office",
                 office_value_per_sqft=1.0),
        ]
        projected_tax_m = metric(
            "Projected real estate tax", projected_tax, "$/yr",
            [p for p in (comp_prov, rate_prov) if p], av_assumptions,
            "projected assessed value x RE rate / 100", adjust=tax_terms)
        metrics.append(projected_tax_m)
        if site_av is not None:
            # only the INCREASE is incremental: the site's current tax is
            # revenue the city already collects
            add_revenue(metric(
                "Real estate tax increase",
                projected_tax - site_av * (re_rate.value / 100.0),
                "$/yr", [p for p in (comp_prov, rate_prov, site_prov) if p],
                av_assumptions, "projected minus current RE tax", headline=True,
                adjust=tax_terms + [
                    term(-site_av.value * re_rate.value / 100.0,
                         "Current site RE tax (removed)")]))
        else:
            # no baseline available — the gross projected tax is the best
            # available stand-in, and the note above says the baseline failed
            revenue_lines.append(projected_tax_m)
        if acres:
            metrics.append(metric("Projected value per acre", projected_av * (1 / acres),
                                  "$/acre", [p for p in (comp_prov,) if p],
                                  av_assumptions, "projected AV / site acres"))

    # personal property: per-household budget actuals when pinned (preferred),
    # else a rate-based vehicle estimate — explicitly labeled a rough estimate
    households_m = _prior_metric(prior, "New households")
    pp_actuals = cfg.tax.personal_property_per_household
    if households_m and pp_actuals.value is not None:
        households = _interval_from_metric(households_m)
        add_revenue(metric(
            "Personal property tax (new households)", households * pp_actuals.value, "$/yr",
            [prov("City budget per-household personal property actuals",
                  pp_actuals.source or "", pp_actuals.fy or "")],
            [], "new households x per-household personal property revenue",
            adjust=terms_scale(_terms_of(households_m, "Personal property tax"),
                               pp_actuals.value)))
    elif households_m:
        pp_rate = _rate(cfg, "tax.personal_property_rate_per_100", notes)
        if pp_rate:
            households = _interval_from_metric(households_m)
            vehicles = households * Interval.from_assumption(a["vehicles_per_household"])
            pp_est = (vehicles * Interval.from_assumption(a["avg_vehicle_assessed_value"])
                      * (pp_rate.value / 100.0))
            pp_terms = terms_pow_extend(
                terms_scale(_terms_of(households_m, "Personal property tax"),
                            a["vehicles_per_household"].value
                            * a["avg_vehicle_assessed_value"].value
                            * pp_rate.value / 100.0),
                vehicles_per_household=1.0, avg_vehicle_assessed_value=1.0)
            add_revenue(metric(
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

    # -- the project's own commercial space -------------------------------
    # Taxes on on-site sales are DISPLACEMENT-ADJUSTED. A new restaurant in
    # town collects meals tax, but most of its receipts are captured from
    # existing city restaurants, which stop collecting it; only the net-new
    # share adds to the city's base. Counting gross receipts (as applicant
    # fiscal analyses typically do) would overstate the city's gain.
    own_capture_m = _prior_metric(prior, "Annual capture: project's own ground-floor retail")
    net_new = Interval.from_assumption(a["net_new_share"])
    onsite_base = None
    if retail_sqft:
        receipts = (Interval.point(retail_sqft)
                    * Interval.from_assumption(a["retail_sales_per_sqft"]))
        onsite_base = receipts
        # new residents' own spending at the project's ground floor is already
        # counted at full weight in the resident-side capture lines below, and
        # it is genuinely new to the city — subtract it here so it is neither
        # double-counted nor discounted by the displacement factor
        if own_capture_m:
            onsite_base = receipts - Interval.point(own_capture_m.value)
            notes.append(
                "On-site commercial tax lines exclude ${:,.0f}/yr of new-resident "
                "spending at the project's own ground floor, which is already "
                "counted in full in the resident-capture lines.".format(
                    own_capture_m.value))

    bpol_rate = _rate(cfg, "tax.bpol_retail_rate_per_100", notes)
    if bpol_rate and onsite_base is not None:
        bpol_factor = bpol_rate.value / 100.0
        bpol_terms = [term(retail_sqft * a["retail_sales_per_sqft"].value
                           * bpol_factor * a["net_new_share"].value,
                           "BPOL on project retail",
                           retail_sales_per_sqft=1.0, net_new_share=1.0)]
        if own_capture_m:
            bpol_terms += terms_pow_extend(
                terms_scale(_terms_of(own_capture_m, "BPOL — resident spending removed"),
                            -bpol_factor * a["net_new_share"].value),
                net_new_share=1.0)
        add_revenue(metric(
            "BPOL business license tax on project retail (rough estimate)",
            onsite_base * bpol_factor * net_new, "$/yr",
            [prov("City BPOL rate schedule (budget Rates & Levies)",
                  bpol_rate.source or "", bpol_rate.fy or "",
                  "retail-sales rate applied to the whole space; the "
                  "repair/personal/business-services classification is taxed "
                  "at $0.27 per $100, slightly above the retail rate")],
            [a["retail_sales_per_sqft"], a["net_new_share"]],
            "ROUGH ESTIMATE: proposed retail sqft x assumed gross sales per "
            "sqft x BPOL retail rate / 100 x net-new share — receipts displaced "
            "from existing city businesses stop paying BPOL at their old location",
            adjust=bpol_terms))
        notes.append(
            "BPOL revenue is a rough estimate: the city rate schedule is "
            "pinned, but tenant gross receipts are assumed from a sales-per-"
            "sqft range.")

    # office BPOL: a separate business class at its own rate. Not
    # displacement-adjusted — professional and medical practices draw
    # regional demand rather than recirculating local retail spending.
    office_bpol_rate = _rate(cfg, "tax.bpol_office_rate_per_100", notes)
    if office_bpol_rate and office_sqft:
        office_receipts = (Interval.point(office_sqft)
                           * Interval.from_assumption(a["office_receipts_per_sqft"]))
        add_revenue(metric(
            "BPOL business license tax on project office (rough estimate)",
            office_receipts * (office_bpol_rate.value / 100.0), "$/yr",
            [prov("City BPOL rate schedule (budget Rates & Levies)",
                  office_bpol_rate.source or "", office_bpol_rate.fy or "",
                  "professional/business-services class rate")],
            [a["office_receipts_per_sqft"]],
            "ROUGH ESTIMATE: proposed office sqft x assumed gross receipts per "
            "sqft x BPOL professional rate / 100 — not displacement-adjusted, as "
            "professional and medical practices serve regional demand",
            adjust=[term(office_sqft * a["office_receipts_per_sqft"].value
                         * office_bpol_rate.value / 100.0, "BPOL on project office",
                         office_receipts_per_sqft=1.0)]))

    # business tangible personal property: equipment physically new to the
    # city, so not displacement-adjusted either
    bpp_rate = _rate(cfg, "tax.bpp_rate_per_100", notes)
    commercial_sqft = retail_sqft + office_sqft
    if bpp_rate and commercial_sqft:
        bpp_base = (Interval.point(commercial_sqft)
                    * Interval.from_assumption(a["bpp_value_per_sqft"]))
        add_revenue(metric(
            "Business tangible property tax (rough estimate)",
            bpp_base * (bpp_rate.value / 100.0), "$/yr",
            [prov("City business tangible property tax rate",
                  bpp_rate.source or "", bpp_rate.fy or "")],
            [a["bpp_value_per_sqft"]],
            "ROUGH ESTIMATE: proposed commercial sqft x assumed equipment value "
            "per sqft x BPP rate / 100. Not displacement-adjusted: fixtures and "
            "equipment are physically new to the city, though a relocating "
            "tenant brings existing equipment with it",
            adjust=[term(commercial_sqft * a["bpp_value_per_sqft"].value
                         * bpp_rate.value / 100.0, "Business tangible property tax",
                         bpp_value_per_sqft=1.0)]))

    meals_rate = _rate(cfg, "tax.meals_tax_rate", notes)
    food_away_m = _prior_metric(prior, "New annual spending: restaurant_bar")
    in_city_food_m = _prior_metric(prior, "In-city capture share: food_away")
    if meals_rate and food_away_m and in_city_food_m:
        meals_base = (_interval_from_metric(food_away_m)
                      * _interval_from_metric(in_city_food_m))
        add_revenue(metric(
            "Meals tax on captured in-city dining", meals_base * meals_rate.value, "$/yr",
            [prov("City meals tax rate", meals_rate.source or "", meals_rate.fy or "")],
            [], "restaurant spending x in-city capture share x meals tax rate "
                "(cross-module link from the economic Huff run)",
            adjust=terms_scale(_terms_of(food_away_m, "Meals tax"),
                               in_city_food_m.value * meals_rate.value)))
    elif meals_rate and not food_away_m:
        notes.append("Meals tax not computed: economic module results unavailable")

    # meals tax on the project's OWN restaurant space — the line applicant
    # analyses lead with and this model previously had no term for at all
    if meals_rate and onsite_base is not None:
        restaurant_share = Interval.from_assumption(a["onsite_restaurant_share_of_retail"])
        onsite_meals = onsite_base * restaurant_share * meals_rate.value * net_new
        share_v = a["onsite_restaurant_share_of_retail"].value
        factor = meals_rate.value * share_v * a["net_new_share"].value
        onsite_meals_terms = [
            term(retail_sqft * a["retail_sales_per_sqft"].value * factor,
                 "Meals tax on project restaurants", retail_sales_per_sqft=1.0,
                 onsite_restaurant_share_of_retail=1.0, net_new_share=1.0)]
        if own_capture_m:
            onsite_meals_terms += terms_pow_extend(
                terms_scale(_terms_of(own_capture_m,
                                      "Meals tax — resident spending removed"), -factor),
                onsite_restaurant_share_of_retail=1.0, net_new_share=1.0)
        add_revenue(metric(
            "Meals tax on the project's own restaurants (net-new, rough estimate)",
            onsite_meals, "$/yr",
            [prov("City meals tax rate", meals_rate.source or "", meals_rate.fy or "")],
            [a["retail_sales_per_sqft"], a["onsite_restaurant_share_of_retail"],
             a["net_new_share"]],
            "ROUGH ESTIMATE: ground-floor sqft x assumed sales per sqft x assumed "
            "restaurant share x meals tax rate x net-new share — receipts displaced "
            "from existing city restaurants were already taxed there",
            adjust=onsite_meals_terms))

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
                sales_terms += terms_scale(_terms_of(m, "Local sales tax"),
                                           in_city_all_m.value * sales_rate.value)
            add_revenue(metric(
                "Local sales tax share on captured in-city retail",
                base * sales_rate.value, "$/yr",
                [prov("Local-option sales tax share", sales_rate.source or "",
                      sales_rate.fy or "")],
                [], "in-city captured retail spend x local sales tax share",
                adjust=sales_terms))

    # local sales tax on the project's own retail sales, same net-new framing
    if sales_rate and onsite_base is not None:
        factor = sales_rate.value * a["net_new_share"].value
        onsite_sales_terms = [
            term(retail_sqft * a["retail_sales_per_sqft"].value * factor,
                 "Local sales tax on project retail",
                 retail_sales_per_sqft=1.0, net_new_share=1.0)]
        if own_capture_m:
            onsite_sales_terms += terms_pow_extend(
                terms_scale(_terms_of(own_capture_m,
                                      "Local sales tax — resident spending removed"),
                            -factor),
                net_new_share=1.0)
        add_revenue(metric(
            "Local sales tax on the project's own retail (net-new, rough estimate)",
            onsite_base * sales_rate.value * net_new, "$/yr",
            [prov("Local-option sales tax share", sales_rate.source or "",
                  sales_rate.fy or "")],
            [a["retail_sales_per_sqft"], a["net_new_share"]],
            "ROUGH ESTIMATE: ground-floor sqft x assumed sales per sqft x local "
            "sales tax share x net-new share (prepared food is subject to both "
            "this and the meals tax, as under state law)",
            adjust=onsite_sales_terms))

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
            school_terms = [term(school_cost.value, "School cost", students_per_unit=1.0)]
            resident_terms = terms_scale(
                _terms_of(residents_m, "Service cost — non-school"), nonschool_percap)
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
            naive_terms = terms_scale(
                _terms_of(residents_m, "Service cost — per capita"), per_capita)
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
            adjust=[term(students.value, "Estimated students", students_per_unit=1.0)]))

        # net fiscal impact: INCREMENTAL revenue minus the cost range, summed
        # over every line registered through add_revenue. The per-household and
        # vehicle-estimate personal property lines are mutually exclusive
        # above, so both being registered cannot double count.
        revenue = None
        revenue_terms = []
        for m in revenue_lines:
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

    _external_estimates(spec, metrics, notes, projected_av)

    result = ModuleResult(module="fiscal", metrics=metrics,
                          narrative_notes=notes, assumptions=list(a.values()))
    return result, {}


_KIND_LABELS = {"applicant_fia": "applicant fiscal impact analysis",
                "staff_report": "city staff report",
                "other": "other published estimate"}


def _external_estimates(spec, metrics, notes, projected_av):
    """Publish the applicant's and staff's own fiscal estimates alongside ours,
    and check our assessed value against any stated construction cost.

    These are never averaged into our figures — they are a benchmark. When an
    independent estimate lands outside our range, that disagreement is the
    most useful thing on the page, so it gets stated plainly rather than
    smoothed over.
    """
    estimates = getattr(spec, "external_estimates", None) or []
    if not estimates:
        return

    net_ours = next((m for m in metrics if m.name
                     == "Net annual fiscal impact (range across both cost methods)"), None)
    published: set[tuple] = set()
    used_names: set[str] = set()
    for est in estimates:
        label = _KIND_LABELS.get(est.kind, est.kind)
        source_prov = prov(f"{label}: {est.source}", est.url or spec.source_url,
                           est.fy or "as published",
                           f'stated: "{est.quote}"' if est.quote else None)
        low, high = est.net_annual_low, est.net_annual_high
        if low is None and high is None:
            continue
        low = low if low is not None else high
        high = high if high is not None else low
        # the same estimate often appears in several documents (a staff report
        # split into parts, a summary repeating the analysis) — publish once
        if (est.kind, low, high) in published:
            continue
        published.add((est.kind, low, high))
        mid = (low + high) / 2.0
        name = f"External estimate: {label} — net annual fiscal impact"
        if name in used_names:  # several distinct estimates of the same kind
            name = (f"External estimate: {label} ({est.fy or est.source}) — "
                    "net annual fiscal impact")
        used_names.add(name)
        metrics.append(MetricValue(
            name=name,
            value=mid, unit="$/yr", low=min(low, high), high=max(low, high),
            provenance=[source_prov], assumptions=[],
            method=f"reported by the {label}; not computed by this pipeline and "
                   "not combined with the estimates above",
            adjust=None))
        if net_ours is not None:
            ours_low = net_ours.low if net_ours.low is not None else net_ours.value
            ours_high = net_ours.high if net_ours.high is not None else net_ours.value
            overlaps = max(ours_low, min(low, high)) <= min(ours_high, max(low, high))
            notes.append(
                "BENCHMARK: this analysis puts the net annual fiscal impact at "
                f"${ours_low:,.0f} to ${ours_high:,.0f}; the {label} states "
                f"${min(low, high):,.0f} to ${max(low, high):,.0f}. The ranges "
                + ("overlap." if overlaps else
                   "do NOT overlap — the methods disagree on the sign or scale of "
                   "the result, and the reader should compare them directly.")
                + " External figures are reported as published, never merged into "
                "the estimates above.")

    # sanity gate: new construction that assesses at a small fraction of its
    # own stated cost basis is a signal that the per-unit value input is wrong
    costs = [e.construction_cost for e in estimates if e.construction_cost]
    if costs and projected_av is not None:
        cost = max(costs)
        ratio = projected_av.value / cost if cost else None
        if ratio is not None and not (0.5 <= ratio <= 1.5):
            notes.append(
                f"SANITY: the projected assessed value (${projected_av.value:,.0f}) is "
                f"{ratio:.0%} of the stated construction cost basis (${cost:,.0f}). New "
                "construction typically assesses at roughly 70-110% of hard cost, so a "
                "figure far outside that band usually means the assessed value per unit "
                "is drawn from the wrong product class — review "
                "`residential_value_per_unit`.")


def _comps(spec, ctx, notes):
    """Assessment comps for the project's residential product class.

    For-sale projects are valued against condominium comps when the
    jurisdiction has pinned a condo land-use code; apartment comps understate
    a for-sale condo's assessed value several-fold, which was the single
    largest error in the fiscal model. Without a pinned condo code, this
    returns nothing and the caller falls back to a screening default rather
    than silently pricing condos as apartments.
    """
    from councilhound.impact.context.assessments import (APARTMENT_LUC,
                                                         WebProClient)

    lucs = getattr(ctx.cfg, "assessment_lucs", None) or {}
    for_sale = is_for_sale(spec)
    if for_sale:
        luc = lucs.get("condo")
        if not luc:
            notes.append(
                "This is a FOR-SALE residential project, but the jurisdiction has "
                "no pinned condominium land-use code (assessment_lucs.condo), so "
                "no comps were queried — apartment comps would understate for-sale "
                "value several-fold. Run `impact-probe-luc` and pin the code.")
            return None
        unit_mode, window, klass = "per_account", 5, "condominium"
    else:
        luc = lucs.get("apartment") or APARTMENT_LUC
        unit_mode, window, klass = "per_building", 0, "apartment"

    try:
        comps = WebProClient().residential_comps(
            built_since=date.today().year - COMP_LOOKBACK_YEARS,
            luc=luc, unit_mode=unit_mode, year_window=window)
    except Exception as exc:
        log.warning("comp query failed: %s", exc)
        notes.append(f"Not computed: assessment comps — comp query failed ({exc})")
        return None
    log.info("%d %s comp(s) for LUC %s", len(comps), klass, luc)
    return comps
