# Non-school service cost scaling — reference library

Collected 2026-07-27 to answer a specific challenge to the fiscal module:
**does non-school municipal service cost really scale linearly with new
residents, especially for dense infill housing?** That question sits under
the `marginal_cost_factor` assumption in
`ingestion/src/councilhound/impact/modules/fiscal.py`, which previously
carried only an unsourced basis ("fixed services don't scale with infill
residents"). Companion pages: `WALK_ECONOMIC_IMPACT_REFERENCES.md`,
`BIKE_IMPACT_REFERENCES.md`.

---

## What the model does today

Two cost framings are published side by side, and the net fiscal impact is
reported as a range spanning both:

- **Naive per-capita** — `residents × non-school GF per capita`, i.e.
  strictly **linear** in residents. For Fairfax City: (\$207,912,496 GF −
  \$76,429,791 education transfer) / 25,026 residents = **\$5,254 per
  resident-year** of non-school cost.
- **Marginal framing** — the same figure × `marginal_cost_factor`
  (**0.40**, range 0.25–0.60).

School costs are already excluded from both and driven separately by the
project's own student estimate, which is the single largest correction —
education is 37% of the Fairfax general fund.

So the model already rejects pure linearity. The open question is whether
**0.40 (0.25–0.60)** is the defensible number, and in which direction the
evidence points.

---

## Literature 1 — marginal vs. average cost (the directly relevant one)

This is the literature that actually addresses "should a new development be
charged the average cost per resident?"

### Kotval & Mullin — *Fiscal Impact Analysis: Methods, Cases, and Intellectual Debate* (Lincoln Institute of Land Policy working paper)
- **Local:** `kotval-mullin-lincoln-fiscal-impact-analysis-methods.pdf`
- https://www.lincolninst.edu/sites/default/files/pubfiles/kotval-wp06zk2.pdf
- Splits the field into **average costing** (per-capita multiplier, service
  standard, proportional valuation) and **marginal costing** (case study,
  comparable cities, employee anticipation) — the taxonomy originating with
  Burchell & Listokin's *Fiscal Impact Handbook*. The model's naive framing
  is literally the per-capita multiplier method; the marginal framing is a
  crude stand-in for a case-study method.
- **The key guidance, quoted in substance:** average costing "work[s] well in
  mid-sized communities that are experiencing slow to moderate growth and
  where service delivery is steady and in sync with demands." Marginal
  costing is better "where growth is rapid or unexpected and new development
  has the potential to change the land use character as well as service
  delivery mechanisms."
- **Critical nuance that cuts against a naive discount:** their worked
  example of why marginal costing matters is a community whose growth forces
  a switch from volunteer to salaried fire protection — "marginal costing
  methods will pick up the increased costs associated with the change while
  average costing methods will not." **Marginal cost can exceed average
  cost** when growth crosses a capacity threshold. Our
  `marginal_cost_factor` range (0.25–0.60) lies entirely below 1.0 and
  therefore encodes only the excess-capacity direction.

### Burchell & Listokin — *The Fiscal Impact Handbook* (1978) and *Development Impact Assessment Handbook* (1994)
- Link only (print/paywalled). The origin of the six-method taxonomy and of
  the per-capita multiplier the module uses. Also the source of the
  demographic-multiplier approach already cited for
  `avg_hh_size_multifamily` (see `WALK_ECONOMIC_IMPACT_REFERENCES.md`).

### UNH Cooperative Extension — *An Introduction to Fiscal Impact Analysis*
- **Local:** `unh-introduction-to-fiscal-impact-analysis.pdf`
- https://extension.unh.edu/resources/files/Resource002700_Rep3989.pdf
- Practitioner-level statement of the same average/marginal distinction:
  average methods assume each added unit imposes the average cost; marginal
  methods account for **under- or over-utilisation of existing capacity**.
  Useful plain-language framing for the assumption's rationale string.

**Takeaway for the model:** the excess-capacity argument for a factor below
1.0 is well-founded *for infill in an already-served area* — no new road
miles, mains, or service territory. But the literature does not license
treating the factor as strictly < 1: threshold effects (a new fire company,
a new shift) push marginal cost above average, and the current 0.25–0.60
interval cannot express that.

---

## Literature 2 — density and per-capita cost (contested, and often misapplied)

This is the literature people reach for when arguing "dense housing is
cheaper to serve." It is **genuinely mixed**, and it answers a
cross-sectional question (do denser *jurisdictions* spend less per capita?)
rather than the marginal question the model asks.

### Ladd (1992) — *Population Growth, Density and the Costs of Providing Public Services*, Urban Studies 29(2): 273–295
- Link only (paywalled): https://doi.org/10.1080/00420989220080321
- 247 large county areas, 1985. Finds a **U-shaped** relationship between
  per-capita current spending and density — the seminal result in this
  debate. Reported trough around **250 residents/sq mi**; counties above
  ~24,000/sq mi spend roughly **43% more** per capita than counties in the
  optimal range, with a similar pattern for public-safety spending.
- **Direction matters:** above the trough, higher density is associated with
  *higher* per-capita cost, not lower — congestion, higher input costs, more
  service-intensive settings.
- **Scale caveat before applying this locally:** the units are whole
  counties including rural land, so a 250/sq mi trough is not transferable
  to a 6.3 sq mi city. Fairfax City sits at ~**3,991 residents/sq mi**
  (25,026 / 6.27 sq mi) — above Ladd's trough but an order of magnitude
  below her high-cost tail.

### Carruthers & Ulfarsson (2003) — *Urban Sprawl and the Cost of Public Services*, Environment and Planning B 30(4)
- Link only: https://doi.org/10.1068/b12847
- 283 metropolitan counties, 1982–92, twelve separate expenditure
  categories (total direct, capital facilities, roadways, other
  transportation, sewerage, trash, housing/community development, police,
  fire, parks, education, libraries). Finds **density negative and
  significant** for overall spending, capital facilities, roadways, police
  protection, and education — i.e. the opposite sign to Ladd — and
  insignificant for sewerage.
- The per-category structure is the most useful feature for us: it says the
  scaling question has a different answer per service line, which a single
  blended `marginal_cost_factor` necessarily averages over.

### Benito, Bastida & Guillamón (2010) — *Urban Sprawl and the Cost of Public Services: An Evaluation of Spanish Local Governments*, Lex Localis 8(3): 245–264
- **Local:** `carruthers-ulfarsson-urban-sprawl-cost-public-services.pdf`
  (filename reflects the search that found it; the PDF is the Spanish
  local-government study, whose value here is its **literature review**)
- https://lex-localis.org/index.php/LexLocalis/article/download/8.3.245-264(2010)/97/430
- Its review section is the cleanest available summary of how unsettled
  this is, and is worth quoting in the assumption basis:
  - per-capita spending **rises** with density: Ladd & Yinger (1991),
    Ladd (1992, 1994), Holcombe & Williams (2008)
  - per-capita spending **falls** with density: Downing (1969), Dajani
    (1973), Carruthers & Ulfarsson (2003, 2008), Burchell & Mukherji
    (2003), Litman (2004)
  - **little significance**: Cox & Utt (2004)
  - and Ladd (1992) specifically identifies the U-shape that reconciles
    some of the disagreement.
- Also notes economies of scale produce a U-shaped cost function with the
  positive-slope inflection at ~250,000 inhabitants (Shapiro 1963) or
  ~50,000 (Schmandt & Stephens 1963) — both far above Fairfax's 25,026, so
  scale economies should still be available here.

### Holcombe & Williams (2008) — *The Impact of Population Density on Municipal Government Expenditures*, Public Finance Review 36(3)
- Link only: https://doi.org/10.1177/1091142107308302
- On the "density raises per-capita cost" side; useful as the counterweight
  citation so the basis string does not cherry-pick one direction.

### Smart Growth America (2013) — *Building Better Budgets: A National Examination of the Fiscal Benefits of Smart Growth Development*
- Link only (direct PDF blocked by the host; page:
  https://smartgrowthamerica.org/resources/building-better-budgets-a-national-examination-of-the-fiscal-benefits-of-smart-growth-development/)
- Meta-review of development cost/revenue studies. Headline figures: smart
  growth (compact, higher-density, mixed-use) saves ~**38% on upfront
  infrastructure** and about **10% on ongoing delivery of municipal
  services** versus conventional low-density development.
- **This is the most directly usable number for our purposes** and it is
  sobering: the ongoing-services saving attributable to compact form is
  about **10%**, not the ~60% discount implied by a 0.40 factor. The two
  numbers are not measuring the same thing — SGA compares development
  *patterns* at average cost, while our factor compares *marginal to
  average* within one city — but any argument that leans on "density is
  cheaper to serve" should be sized against 10%, not 60%.

---

## What this implies for `marginal_cost_factor` (0.40, 0.25–0.60)

1. **The direction is defensible; the magnitude is the weak part.** The
   excess-capacity case for marginal < average is standard fiscal-impact
   practice, and infill in an already-served city is its best case. But no
   source found here supports a specific 0.40 central, and the one clean
   empirical figure for compact development's ongoing-service advantage is
   ~10%.
2. **The interval cannot express threshold effects.** Kotval & Mullin's
   fire-service example is exactly the case where marginal > average. A
   ceiling of 0.60 asserts that growth never triggers a capacity step. For a
   261-unit building that is probably fine; for a large project or a
   cumulative pipeline it is an assumption worth stating rather than hiding.
3. **A single blended factor averages over services that behave
   differently.** Carruthers & Ulfarsson estimate twelve categories
   separately for a reason: roads and police scale with area and calls,
   trash and water with households, admin barely at all. A per-category
   split is the principled version of this assumption.
4. **The density literature should be cited carefully, in both
   directions.** It is contested, and the U-shape means "denser is cheaper"
   is not a safe general claim — above the trough it reverses. Citing only
   the pro-density side would be cherry-picking.

**Recommended encoding** (not yet applied — see below): keep the 0.40
central, widen the interval to roughly **0.25–0.85** so the upper bound can
represent "growth largely absorbed at average cost / a capacity step is
triggered," and rewrite the basis to cite Kotval & Mullin for the
average-vs-marginal frame, SGA's ~10% ongoing-service figure as the
compact-form anchor, and Ladd / Carruthers & Ulfarsson as the contested
density evidence with the U-shape stated explicitly.

---

## Status

Research only — **no code change applied yet**. Changing
`marginal_cost_factor` moves the published net-fiscal range on every
residential project, so it needs its own re-run and push rather than riding
along with the in-flight label re-run.
