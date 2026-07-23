# Changelog

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
