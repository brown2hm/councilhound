# Changelog

## Unreleased — the nightly stops lying to itself (August 2026)

- **Late minutes/actions reports re-trigger extraction.** The nightly
  structures a fresh meeting from its agenda alone and honestly records "no
  votes"; nothing revisited it when the decision documents landed days later.
  The July 28 council meeting sat on the homepage with zero votes while its
  actions report (with the 4-2 zoning vote) was already in the database, and
  four older meetings had the same gap. `structure_pending` now re-extracts
  any meeting whose minutes/actions report text arrived after its stored
  extraction, exactly once per late arrival.
- **Granicus 403s fail fast on the datacenter-IP block.** A Fly-side probe
  confirmed CloudFront blocks BOTH archive-video and the archive-stream HLS
  host, so there is no unauthenticated cloud path to meeting media — and the
  download ladder was treating the hard block as throttling, sleeping 180s
  per meeting per night. The ladder is now success-aware: cold 403 fails in
  ~5s; post-success 403 keeps the full 30/60/90 back-off for residential
  backfills. Audio continues to be fetched and transcribed locally.
- Fly gotcha, hard-won: `flyctl machine update` leaves scheduled machines
  disarmed — each needs one manual `flyctl machine start` afterwards or the
  daily/hourly schedules silently stop firing.

## Unreleased — checking our own numbers (July 2026)

Comparing City Centre West against the applicant's fiscal impact analysis
(+$1.6–2.2M/yr) and the July 11, 2023 city staff report (+$543–741K/yr) put
our estimate at −$776K to +$338K — the wrong *sign*, not merely a different
magnitude. Five of the causes were defects rather than framing differences,
and all of them were systemic.

### Parcel resolution

- **PIN normalization.** `intake/parcels.py` collapsed whitespace only, so a
  document's `57-4-02-076` never matched the GIS layer's `57 4 02    076`.
  Resolution then fell through to the address rung, which resolves exactly
  one parcel by point-in-polygon. **20 of 26 specs had resolved a single
  parcel this way**; City Centre West's baseline used $2.0M of $7.0M in
  assessed value. New `impact/pins.py` gives every comparison one canonical
  form — the extractor's own quote firewall already normalized on alnum, and
  the two normalizers disagreeing was the whole bug.
- **Failures are visible.** `resolve_site` returns warnings that land in
  `extraction_notes`; an unmatched PIN used to be a log line nobody saw.
- **Superseded parents dropped.** Documents name pre-subdivision parcels
  alongside their children; summing both double-counts the site.
- **`impact-reresolve`** re-resolves existing specs without re-extracting
  (`impact-extract --force` would discard hand edits). Dry-run by default,
  with a no-regression guard: a candidate set that fits the document-stated
  acreage *worse* than the current geometry is reported for review, not
  proposed. Across the corpus: 5 clean fixes (City Centre West 53% → 1%
  acreage drift, Breezeway 99% → 27%, Northfax West 71% → 18%), 5 flagged.
- **Baseline honesty.** `_site_assessment` fills WebPro misses from the bulk
  parcel layer, cross-checks the two, and names any parcel it couldn't value.
  Partial success used to pass silently.

### Fiscal model

- **`office_sqft` entered no computation.** Projected assessed value counted
  only retail; City Centre West's 36,862 proffered square feet were worth
  $0. Office space now enters assessed value, BPOL at the professional-
  services class rate, business tangible property, and the jobs ledger.
- **Residential tenure.** New `proposed.tenure`, extracted under a new
  enum firewall (the value is our code word, so the quote must carry
  evidence for the class claimed). For-sale projects are valued against
  condominium comps instead of apartment buildings — a 5× understatement —
  and get their own household-size, occupancy, income-premium and school-
  yield defaults. Tenure changes a default's value, never its key.
- **`residential_value_per_unit` is a real assumption**, seeded from comps.
  The largest single input to the result was previously buried in comp
  arithmetic: not adjustable, not sensitivity-ranked, and unable to warn
  that it came from the wrong product class.
- **On-site commercial taxes**, displacement-adjusted by a new
  `net_new_share` (0.15–0.50). Meals and sales tax on the project's own
  restaurants and shops were missing entirely; counting them gross, as
  applicant analyses do, would overstate the city's gain, since sales
  captured from existing city businesses stop being taxed there. Resident
  spending already counted at the project's own ground floor is subtracted
  so it is neither double-counted nor discounted.
- **Revenue lines register themselves.** Membership in the net was a
  hard-coded tuple of metric names, so a new line could be computed,
  displayed, and silently omitted. A test now asserts every recurring-
  revenue metric reaches the net.
- Pinned `bpol_office_rate_per_100` ($0.40, financial and professional
  services) and `bpp_rate_per_100` ($4.13) from the FY2024 Rates & Levies
  schedule.

### Checking against others, and ourselves

- **External estimates.** Applicant FIA and staff-report figures are
  extracted under the same verbatim-quote firewall, published as attributed
  metrics, and compared: the report states both ranges and whether they
  overlap. They are never averaged into ours.
- **Cost-basis sanity gate.** New construction assesses at roughly 70–110%
  of hard cost; a projected value far outside that band is flagged. This
  alone would have caught the original defect ($30.6M against a stated
  $136.3M cost basis).
- **Council packets reach the extractor.** Staff reports — carrying the
  city's own fiscal estimate and the program council voted on — were absent
  from every spec corpus, though the meeting pipeline had already ingested
  and text-extracted them. Also widened the project scraper's document
  sections beyond "plan"/"document", which was skipping staff reports and
  hearing packets outright.
- **Method claims are checked.** A report once said office square footage
  "is accounted for in the tax value estimate" when nothing read that field,
  and it passed validation because the number itself was real. The
  synthesizer may now describe how a figure was computed only from that
  metric's method string and term labels; an advisory validator flags
  inclusion claims no method supports. The sensitivity ranking the executive
  summary asks for is now computed rather than guessed —
  `rank_assumptions_by_sensitivity` was imported and never called.
- **`assumption_overrides`** lets a reviewer replace any default at the
  confirm gate (e.g. applicant per-unit pricing comps can't see).
- **Tests.** `tests/impact/` goes 128 → 178. The fiscal module had **zero**
  tests while producing the headline numbers; it now has 17, plus the
  hyphenated-PIN regression, the enum firewall, the packet bridge, and a
  guard that every declared assumption has a frontend label.

### The parcel corpus, hand-verified

Working the whole corpus through the new tooling surfaced two more
normalizer gaps and settled every open site:

- **Suffix letters.** Documents write `58-3-02-013C`; this GIS layer stores
  `58 3 02    013 C`. `norm_pin` now splits every digit↔letter boundary, so
  both spellings canonicalize identically — this alone resolved Fairfax
  Square (1 parcel/4.14 ac → 3 parcels/10.06 ac, the Statement of Support's
  exact list) and Courthouse Plaza (004-D + 003-A = 10.57 ac vs 10.34
  stated; the old norm couldn't see `004D`).
- **Stacked condominium records.** `_dissolve` and the reresolve acreage
  check summed per-parcel areas, so 138 condo units sharing one 1.9-ac
  footprint read as ~280 acres. Both now use the union.
- **Built-out sites.** Breezeway, Northfax West, Paul VI, and Park Rd were
  approved assemblages since re-subdivided — the original parcels no longer
  exist in the layer, which is why no amount of PIN recovery could fix
  them. Their specs now carry the full post-development block (65, 60, 269,
  and 14 parcels; unions within 2% of stated acreage) plus a note that the
  "current" assessed value reflects the built project, so the
  tax-increase metric understates the true increment for them.
- **Judgment calls recorded in the YAML**: City Centre West (the staff
  report's three tax maps; neighbour 070 is the same size as 071, so
  acreage alone genuinely couldn't distinguish the sets), N29 WillowWood
  (the proffers put Phase I on post-split 002A1, 2.95 ac, not sibling
  002B1 where the geocode landed), Northfax-Chain-Bridge (pre-application,
  no plat — the five corner parcels its addresses geocode onto sum to 2.29
  vs 2.3 +/- stated).
- `impact-reresolve` now skips any spec whose current parcels already fit
  the stated acreage, so a hand-set answer is never re-flagged, and REVIEW
  ties print the differing pins rather than entire condo blocks.

**All 25 non-corridor specs now resolve within the acreage gate** (the
sweep reports "fits stated" for every one), against 20-of-26
single-parcel-by-geocode before.

Existing analyses need re-runs:
`impact-enrich <slug> --tenure --external-estimates` → `impact-confirm` →
`impact-evaluate --force` → `impact-push --all`. Headline metric names are
unchanged, so curator-owned `{{metric:…}}` markers keep resolving.

## Unreleased — reading the record (July 2026)

Three gaps a visitor hits that the roadmap never framed as user problems:
the app could fail in front of them, it never said how fresh it was, and it
held complete transcripts it wouldn't let anyone read.

### Reliability

- **Route-level boundaries.** There was no `error.tsx`, `loading.tsx`, or
  `not-found.tsx` anywhere in `frontend/app/`, and `lib/api.ts` throws on
  any non-OK response while the list pages don't catch — so a brief API
  blip served Next's stock error screen on `/topics`, `/meetings`,
  `/members`, `/map`, and `/development`. Adds a styled error card with
  retry, a 404 that routes people onward (topics get merged as the record
  grows), and skeletons on the five slowest routes.
- **Per-panel degradation on the briefing.** The hot-topic rankings, stat
  tiles, and per-meeting detail fetches now fall back individually, so one
  dead endpoint blanks its own panel instead of the page. Only the meetings
  list is load-bearing enough to reach the error boundary.
- **Pagination.** `/meetings` and `/topics` hard-capped at 100 rows with no
  paging, silently hiding everything older. Both now page (`offset` added
  to `GET /entities/`, which lacked it), fetching `PAGE_SIZE + 1` to detect
  a next page without a count query.

### Freshness

- **`GET /status`.** `ingest_runs` has always recorded phase, counts,
  bytes, and errors per run, and nothing had ever read it back — so
  "the council didn't meet this week" and "ingestion has been broken for a
  week" looked identical on a machine-generated site. Every page footer now
  carries the last-checked time, the meeting the record runs through, and
  transcript coverage, turning coral when the last run recorded errors or
  never wrote `finished_at`.

### Reading a meeting

- **`GET /meetings/{id}/transcript` and `/meetings/[id]/transcript`.** The
  complete timestamped transcript has been sitting in `transcript_chunks`
  backing `/search` and `/ask`, but only ever escaped as ~700-char
  fragments — there was no way to actually read a meeting. The page slices
  the segment stream at each agenda item's official Granicus index point,
  deep-links every segment to that moment on the city's player, and adds
  jump-to-item nav and find-in-transcript.
- **Search results land somewhere.** Transcript hits now carry a "Read in
  context" link that passes the query through, instead of dead-ending at
  the fragment.

### Access and reach

- Skip link, `aria-live` on the Ask page's loading/error region, focus moved
  to the map detail pane on selection, and timeline permalink anchors that
  are reachable by keyboard (they were `opacity-0` until hover).
- Mobile padding on all 16 page containers, the footer, and three
  fixed-width filter inputs — every container was a flat `px-8` with no
  mobile step, on a site whose audience is mostly on phones.
- `/civic` joins the nav; it existed with content and was reachable only
  from one link inside `/development`. Nine items no longer fit beside the
  wordmark at `lg`, so the inline bar starts at `xl` and the menu covers
  everything below it.

## Unreleased — bikes (July 2026)

Bike infrastructure joins the impact pipeline: two new modules for corridor
and trail agenda items, and cycling as a third mode inside the development
model. Every parameter is literature-anchored; the source library (annotated
index + local PDFs, including transcribed decay tables and per-trail
economics) lives in `docs/references/`.

### New impact modules

- **`bike_lane` module** (street_multimodal projects): mechanism +
  literature bounds. Decay-weighted bike catchment over a new OSM bike
  network graph (`beta_bike` 0.10/min, Iacono MnDOT 2008-11 Table 11) ×
  latent bike trips (FHWA NHTS) × an induced-visit share whose BOUNDS are
  calibrated to corridor natural experiments (Liu & Shi 2020; Arancibia
  2019; Volker & Handy 2021), priced with Clifton (2013) cyclist per-trip
  spending ($10.97 restaurant / $16.90 bar / $7.95 convenience). Ships with
  a consistency diagnostic that flags results outside the observed 0–50%
  corridor-uplift envelope.
- **`trail` module** (park/trail projects): two channels — trail-user
  spending (access-point catchment at the Iacono trail-access decay,
  0.333/km, N=1,967; NCDOT/ITRE four-trail user-days and $/user-day,
  destination-trail tourism excluded) and property capitalization (0–5%
  premium with a zero floor per the null-result literature, → RE tax
  increment at the pinned city rate).
- **Corridor intake**: LLM extraction of corridor street/cross-street names
  under a new string firewall (verbatim-in-documents or nulled), name-gap-
  tolerant snapping to the walk network (suffix expansion, junction
  tolerance, off-name path bridging for OSM tag gaps), and an
  `impact-confirm --geometry` manual override.
- **Bike as a third mode** in the development economic module: the joint
  Huff choice is now walk/bike/drive, with the bike preference carved from
  the drive remainder so published walk shares keep their meaning. New
  "spending arriving by bike" metric and per-business `bike_usd` in the map
  payloads. Existing analyses need a re-run + push (`impact-evaluate
  --force`, then `impact-push --all`).
- Module dispatch by project type (`registry.MODULES_BY_TYPE`); corridor
  and trail rows get corridor/trail map panels, assumption-lab groups, and
  methods-page entries in the frontend; the synthesis template assembles
  per-module sections dynamically.
- **Walk-module reference library**
  (`docs/references/WALK_ECONOMIC_IMPACT_REFERENCES.md`): every assumption
  in the development economic module now has a citable anchor — Census HVS
  vacancies, Rutgers CUPR multipliers, JCHS 2025 new-unit rents, Yang &
  Diez-Roux walk decay (0.073/min, N=80k), Clifton mode shares, FHWA NHTS
  trip rates, EIA CBECS 2018 employment densities — with transcribed
  values, local PDFs, and three flagged recalibration candidates
  (office sqft/job high bound vs CBECS 507; BETA_DRIVE steeper than
  Iacono's drive decay; walk-share zero-impedance framing).

## 0.2.0 — the interpretability round (July 2026)

A release focused on making the tracker trustworthy and legible for two
readers: a citizen following city projects, and a council member preparing
for a meeting.

### Topic quality

- **Entity dedup shipped.** Slug normalization now canonicalizes spelling
  drift (Blvd/Ave/Rd, thru/through, improvement/improvements, masterplan,
  Draft/Proposed prefixes); the nightly job re-slugs stranded entities and
  merges twins automatically; and `merge-entities-batch` applies the
  curated one-time merge of the 105 audited prod duplicate clusters
  (`ingestion/data/entity_merges_2026_07.json`) — Davies ×8, CIP ×11,
  Willard-Sherwood ×5, Blenheim ×4, and friends. Merges now carry official
  city-project links, geocodes, wiki pages, and follower subscriptions to
  the surviving entity, and old slugs keep resolving as aliases.
- **Minutes govern vote totals.** Profile synthesis (prompt v2) treats the
  minutes-derived dated record as authoritative for vote totals and
  outcomes; transcript excerpts supply color only. All profiles regenerate
  under the new rule on the next nightly run.

### Reach

- **Mobile works now.** Hamburger navigation below desktop widths; the
  header no longer forces a ~900 px minimum layout width that clipped and
  pan-scrolled every page on phones.
- **Every page has real metadata** — per-page titles, descriptions, and
  OpenGraph tags for search results and link-share cards.

### Following along

- **Follow a topic.** Email signup on every topic page: tokened
  confirmation, one digest per subscriber when followed topics get new
  updates (sent by the nightly job), one-click unsubscribe in every email.
- **Meeting calendar feed.** `/meetings/upcoming.ics` — subscribe from any
  calendar app; linked from the briefing and meetings pages.

### Interpretability

- **Plain-language fiscal summary** on impact pages: a deterministic,
  jargon-free paragraph reconciling the two net-fiscal framings as one
  cost/gain range, with one line on why they differ.
- **Negative currency renders as −$1.7M** (never `$-1.7M`), via one shared
  formatter.
- **Pre-meeting brief.** `/meetings/upcoming/<event>`: every tracked topic
  named on an upcoming agenda, with its status, the agenda line naming it,
  what happened last time, and links to full history and impact analysis.
  Linked from the briefing's Next-up card and from topic-page callouts.

### Release steps (prod)

1. Run the migration (adds `topic_subscriptions`):
   `alembic upgrade head` via the jobs machine.
2. Apply the curated merge batch once (dry-run first):
   `python -m councilhound.cli merge-entities-batch data/entity_merges_2026_07.json`
   then re-run with `--apply`. Safe to re-run; already-merged rows skip.
3. Set new secrets on the api and jobs apps for email:
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM`
   (unset = signups accepted but mail is logged and dropped), plus
   `SITE_BASE_URL` / `API_BASE_URL` if they differ from the defaults.
4. Deploy api and frontend as usual. The nightly `daily` job picks up the
   dedupe pass, profile regeneration (prompt v2), and the notifier on its
   next run.
