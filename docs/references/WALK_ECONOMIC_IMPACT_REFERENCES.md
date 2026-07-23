# Walk / overall economic impact module — reference library

Collected 2026-07-22, backfilling literature anchors for every assumption in
the development economic module
(`ingestion/src/councilhound/impact/modules/economic.py`) — the model behind
the "Overall Economic Impact" and "Walk-Based Impact" maps. Several
assumptions predate the bike round and carried only "industry norm" /
"methodology brief default" as basis; this page gives each one a citable
source, transcribes the key values, and flags the places where the found
evidence disagrees with the current encoding. Local PDFs live in this
directory; paywalled sources are link-only. Companion page:
`BIKE_IMPACT_REFERENCES.md`.

---

## Demand block

### `occupancy_rate` = 0.95 (0.90–0.97)
- **Census Housing Vacancies and Homeownership (HVS), quarterly.**
  **Local:** `census-hvs-current-quarterly-vacancies.pdf`;
  https://www.census.gov/housing/hvs/current/index.html
- All-rental national vacancy ran **7.1–7.2%** through 2025 (highest Q3
  reading since 2018) → ~92.9% occupancy across the whole rental stock,
  supporting the 0.90 floor. Professionally managed stabilized multifamily
  runs tighter — Yardi Matrix reported **5.3%** multifamily vacancy
  (Sep 2025) → ~94.7% occupied, matching the 0.95 center; 0.97 is the
  tight-market top. The center is the standard stabilized-underwriting
  figure for exactly the product the module models (new professionally
  managed multifamily).

### `avg_hh_size_multifamily` = 1.8 (1.5–2.2)
- **Rutgers CUPR Residential Demographic Multipliers (Listokin, Voicu,
  Dolphin & Camp, 2006).** **Local:**
  `rutgers-cupr-2006-residential-demographic-multipliers-ct.pdf` (the
  publicly posted CT edition — same methodology; state editions share the
  Census 2000 PUMS approach); series page:
  https://cupr.rutgers.edu/products/new-jersey-demographic-multipliers/
- Household size by structure type × bedrooms × tenure, for units built in
  the preceding decade — the correct estimator for NEW 1–2BR multifamily,
  vs. the ACS all-stock tenure average (~3.1 locally) which is unit-mix
  blind. 5+-unit rentals run ~1.5 (1BR) to ~2.2 (2BR) across state
  editions; 1.8 is the studio/1BR/2BR blend. A Virginia-edition table would
  refine the center; the interval already spans the bedroom mix.

### `income_premium_new_construction` = 1.125 (1.0–1.25)
- **Harvard JCHS, The State of the Nation's Housing 2025.** **Local:**
  `harvard-jchs-state-of-nations-housing-2025.pdf`;
  https://www.jchs.harvard.edu/
- Median asking rent for apartments completed in late 2024 was **$1,900**
  — "affordable only to households earning $76,000 or more"; over
  two-thirds of new units asked ≥ $1,650 and 41% exceeded $2,050.
- **JCHS America's Rental Housing / Census:** median renter household
  income ≈ **$54,400/yr** (2024).
- Implied income sorting into brand-new stock: 76,000 / 54,400 ≈ **1.40**.
  The model's 1.125 center (1.0–1.25) is deliberately conservative against
  that national ratio — appropriate because the module already starts from
  the site's own tract mean income (ACS B19025/B11001), which capitalizes
  part of the neighborhood premium.

### Category spending — CES table + `ces_scale` = 1.0 (0.85–1.15)
- **BLS Consumer Expenditure Survey 2023** (released Sep 2024),
  https://www.bls.gov/cex/tables.htm — line items per category are recorded
  in `ces_shares.py` (`CATEGORY_SPEND`, e.g. Food at home $5,703; Food away
  $3,933; CES avg pre-tax income $101,805 per consumer unit).
- `ces_scale`'s ±15% covers regional and vintage drift: BLS publishes
  region/metro CE tables showing metro-area deviation from the national
  averages on this order; the single scale assumption is the honest
  alternative to pretending each line item is locally precise.
- **Engel elasticities** (`CATEGORY_ELASTICITY`: grocery 0.45 …
  entertainment 1.05) are read from the CE income-quintile gradients (same
  publication) — necessities scale sublinearly, discretionary ~linearly.
  These are inline-derived, not external estimates; the CE quintile tables
  are the traceable source.

---

## Destination + mode choice (the Huff run)

### Model form — Huff probabilistic trade areas
- **Huff, D. (1963), "A Probabilistic Analysis of Shopping Center Trade
  Areas," Land Economics 39(1): 81–90.** Link only (JSTOR):
  https://www.jstor.org/stable/3144521 — the founding formulation
  P_ij ∝ A_j^α · f(t_ij).
- The module's exponential impedance + joint destination-and-mode choice is
  the standard modern variant; α = 1.0 (attractiveness ∝ POI count) is the
  neutral default absent local calibration data.

### `beta_walk` = 0.10/min (0.05–0.15)
- **Iacono, Krizek & El-Geneidy (MnDOT 2008-11), Table 10** (walking trips,
  time impedance). **Local:**
  `iacono-krizek-elgeneidy-2008-mndot-distance-decay.pdf` (p. B-10):

  | Purpose    | beta/min | N   | adj. R² |
  |------------|----------|-----|---------|
  | Work       | 0.106    | 366 | 0.91    |
  | Shopping   | 0.094    | 269 | 0.70    |
  | School     | 0.106    | 105 | 0.55    |
  | Restaurant | 0.093    | 179 | 0.67    |
  | Recreation | 0.100    | 292 | 0.92    |

- **Yang & Diez-Roux (2012), "Walking Distance by Trip Purpose and
  Population Subgroups," Am J Prev Med 43(1): 11–19.** Open access:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC3377942/ — 2009 NHTS, **80,222
  walking trips**: duration decay **0.073/min (R² = 0.99)**, distance decay
  1.71/mile (R² = 0.98); median walk 0.5 mi / 10 min, mean 0.7 mi / 14.9
  min; recreation walks longest, meal trips shortest.
- Encoding: center 0.10 sits on the metro purpose-level cluster
  (0.093–0.106); the national-sample 0.073 sets the low-bound direction
  (0.05), and 0.15 covers hostile pedestrian environments.

### `BETA_DRIVE` = 0.15/min and the drive graph (module constant)
- **Iacono et al., Table 7** (drive-alone trips, distance impedance, per
  km; local PDF p. B-7): work 0.088 (N=1,300), **shopping 0.117
  (N=2,437, R² 0.96)**, school 0.122, restaurant 0.119 (N=745),
  recreational 0.103 (N=511).
- At in-city network speeds (~25–35 km/h), 0.117/km ≈ **0.05–0.07 per
  in-vehicle minute** — flatter than the module's 0.15/min. The gap is
  partly principled: OSMnx edge travel times exclude parking, access, and
  egress time, and a steeper per-minute decay proxies that fixed overhead.
  Flagged below as a recalibration candidate all the same.

### Walk mode-share preferences (zero-impedance splits)
`walk_share_neighborhood` = 0.60 (0.40–0.80), `walk_share_comparison` =
0.10 (0.0–0.30), `walk_share_grocery_entertainment` = 0.30 (0.10–0.50)

- **Semantics first:** these are the walk share at ZERO travel time (the
  Huff mode preference), not realized shares — after decay, realized walk
  shares are always lower. Observed survey shares therefore anchor the
  LOWER region of the plausible preference.
- **Clifton et al. (2013), Table 2** (local:
  `clifton-2013-consumer-behavior-travel-choices.pdf`) — realized walk mode
  shares by establishment type, Portland intercepts:

  | Establishment type | Walk share (all) | Walk share (CBD) |
  |---|---|---|
  | Convenience stores | 27% | 49% |
  | High-turnover restaurants | 22% | 42% |
  | Drinking places | 27% | 40% |
  | Overall | 25% | 43% |

  CBD realized shares of 40–49% at real distances are consistent with a
  zero-impedance preference above 0.5 for residents *on site* at a walkable
  mixed-use location → 0.60 center, 0.40 floor (≈ the realized CBD level),
  0.80 for the most walkable settings.
- **FHWA NHTS brief** (local: `fhwa-2020-nhts-nonmotorized-brief.pdf`):
  non-motorized trips are ~12% of ALL trips nationally — the comparison
  categories (goods-carrying, car-oriented) sit near that base rate, hence
  0.10 (0–0.30) for comparison goods and the 0.30 interpolation for
  grocery/entertainment (Clifton: drivers dominate supermarket trips;
  carry-capacity constraint).

---

## Trip generation (foot-traffic flows)

### `walk_trips_per_resident_day` = 1.0 (0.5–2.0)
- **FHWA (2020) NHTS Brief: Non-Motorized Travel** (local):
  42.5 billion walk/bike trips in 2017 ≈ **12% of all trips**, averaging 1
  mile / 16 minutes; on a typical day **17% of Americans** report at least
  one walk/bike trip. Against ~3.4 daily person-trips (NHTS Summary of
  Travel Trends), that implies ~**0.35–0.40 walk trips/person-day as the
  national average** — pulled up several-fold in walkable mixed-use
  settings, which is what the module analyzes.
- **Ewing & Cervero (2010), "Travel and the Built Environment: A
  Meta-Analysis," JAPA 76(3): 265–294.** Link only (paywalled):
  https://doi.org/10.1080/01944363.2010.486884 — walking responds to
  design/diversity/destination accessibility (elasticities ~0.2–0.4 per
  built-environment dimension, compounding across dimensions); the
  literature basis for walkable-context trip rates running well above the
  national mean. Center 1.0 (0.5–2.0) encodes that uplift with wide bounds.
- **Purpose mix context** (FHWA brief, Table 1): weekday non-motorized
  trips are 37% social/recreation, 16% family/personal business, 12%
  shopping, 12% school/church — the reason the foot-traffic metric's
  method string stresses that trips count ALL walking, not only shopping
  (the consistency diagnostic divides spending over the full trip base).

### Walk speed = 4.8 km/h (network constant)
- Yang & Diez-Roux's own means imply 0.7 mi / 14.9 min ≈ **4.5 km/h**;
  the Highway Capacity Manual's standard average walking speed is 1.2 m/s
  (4.3 km/h), with free-flow speeds to ~1.4 m/s (5.0 km/h). 4.8 km/h (3
  mph) is the conventional planning value inside that band.

---

## Jobs & space converters

### `sqft_per_office_job` = 300 (200–450) and `sqft_per_retail_job` = 500 (400–700)
- **EIA CBECS 2018, Table B1** (mean gross sqft per main-shift worker,
  buildings with workers). **Local:**
  `eia-cbecs-2018-table-b1-floorspace-workers.pdf`;
  https://www.eia.gov/consumption/commercial/ — transcribed 2026-07:

  | Building activity | sqft/worker | context |
  |---|---|---|
  | Office | **507** (SE 54) | 970k buildings, 32.8M workers |
  | Food service | **480** | restaurants/bars |
  | Enclosed & strip malls | **992** | inline + anchors |
  | Retail (other than mall) | **1,597** | freestanding/big-box skew |
  | All buildings | 1,072 | — |

- Retail: ground-floor mixed-use space is mostly food service (480) plus
  small-format shops — the 400–700 interval brackets the food-service
  figure and the lower reaches of mall space; big-box densities (1,600) are
  not the modeled product.
- Office: leased-space benchmarks run 150–250 usable sqft/worker, CBECS's
  gross measure runs 507 — the current 300 (200–450) splits the
  difference. See recalibration flag below.

### `own_retail_sqft_per_equiv_poi` = 2,000 (1,500–3,000)
- Industry norms for in-line/small-shop retail spaces run roughly
  1,000–2,500 sqft (e.g. VTS, "7 Standard Retail Spaces":
  https://www.vts.com/blog/7-standard-retail-spaces-in-a-transforming-industry);
  CBECS food-service buildings average ~4,800 sqft but street-front suites
  divide smaller. This is a coarse attractiveness converter (sqft →
  POI-count equivalents) and the weakest-anchored assumption in the module
  — its wide interval and small role (own-retail attractiveness only)
  reflect that.

---

## Site income (method, not an assumption)
- **Census ACS 5-yr, tables B19025 (aggregate household income) and B11001
  (households)** — the site tract's MEAN household income, computed as
  aggregate/households; the mean, not median × count, is the right
  estimator for total purchasing power under right-skewed income. Fallback
  ladder (tract median → citywide) is implemented in
  `economic._site_income` with the vintage recorded from the context
  manifest.

---

## Recalibration candidates (evidence vs. current encoding)

1. **`sqft_per_office_job` high bound.** CBECS 2018 gross office density
   (507 sqft/worker) exceeds the current high (450). Since the assumption
   converts EXISTING (often older, part-vacant) commercial space into
   displaced jobs, the gross measure argues for widening to ~250–500 with
   a center near 350. Effect: fewer estimated displaced jobs per sqft.
2. **`BETA_DRIVE` = 0.15/min.** Iacono's drive-alone shopping decay
   (0.117/km ≈ 0.05–0.07/min on in-vehicle time) is flatter. If the
   parking/access overhead argument is to carry the difference, consider
   documenting it in the constant's comment — or add fixed minutes to
   drive times and flatten beta. Effect of flattening: drive competes
   better at distance → walk capture concentrates slightly less.
3. **Walk-share centers are preferences, not observations.** Documented
   above; not a defect, but any reader comparing 0.60 to Clifton's 25–43%
   realized shares needs the zero-impedance framing — now written down
   here and worth echoing in the assumption's rationale string.
