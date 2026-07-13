# CouncilHound roadmap — digestibility, visuals, and topic quality

Ideas gathered July 2026 from a survey of civic-tech dashboards
(Councilmatic, Council Data Project, citymeetings.nyc, GovTrack, municipal
development trackers) plus an audit of our own entity data. Ordered easy →
ambitious within each theme; the "Tiers" section at the end is the
sequenced plan.

## What the field does that we don't (yet)

- **Councilmatic** (DataMade): legislation detail pages with a status
  badge, sponsor list, and full action-history timeline; council-member
  pages with committee memberships and sponsored/voted legislation;
  **email subscriptions to a bill, person, or committee** — their killer
  retention feature.
- **Council Data Project**: cross-meeting **transcript keyword search**;
  per-member voting-record views.
- **citymeetings.nyc**: meetings broken into typed **chapters**
  (question / testimony / remarks / procedure) with per-chapter summaries
  and **permalinks to any chapter or sentence**; a weekly newsletter of
  highlights.
- **GovTrack**: the **bill-status stepper** (Introduced → Committee →
  Passed → Signed) that shows lifecycle position at a glance; "prognosis"
  scoring.
- **Municipal development trackers** (Colorado Springs, Nashville,
  Montgomery County, KC, SF Housing Dashboard): **map-first dashboards** —
  pins colored by project status/type, filter chips, click-through to a
  project card.

## Visual representations to add

1. **Status stepper on topic pages** — a GovTrack-style lifecycle bar
   (Proposed → Public hearing → Under review → Approved/Denied/Canceled)
   derived from `entity_updates.status_after` history. Instantly answers
   "where does this stand?" — today the status is a text badge.
2. **Vote pills** — per-vote member breakdown as a row of named
   green/red/gray chips (yes/no/abstain-absent) on meeting and topic
   pages. Data already in `votes.breakdown`.
3. **Discussion-time sparkline** — minutes-per-meeting bars on each topic
   page (and mini versions on Hot cards). The hot-topics query already
   computes exactly this; it's plotting existing data.
4. **Meeting chapter bar** — a horizontal segmented strip of a meeting
   proportional to each agenda item's duration (from Granicus index
   points), each segment deep-linking to the video timestamp. A visual
   "table of contents" per meeting.
5. **Briefing stat tiles** — decisions this month, items passed/denied,
   meetings held, hours processed. Cheap aggregate queries.
6. **Map view** (ambitious) — we already track 93 `location` entities with
   street addresses and many projects tied to them; geocode and pin them,
   colored by status, like the municipal development trackers. The single
   highest-impact visual for development projects.

## Topic/project page additions

1. **Status provenance** — "status set at [meeting] on [date] · ▶ watch
   the moment" under the status badge (we have the meeting id and video
   deep links).
2. **Vote history table** — every vote touching the entity with pills and
   watch links.
3. **Key people** — derived from existing per-member commentary + votes:
   who champions, who dissents, who moved/seconded.
4. **Related topics** — nearest neighbors via the embeddings we already
   have (plus shared-meeting co-mentions). Aids navigation *and* surfaces
   duplicate candidates.
5. **Documents** — the agenda/minutes/staff-report PDFs behind each
   timeline entry.
6. **"Next up" detection** — flag when the entity appears on a newly
   scraped upcoming agenda ("on the July 22 council agenda"). Needs the
   upcoming-meetings scrape (Granicus lists them on the same view pages).
7. **Public voice** (ambitious) — mine public-comment transcript spans:
   how many speakers, rough pro/con, one-line quotes with video links.
   citymeetings.nyc proves the value of separating public testimony from
   member discussion.
8. **Follow this topic** (ambitious) — per-topic email/RSS subscription;
   pairs with a weekly digest newsletter generated from the briefing.

## Topic deduplication — audit findings (July 2026)

State of the data (local snapshot, 129 meetings, Jul 2024–Jul 2026):

- 867 non-person entities; **726 (84%) have exactly one mention**; only
  15 have 5+. The tracker is ~140 real recurring threads on a long
  one-off tail.
- Confirmed duplicate clusters (slug-prefix + acronym scan):
  `courthouse-plaza` ×5 variants, `willard-sherwood-community-center` ×4,
  `accessory-dwelling-units` ×4, `city-of-fairfax-2035-comprehensive-plan`
  ×5 (some are legit sub-efforts), fragments like
  `george-snyder-trail-project` (1 mention) split from `george-snyder-trail`
  (22), and acronym twins: `...-prab`, `...-bar`, `...-ufmp`.
- **Counter-examples matter**: `old-town-parking-study` is a *child* of
  `old-town`, not a duplicate; same for `northfax-east-west-roadway` /
  `northfax`. Naive prefix-merging would be wrong — these want a
  *related-entities* link, not a merge.
- Current mechanism is exact slug match + alias table only
  (`entities.resolve_entity`). No fuzzy or semantic matching. **Verdict:
  not enough** — every phrasing drift mints a new entity.

### Dedup plan

1. **Easy — normalization + one-time merge.** At resolve time, strip
   generic trailing tokens (project, program, development, redevelopment,
   update, review) and detect acronym suffixes (trailing token equals the
   initials of the preceding tokens) before slugging; if the normalized
   slug hits an existing entity, alias instead of create. Ship with a
   one-time merge script (reassign mentions/updates/votes/aliases, keep
   the richer name, leave a redirect alias) for the audited clusters.
2. **Medium — retrieval-assisted resolution.** Before creating any new
   non-person entity, embed its name and cosine-search existing entity
   names (infra already exists): ≥0.92 auto-alias, 0.75–0.92 into a
   review file. Also feed the extraction LLM the nearest existing entity
   names as candidates so it reuses canonical spellings in the first
   place.
3. **Ambitious — periodic merge pass with audit trail.** Nightly job
   proposes merges (embedding + heuristics), an LLM judges pairs
   ("same real-world effort?"), merges land in an `entity_merges` table
   with slug redirects; borderline pairs queue for a lightweight admin
   review page. Distinct-but-related pairs become explicit
   `related_entities` edges instead.

## Tiers

**Tier 1 — days each, data already in hand**
- Status provenance line + timeline permalinks on topic pages
- Vote pills component (meeting + topic pages)
- Briefing stat tiles
- Dedup: normalization rules + one-time merge of audited clusters
- Related topics section (existing embeddings)

**Tier 2 — a week-ish each, small new plumbing**
- Status stepper lifecycle bar
- Discussion-time sparklines (topic pages + Hot cards)
- Meeting chapter bar with video seek links
- Embedding-assisted entity resolution in the pipeline + candidate list
  in the extraction prompt
- Upcoming-meetings scrape → "Next up" briefing card + per-topic flags
- Council-member pages: photo, roles, voting record, commentary rollup

**Tier 3 — ambitious, new capabilities**
- Transcript keyword search page (pgvector + trigram over chunks)
- Public-comment mining (speakers, stance, quotes with video links)
- Follow/subscribe per topic + weekly LLM-drafted email digest
- Map view of projects and locations (geocoding + status pins)
- Merge-review admin page + `entity_merges` audit trail

Sources: [Councilmatic](https://www.councilmatic.org/) ·
[NYC Councilmatic case study](https://datamade.us/our-work/councilmatic/nyc-council-councilmatic/) ·
[Council Data Project](https://councildataproject.org/) ·
[citymeetings.nyc](https://citymeetings.nyc/) and its
[design writeup](https://vikramoberoi.com/posts/how-citymeetings-nyc-uses-ai-to-make-it-easy-to-navigate-city-council-meetings/) ·
[GovTrack](https://www.govtrack.us/) ·
[Colorado Springs](https://coloradosprings.gov/developmenttracker) /
[Nashville](https://maps.nashville.gov/DevelopmentTracker) /
[Montgomery County](https://montgomeryplanning.org/planning/housing/development-tracker/)
development trackers ·
[SF Housing Dashboard](https://sfplanning.org/san-francisco-housing-dashboard)
