# CouncilLens Development Impact Methodology

## Abstract

CouncilLens produces screening-level impact estimates for proposed development projects. The current project report combines a deterministic economic module, a deterministic fiscal module, and a generated narrative that is constrained to use only structured model outputs. This note documents how each metric shown on a project page is calculated, which assumptions drive uncertainty ranges, and where the present model could be strengthened with additional sources.

The estimates should be read as decision-support evidence rather than forecasts. They are intended to rank likely orders of magnitude, expose assumptions, and separate traceable calculations from narrative interpretation.

## Data And Literature Basis

The economic module follows a spatial-interaction tradition. Retail capture is modeled with a Huff-style probabilistic gravity model, after Huff's formulation of shopping-center trade areas as attraction divided by distance or impedance-weighted competition: David L. Huff, "A Probabilistic Analysis of Shopping Center Trade Areas," Land Economics 39, no. 1 (1963), 81-90 ([record](https://www.semanticscholar.org/paper/A-Probabilistic-Analysis-of-Shopping-Center-Trade-Huff/d35f5666d9455a4cb8a6c75898a95d8109858784)). Household spending inputs come from the U.S. Bureau of Labor Statistics Consumer Expenditure Surveys, which provide expenditure, income, and demographic data for consumer units ([BLS CE](https://www.bls.gov/cex/)). Household size and income inputs use American Community Survey tables including B25010 for household size and B19013 for median household income ([Census B19013](https://data.census.gov/table/ACSDT5Y2023.B19013)).

Walk-network measures use OpenStreetMap street graphs through OSMnx. The appropriate software citation is Boeing (2017), "OSMnx: A Python package to work with graph-theoretic OpenStreetMap street networks," Journal of Open Source Software, 2(12), 215 ([JOSS](https://joss.theoj.org/papers/10.21105/joss.00215)). Daily walking trip inputs cite the 2022 National Household Travel Survey, a household travel survey expanded to estimate trips and miles by mode and purpose ([NHTS](https://nhts.ornl.gov/); [BTS record](https://rosap.ntl.bts.gov/view/dot/73764)).

The fiscal module follows the public-finance planning literature that distinguishes average-cost and marginal-cost fiscal impact analysis. Kotval and Mullin describe fiscal impact analysis as estimating public costs and revenues resulting from property investment ([Lincoln Institute working paper](https://www.lincolninst.edu/app/uploads/legacy-files/pubfiles/kotval-wp06zk2.pdf)). A University of Delaware literature review summarizes average-cost and marginal-cost approaches as the two basic methods, with average cost assigning per-unit costs and marginal cost estimating next-unit costs ([UD review](https://udspace.udel.edu/bitstreams/6513e9c9-528c-40a1-9e23-ab00317ab333/download)). The current module deliberately reports both framings.

## Economic Metrics

### New Households

Formula: proposed units x `occupancy_rate`.

The occupancy assumption represents stabilized multifamily occupancy. Its low and high values propagate directly to the range.

### New Residents

Formula: new households x `avg_hh_size_renter`.

Renter household size is derived from ACS B25010 for populated local block groups, with population weighting. The uncertainty range is carried by `occupancy_rate` and `avg_hh_size_renter`.

### Aggregate Household Income

Formula: new households x site-area median household income x `income_premium_new_construction`.

The site-area income comes from ACS B19013, using the site's census tract when available and falling back to a citywide mean when tract medians are suppressed. The new-construction premium is an explicit screening assumption.

### New Annual Spending By Category

Formula: aggregate household income x Consumer Expenditure Survey category share x `ces_scale`.

Current categories are grocery, restaurant and bar, comparison retail, convenience retail, personal services, and entertainment. The CE table is income-scaled from the national average consumer-unit income to the modeled site income. The `ces_scale` assumption carries regional and vintage uncertainty.

### Annual Capture By Named Area

Formula: category spending allocated to individual retail points by a Huff model, then rolled up to DBSCAN reporting clusters.

For each retail destination, attractiveness is represented by POI count or equivalent own-retail attractiveness. Travel impedance uses the model's drive and walk travel times with exponential decay. Cluster values are reporting aggregates only; the allocation itself is per business point. Assumptions include `beta_walk`, mode-share assumptions, and `ces_scale`.

### In-City Capture Share

Formula: captured spending at destinations inside the city boundary / total captured spending.

Separate shares are produced for food-away spending and all retail. These shares feed fiscal meals-tax and local sales-tax calculations. The range comes from the same Huff and walk-mode assumptions used in capture.

### Annual Capture At Project Ground-Floor Retail

Formula: Huff-allocated spending captured by the project's own modeled retail destination.

The project's retail square footage is converted to equivalent POI attractiveness using `own_retail_sqft_per_equiv_poi`, then assigned a retail mix. This lets the proposed ground-floor retail compete with existing businesses instead of being added outside the spatial model.

### On-Site Jobs Removed, Jobs Added, And Net Job Change

Formulas:

- jobs removed = existing commercial square feet / `sqft_per_office_job`
- jobs added = proposed retail square feet / `sqft_per_retail_job`
- net job change = retail jobs added - existing jobs removed

These are site-activity screening metrics. They do not model indirect or induced employment.

### New Annual Spending Arriving On Foot

Formula: walk-mode share of the joint destination-and-mode Huff choice, summed over businesses.

This is not total pedestrian commerce. It is the portion of modeled new-resident spending whose destination and mode jointly resolve to walking. Distant businesses can still capture spending by car while receiving little walk-arriving spending.

### Spending Arriving On Foot At Project Retail

Formula: walk-mode share of the joint Huff choice for the project's own retail destination.

This isolates the walk-arriving part of the project's own retail capture. It uses the same own-retail attractiveness and walk impedance assumptions as the total own-retail capture metric.

### New Resident Walk Trips Per Day

Formula: new residents x `walk_trips_per_resident_day`.

The trip rate is sourced to NHTS-style daily walking-trip evidence. The model treats these as all-purpose resident walking trips, not only shopping trips.

### Foot-Traffic Index Change

Formula: exact marginal site-origin walk-trip flows on shortest paths / sampled baseline pedestrian-betweenness index for the nearest commercial street segments.

The numerator assigns new resident walk trips from the project to POI-weighted destinations with distance decay, then routes those trips over the walk network. The denominator is a seeded sampled baseline of existing population-to-destination walk opportunities. Without local pedestrian counts, the percent is an index comparison, not a calibrated count.

### Implied Spending Per Resident Walk Trip

Formula: total walk-arriving annual spending / (new resident walk trips per day x 365).

This is a diagnostic. Values outside the plausible range indicate tension between the retail mode-share assumptions and the all-purpose walking trip rate.

## Fiscal Metrics

### Current Real Estate Tax And Current Value Per Acre

Formulas:

- current real estate tax = current assessed value x real-estate tax rate / 100
- current value per acre = current assessed value / site acres

Current assessed value comes first from extracted project documents, then from parcel assessment records when available. The tax rate is jurisdiction-configured with provenance.

### Projected Assessed Value, Projected Real Estate Tax, And Projected Value Per Acre

Formulas:

- projected assessed value = median comparable multifamily value per unit x proposed units + proposed retail square feet x `commercial_value_per_sqft`
- projected real estate tax = projected assessed value x real-estate tax rate / 100
- projected value per acre = projected assessed value / site acres

Comparable multifamily parcels built within the lookback window provide the residential value range. Retail value uses a screening dollars-per-square-foot assumption until commercial comps are added.

### Real Estate Tax Increase

Formula: projected real estate tax - current real estate tax.

This metric is emitted when both baseline and projected tax can be computed.

### Personal Property Tax

Formula: new households x jurisdiction-configured personal-property revenue per household.

This is a local average revenue screen, not a household vehicle ownership model.

### Meals Tax On Captured In-City Dining

Formula: restaurant/bar spending x in-city food-away capture share x meals-tax rate.

This is a cross-module metric. It depends on the economic module's capture share rather than assuming all new dining spending occurs inside the city.

### Local Sales Tax Share On Captured In-City Retail

Formula: taxable retail categories x in-city all-retail capture share x local sales-tax share.

The current taxable base includes grocery, comparison retail, and convenience retail categories as represented in the CE-to-POI taxonomy, with the local capture share supplied by the Huff model.

### Annual Service Cost, Naive Per-Capita Method

Formula: new residents x general-fund expenditure per resident.

This is intentionally an upper-bound framing because it assigns average citywide costs, including fixed costs, to incremental residents.

### Annual Service Cost, Marginal Framing

Formula: naive per-capita cost x `marginal_cost_factor`.

This reflects the literature's distinction between average-cost and marginal-cost fiscal impact analysis. It can understate costs if the project triggers capital expansion or staffing thresholds.

### Net Annual Fiscal Impact

Formulas:

- net, naive method = total new recurring revenue - naive per-capita service cost
- net, marginal method = total new recurring revenue - marginal service cost
- range across both cost methods = conservative revenue/cost endpoints across the two methods

The project page reports the range across both cost methods because neither method is universally correct for infill development.

## Sources That Would Improve The Model

1. Local pedestrian or mobile-location counts. These would calibrate the foot-traffic layer from a relative index to estimated observed segment volumes.

2. Local retail sales leakage studies or anonymized card-spend data. These would calibrate Huff decay parameters, category capture shares, and the in-city retention assumptions.

3. Parcel-level commercial lease, sales, and assessment comparables. These would replace the current `commercial_value_per_sqft` screening range for ground-floor retail.

4. Local multifamily resident generation studies by building type, tenure, and bedroom mix. These would refine `avg_hh_size_renter`, `students_per_unit`, and occupancy assumptions.

5. Jurisdiction department marginal-cost interviews or service-capacity data. These would replace the broad `marginal_cost_factor` range with department-specific marginal costs.

6. BPOL and business-license receipts by NAICS category. These would allow the fiscal module to add business-license revenue from proposed commercial space.

7. Local trip-purpose walking rates by neighborhood context. These would improve the link between all-purpose resident walk trips and walk-arriving retail spending.
