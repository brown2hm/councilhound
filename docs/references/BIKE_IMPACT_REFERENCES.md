# Bike lane & trail impact modules — reference library

Collected 2026-07-21 while designing the bike-lane and trail analogs of the
walk-based economic impact module
(`ingestion/src/councilhound/impact/modules/economic.py`). Each entry notes
which assumption slot it anchors. Local PDFs live in this directory; paywalled
sources are link-only.

---

## Decay functions (anchors `beta_bike`, trail catchment decay)

### Iacono, Krizek & El-Geneidy (2008) — *Access to Destinations: How Close is Close Enough? Estimating Accurate Distance Decay Functions for Multiple Modes and Different Purposes*
- MnDOT Report 2008-11. **Local:** `iacono-krizek-elgeneidy-2008-mndot-distance-decay.pdf`
- Source: https://mdl.mndot.gov/_flysystem/fedora/2023-01/200811.pdf
- Same study family the existing `beta_walk = 0.10/min` anchors on
  (their walk time-decay, Table 10: work 0.106, shopping 0.094, restaurant
  0.093, recreation 0.100 per minute).
- **Bicycle travel-time decay (Table 11, p. B-11), per minute:**

  | Purpose    | beta/min | N   | adj. R² |
  |------------|----------|-----|---------|
  | Shopping   | 0.107    | 64  | 0.67    |
  | School     | 0.100    | 36  | 0.56    |
  | Recreation | 0.071    | 131 | 0.55    |
  | Work       | 0.040    | 109 | 0.33    |

  Key result: per-minute decay for bike *shopping* trips (~0.107) is nearly
  identical to walking (~0.094); bikes simply cover 3–4x the distance per
  minute. Supports reusing the Huff architecture with a bike travel-time
  graph and `beta_bike` centered at 0.10/min. Caveats: small N, and the
  negative exponential fits bike time data worse than walk (overpredicts
  short trips, underpredicts 25–60 min).
- **Bicycle distance decay (Table 2, p. B-2), per km:** work 0.203 (N=56),
  shopping 0.514 (N=38), school 0.122 (N=177), recreation 0.375 TBI / 0.229
  NMPP. Walk shopping is 2.106/km — bike has ~1/4 the spatial friction,
  i.e. ~4x the reach.
- **Trail-access decay (Table 2 "Trail Trips" row): beta = 0.333/km,
  N = 1,967, R² = 0.93** — from a dedicated Hennepin County trail-user
  survey; the best-powered curve in the report. Measures distance from
  residence to trail entrance → defines a trail's user catchment around
  access points (~50% at 2 km, ~20% at 5 km).

---

## Consumer spending by mode (anchors per-category bike share / spend split)

### Clifton, Muhs, Currans et al. (2013) — *Consumer Behavior and Travel Choices: A Focus on Cyclists and Pedestrians* (Portland State / NITC)
- **Local:** `clifton-2013-consumer-behavior-travel-choices.pdf`
- Source: https://nacto.org/wp-content/uploads/consumer_behavior_and_travel_choices_clifton.pdf
- Project page: https://nitc.trec.pdx.edu/research/project/411/Examining_Consumer_Behavior_and_Travel_Choices
- ~1,900 customer-intercept surveys, Portland. Cyclists spend less **per
  trip** but visit more often; **per month** they match or exceed drivers at
  restaurants, bars, convenience stores; drivers out-spend at supermarkets.
  Maps onto the existing category split: high bike share for neighborhood
  categories, low for grocery/comparison. Per-establishment-type dollar
  ratios usable directly in assumption `basis` strings.

---

## Corridor natural experiments (validation targets, bike-lane mode-shift anchor)

### Volker & Handy (2021) — *Economic impacts on local businesses of investments in bicycle and pedestrian infrastructure: a review of the evidence*, Transport Reviews 41(4)
- Link only (paywalled): https://www.tandfonline.com/doi/full/10.1080/01441647.2021.1912849
- The literature review to cite first: 23 US/Canada studies. Bike/ped
  facilities → **positive or non-significant** effects on food/retail;
  negative mainly for auto-centric businesses (gas, auto repair); results
  hold when parking is removed.

### Arancibia, Farber, Savan, Verlinden, Smith Lea, Allen & Vernich (2019) — *Measuring the Local Economic Impacts of Replacing On-Street Parking With Bike Lanes: A Toronto (Canada) Case Study*, JAPA 85(4)
- **Local:** `arancibia-2019-japa-bloor-bike-lanes.pdf` (open mirror copy)
- DOI: https://doi.org/10.1080/01944363.2019.1638816
- TCAT summary, **local:** `tcat-2019-bloor-west-economic-impacts-summary.pdf`
  (https://www.tcat.ca/wp-content/uploads/2020/06/8e2c-Bloor-West-Economic-Impacts-Summary-FINAL-Nov2019.pdf)
- Bloor St: 136 parking spots → pilot bike lane; customer counts and
  reported spending rose, vacancies stable.

### Liu & Shi (2020) — *Understanding Economic and Business Impacts of Street Improvements for Bicycle and Pedestrian Mobility — A Multicity Multiapproach Exploration* (NITC-RR-1031/1161)
- **Local:** `liu-shi-2020-nitc-street-improvements-business-impacts.pdf`
- Source: https://ppms.trec.pdx.edu/media/project_files/NITC-RR-1031-1161_Understanding_Economic_and_Business_Impacts_of_Street_Improvements_for_Bicycle_and_Pedestrian_Mobility_FKG7DD1.pdf
- Summary: https://trec.pdx.edu/news/study-finds-bike-lanes-can-provide-positive-economic-impact-cities
- 14 corridors, 6 cities, sales-tax + employment data (strongest
  methodology). E.g. Minneapolis Central Ave food sales +52% vs +22%
  control; Seattle Broadway food-service employment +31% vs 2.5–16%
  controls.

---

## Trip generation (anchors `bike_trips_per_resident_day`, mode share)

### FHWA (2020) — *NHTS Brief: Non-Motorized Travel* (2017 NHTS)
- **Local:** `fhwa-2020-nhts-nonmotorized-brief.pdf`
- Source: https://nhts.ornl.gov/assets/FHWA_NHTS_Brief_Bike%20Ped%20Travel_041520.pdf
- Bikes ~1% of trips nationally (walking ~10%+); 85% of bike trips ≤ 3 mi.
  Bike trips/resident-day on the order of 0.02–0.05 (vs walk ~1.0 in the
  walk module) — the dominant lever; scale by city via ACS commute share
  (college towns run 5–10x).

---

## Trail user spending (anchors trail `spend_per_user_day`, user counts)

### NCDOT / ITRE (2018) — *Evaluating the Economic Impact of Shared Use Paths in North Carolina* (NCDOT 2015-44)
- **Local:** `ncdot-itre-2018-shared-use-paths-economic-impact.pdf` (54 MB — full final report with per-trail appendices)
- Source: https://itre.ncsu.edu/wp-content/uploads/2018/03/NCDOT-2015-44_SUP-Project_Final-Report_optimized.pdf
- Project page: https://itre.ncsu.edu/focus/bike-ped/sup-economic-impacts
- Press release: https://www.ncdot.gov/news/press-releases/Pages/2018/Greenways-Providing-Positive-Economic-Benefits-to-North-Carolina.aspx
- Best anchor for **ordinary urban greenways**; methodology closest to our
  model (counts + intercept surveys → per-user-day spending). Four trails
  (American Tobacco, Little Sugar Creek, Brevard, Duck): $19.4M/yr business
  sales, **$1.72/yr returned per $1 construction**, $684K/yr sales tax.
- **Transcribed 2026-07 (Table 26 + Ch. 5, direct expenditure per trip):**

  | Trail | Length | Annual trips | Direct expenditure | $/trip |
  |---|---|---|---|---|
  | American Tobacco Trail | 22 mi | 480,800 (3-yr ave) | $3,000,000 | $6.24 |
  | Little Sugar Creek | ~4 mi urban | 382,600 (2016) | $2,783,000 | $7.27 |
  | Brevard Greenway | 5 mi | 76,000 (3-yr ave) | $831,000 | $10.93 |
  | Duck Trail | 6 mi | 145,700 (2016) | $3,643,000 | $25.00 |

  Duck is a beach-tourism regime (Outer Banks) — excluded from the
  ordinary-greenway spend anchor. → `trail_spend_per_user_day` 7.5
  (6.0–11.0). Per-capita derivation using one-mile-band population densities
  (Table 13: ATT 840/mi², LSC 3,348/mi²; Brevard town pop ~7.7k): ATT ≈ 13,
  LSC ≈ 14, Brevard ≈ 10 user-days/capita-year → `trail_user_days_per_capita`
  12 (6–20), bounds widened for derivation roughness.
- **Bonus hedonic finding (Ch. 4):** the report's own regression on the ATT
  found **no statistically significant** sales-price premium within 1/2 mi
  (0.7–2.6% n.s. on the southern section) — direct support for the 0.0 floor
  on `trail_property_premium`.

### Destination-trail regime (apply only if a trail plausibly draws tourists)
- **Great Allegheny Passage** (Fourth Economy / GAP Conservancy 2021):
  $121M/yr along 150 mi; overnight users spend ~7x day users.
  https://www.planetizen.com/news/2021/12/115447-measuring-economic-impact-great-allegheny-passage
- **Virginia Creeper Trail** (Bowker, Bergstrom & Gill): ~$1.6M/yr from
  non-local users, ~1 in 10 overnight; 27 FTE jobs.
  https://headwaterseconomics.org/trail/12-virginia-creeper-rail-trail/

### Headwaters Economics — Trails Benefits Library
- https://headwaterseconomics.org/trail/?benefit=business-impacts&region=&use=cycling
- Index of ~100 trail studies, filterable by type; use for `basis` strings
  and corridor-specific sanity checks.

---

## Property-value capitalization (anchors trail fiscal channel)

### Crompton & Nicholls (2019) — *The Impact of Greenways and Trails on Proximate Property Values: An Updated Review*, J. Park & Recreation Administration 37(3)
- **Local:** `crompton-nicholls-2019-greenways-property-values.pdf` (mirror copy)
- Journal: https://js.sagamorepub.com/index.php/jpra/article/view/9906
- 20 hedonic analyses: typical premium **3–5%** for homes near trails.
  Asymmetric spread: destination mega-trails much higher (Chicago 606:
  ~22% within 1/5 mi); less-popular trails (Indianapolis evidence) show no
  measurable premium. Defensible encoding: 0–5% interval, ~3% center,
  gated on trail quality. Premium × assessed value in proximity band →
  property-tax increment.

### Impacts of bicycle facilities on residential property values in 11 US cities (2025)
- Link only (paywalled): https://www.sciencedirect.com/science/article/pii/S0966692325000377
- Modern single citation spanning both on-street facilities and trails.
