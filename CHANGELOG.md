# Changelog

## Unreleased — extractor guards: no votes without a record, no bodies as topics (September 2026)

Two things the two-year advisory-board backfill surfaced.

- **Votes need minutes or an actions report.** Given only an agenda and its
  packet, the model had filed the packet's sample motions and routine
  procedure as passed votes (the July 27, 2026 Planning Commission meeting
  carried four). `apply_extraction` now drops votes unless a minutes or
  actions-report document with text exists; the late-document re-run
  restores them when the record lands.
- **The city and its own bodies are never entities.** PRAB agendas'
  "Stakeholder Updates: Planning Commission – …; School Board – …" lines
  became topics, and "City of Fairfax" topped the School Board hot-topics
  ranking. `councilhound.bodies.is_self_reference` (registry labels plus
  the jurisdiction and its untracked boards) is applied at apply time, the
  prompt says so too, and a `purge-entity` command removes the rows made
  before the guard existed.
## Unreleased — one runner per stage (September 2026)

The jobs app runs a nightly `daily` machine, an hourly `catchup` machine and
the occasional one-off backfill machine against the same database. On
2026-09-16 the hourly catchup started while a backfill was mid-way through
structuring: both selected the same pending meetings (oldest first), both
called Claude, and the loser died on the `(meeting_id, prompt_version)`
unique constraint. The data was right; the LLM spend doubled and the logs
filled with tracebacks.

- **Advisory lock per stage.** `councilhound.db.session.stage_lock(stage)`
  takes a session-level Postgres advisory lock keyed by stage (`ingest`,
  `structure`, `transcribe`, `embed`, `profile`) on its own connection and
  yields whether it got it. Non-blocking: a runner never waits on another.
  Released on exit, and by Postgres itself when the connection drops, so a
  machine that exits or is killed never leaves a stale lock behind.
- **The CLI skips instead of duplicating.** `ingest`, `structure`,
  `transcribe`, `embed` and `profile` log `another runner holds <stage>;
  skipping` and exit 0 when the stage is taken. `daily` and `catchup` hold
  the lock per stage, so a catchup that arrives during a backfill still
  ingests, extracts text and embeds, and skips only the structuring pass.
  The cheap idempotent housekeeping passes (text extraction, index points,
  roster seeding, dedupe, geocoding, notifications) stay unguarded.

## Unreleased — three more bodies: School Board, Parks and Recreation Advisory Board, Housing and Healthy Communities Advisory Board (September 2026)

All three already publish to the same Granicus archive page the scraper
reads; they were sitting in `<h3>` sections the parser skipped by name.

- **One body registry.** `councilhound.bodies` lists every tracked body
  (key, label, archive section) and every layer that had hardcoded
  "city_council | planning_commission" reads from it: scraper scope,
  subscription validation, email labels, and the front end's chips, dots,
  filters, and follow buttons (`BODIES` in `lib/api.ts` mirrors it).
- **Scraper.** `School Board Meetings` (recorded; regular, work session,
  closed, retreat, special, joint), `Park and Recreation Advisory Board
  Meetings` and `Housing and Healthy Communities Advisory Board Meetings`
  (agenda + minutes only, no MP3) are in scope. Upcoming-events rows for
  these bodies now get a body instead of NULL, so they appear on the
  calendar feed and event pages with a follow button. Advisory-board agendas
  are uploaded PDFs, not Granicus HTML: the document fetcher already handled
  that by content type, and `fetch_agenda_text` (upcoming agenda matching)
  now does too.
- **School Board roster.** Agenda headers carry the chair and four members
  two-to-a-line; `parse_school_board_header` seeds them with body-qualified
  titles ("School Board Chair", "School Board Member") so `/members` shows a
  School Board section without confusing its chair with the Planning
  Commission's. The advisory boards' agendas have no roster block, so their
  members are not seeded.
- **Unanimous votes get a breakdown.** School Board minutes record
  outcomes as "passed unanimously" over an attendance list rather than a
  roll call, which left every board member with zero recorded votes. The
  extractor now derives the breakdown in exactly that case: every member
  recorded present is yes (no for a unanimous failure), members recorded
  absent are absent, and it still records nothing when neither a roll call
  nor attendance is written down. Council minutes with the same phrasing
  benefit on their next re-extraction.
- **Not yet:** the home page and `/topics` hot-topics panels still show
  only City Council and Planning Commission, and nothing has been
  backfilled — a historical ingest (School Board audio must be fetched from
  a residential IP) is a separate step.

## Unreleased — discovery and tracking: one directory, a change feed, near me, broader follows (September 2026)

An audit of the front end against two readers — a resident trying to find
out what's being decided near them, and a council member trying to keep up
with everything — found the pieces were all there but not connected: meeting
pages didn't link to topics, three list pages sliced one entity table three
ways, nothing answered "what changed this week", search skipped topic names,
and every page re-fetched the API on every view. This round wires them
together.

- **Meeting pages link to the topics they touch.** `GET /meetings/{id}` now
  carries `entities` per agenda item (tracked updates first, then bare
  mentions, people excluded) and `documents` per item, and the meeting page
  renders topic chips with the status each item set plus the staff-report
  PDFs the ingest had been fetching but never showing. Meeting-level
  documents (actions report, packets) get their own section.
- **One directory.** `/topics` is now "Projects & topics": official city
  records and meeting-derived topics in one list, faceted by type, official
  vs. from-meetings, status, body, recency, and "recurring only" (hides the
  one-mention tail the July audit measured at 84%), sortable, with a map
  view of the filtered set and the city's own project images on cards.
  `GET /entities/` grew `body`, `days`, `min_updates`, `official`, `sort`,
  alias search, and per-row card fields (`bodies`, `lat/lng`, `has_wiki`,
  `official{...}`). `/development` and `/civic` redirect into the facets;
  the nav drops from nine items to six plus a search box.
- **The naive per-capita fiscal method is retired.** It billed every new
  resident for a full share of fixed citywide costs and so always landed
  the net low for infill. The fiscal module no longer publishes "Annual
  service cost — naive per-capita method", "Net annual fiscal impact —
  naive per-capita method" or the range that spanned both methods; the
  marginal framing is the one net, with the marginal cost factor's range
  carrying the uncertainty. `GET /development/{slug}/evaluation` drops
  those rows from evaluations stored before the retirement, the wiki
  resolver drops a bullet that cites them, the wiki bundle's impact pages
  lose the line, and the methods list, formulas and plain-language summary
  follow. Stored report narratives that quoted the old figure are
  regenerated on the next enrichment run.
- **Ask the hound puts the answer beside its evidence.** The answer's
  first line becomes the page's statement; the rest follows at reading
  size with citation markers as small chips that jump to the source. The
  sources sit in a sticky rail beside the answer, in date order (marker,
  date, meeting and item, first line, one action), instead of ten cards
  below it. Markers the model cited but retrieval did not return stay
  unlinked, and the rail says how many. Under the answer, "About this
  topic" names the record the answer is about, with its status, a Follow
  button and a link to its full history, so an answer is no longer a dead
  end. `POST /ask/` grew `topics`: the tracked records on the cited
  agenda items (or, failing that, updated at the cited meetings), ranked
  by how many cited sources touch them.
- **Meeting pages lead with what was decided.** The agenda list of
  equal-weight cards becomes "What was decided": one row per vote with a
  check, the item label, the title, the outcome stated once (the
  "Outcome:" prefix and the duplicate vote line are gone), "Passed,
  unanimous" or the tally, the topics it touched, and a watch-from
  timestamp where the recording is chaptered; proclamations and other
  unvoted items follow as "Presented" (or "Discussed" for a work
  session). Everything about the recording moves to a sticky rail: Watch
  from the start with the chapters as timestamps, then the documents by
  kind with counts (7 staff reports, 7 motions, 4 draft minutes… instead
  of 22 rows all tagged "Staff report"), and every topic the meeting
  touched, once, with the status it set. The header keeps Watch, Agenda,
  Transcript and the chapter bar and adds a fact line: duration, items,
  votes and whether all were unanimous, tracked topics.
- **Topic pages read as briefs, and a place touched by several projects
  gets each on its own terms.** `GET /entities/{slug}` grew `threads`: the
  record's history grouped by the project entities on the same agenda
  items, each with that project's own status, city status and summary
  lead. When a record has threads the page shows the summary's first
  sentence as a lede, then one section per matter (status pill, lead,
  its history rows), then any unthreaded rows as "Other mentions", with
  the topic-level status, Follow, open questions, member remarks, the
  discussion chart and related topics in a sticky rail; the rest of the
  summary follows as "In full". Records with no threads get the same
  content as a one-column brief. Either way the proposal stepper is gone
  (a street is not a proposal), the summary is a lede plus paragraphs
  rather than a box, open questions are a plain list, member remarks are
  rows, the discussion chart carries years on its axis, and history rows
  mark actions with filled dots and mentions with open dots, so a vote
  on another matter no longer reads as a vote on this one.
- **The map's side panel is a list, not a prompt.** At rest it lists
  every pin, open decisions first, with its shape, status and address;
  a row click centers the map on the pin and opens the record, and the
  record's close button goes back to the list. The legend is a real
  legend (three shapes, seven colors) instead of the filter chips
  doubling as one, and the palette is rebalanced so in progress and
  proposed are the loud pins, approved is quiet, and "no status yet" has
  its own grey. Kind chips carry counts, status is a select rather than a
  wrapping chip row, colored pins draw above grey ones at the same spot,
  and "What's near an address?" is the header's input rather than a
  corner chip (it submits to the existing /nearby page).
- **Members shows how each member votes, not just how often.** The
  roster cards (name, role, "279 recorded votes") become one record table
  per body: votes cast, a yes/no/absent split bar, the share of yes and no
  votes cast with the outcome, the last no vote with its date and subject
  (linked to the meeting), and the last vote date. The mayor's row says
  the mayor votes only to break a tie, so 34 votes no longer reads as
  absence. Former members drop to a compact list. `GET /members/` grew
  `vote_stats`, `with_outcome_pct` and `last_no` per member.
- **Meetings shows what each meeting decided.** The list promised "with
  what was decided" and showed dates, item counts and minutes. Now it is
  a month ledger: a month rail, the day as the big number, and under each
  meeting its votes one per line (a check, the item label, the title with
  its procedural opener stripped), with "+N more votes" after the first
  three and consent agendas last. Work sessions list what they discussed;
  a meeting with no recording says so; cancelled meetings collapse to a
  grey one-liner. "Next up" leads the page so it no longer starts in the
  past, and the two Follow buttons shrink to a line of links. `GET
  /meetings/` grew `include_decisions=true`, which attaches each meeting's
  substantive votes, discussed items and pass/fail tally.
- **Projects & topics is a directory again.** The page had become a
  changelog of names: 239 of its 972 records are people, every row was a
  full-width strip with one meta line, and the filters ran three rows
  deep. Now the unfiltered view leads with the official city projects as
  a card grid (the only records with photos, addresses and a staff
  status), follows with one dense table of everything the meetings named
  (name, kind, status, body, updates, last seen), and demotes people to a
  single row with a "Show people" link. Filters collapse to one labelled
  row with a Kind select covering both the official facet and the entity
  types; "Recurring only" is on by default (`active=0` turns it off) and
  the default sort is most activity. `GET /entities/` grew
  `exclude_type` (the page hides people with it) and `GET /entities/counts`
  reports the directory's size by kind for the section headers.
- **The briefing leads with what changed.** The front page drops the
  stat tiles (meetings held, hours in session, votes taken, passed vs.
  failed: small numbers with no story, and the last one disagreed with the
  headline). The headline now reads "Five measures passed. Five topics
  changed status." and both halves count the same seven-day window the
  change feed uses, instead of "the last four meetings, capped at six";
  when nothing met in the window it falls back to the last meeting and
  says so. "Changed this week" moves above the decision cards, consent
  agendas drop to one-line rows at the end, and Ask the hound tightens to
  a single row so the headline shares the first screen with it. Also
  fixes a pre-existing phone-width overflow: the Next Up rows never
  wrapped, and on one-column layouts that widened the whole page.
- **A change feed.** `GET /entities/changes?days=` reports status
  transitions and first appearances, measured against the last status
  actually set (not the previous row); the briefing shows "Changed this
  week", and `GET /entities/changes.atom` is a feed-reader counterpart to
  the meeting calendar. Change detection lives in `councilhound.changes`
  so the weekly email and the API agree.
- **Search is global.** `GET /search/` leads with matching tracked topics
  (name or alias, body-filterable); `GET /entities/suggest` backs a
  site-wide typeahead in the nav covering topics and members; the search
  page gets body pills.
- **Near me.** `GET /entities/near?lat&lng&radius_m` lists projects and
  named places within a radius, nearest first, from city coordinates or our
  geocodes; `GET /entities/geocode?q=` proxies the Census geocoder
  (rate-limited per IP). `/nearby` takes an address or browser location
  with ½/1/2-mile radii, a compact map, and an area follow. The map page
  gained kind/status filters and `?focus=slug`; topic and project pages
  link to their pin and to "what else is nearby". Entity detail carries
  `location`.
- **Follows beyond topics.** `topic_subscriptions` gained `kind` (topic,
  member, body, area, briefing) with `body`, `lat/lng/radius_m`, `label`,
  `last_vote_id`, and `last_sent_at`; the migration drops the
  (email, entity_id) unique constraint, which can't express the per-kind
  key — the API dedups instead. The notifier composes one email per
  address from per-kind sections: a member's votes, a body's meetings
  (every update, capped at 40 lines with a link to the rest), updates
  inside an area, and a weekly briefing (decisions, status changes,
  upcoming meetings) that sends at most every seven days and skips quiet
  weeks. Follow buttons sit on member pages, the meetings list, pre-meeting
  briefs, `/nearby`, and the briefing header.
- **Glossary.** `/glossary` defines the agenda vocabulary (special use
  permit, proffer, first reading, work session…); agenda item titles and
  descriptions, topic summaries, and open questions get dotted-underline
  hover definitions via a server-rendered `Jargon` component.
- **The data layer is cached.** `lib/api.ts` wraps fetches in
  `unstable_cache` with a five-minute revalidate (search and geocode stay
  fresh), so the briefing's nine API calls happen nine times per five
  minutes instead of per view; pages stay dynamically rendered and errors
  are never cached. Topic and meeting pages carry an explicit
  `revalidate` so an on-demand render can't be kept forever.

## Unreleased — calibrating the fiscal model against the city's own estimates (August 2026)

The pipeline's net-fiscal estimates ran systematically below the city's:
across every project where a staff report states a fiscal estimate, ours was
the more pessimistic, and the naive per-capita framing never once landed in
the neighborhood of a published city figure. The city's estimates have
tracked outcomes well, while several of our screening defaults were
literature-range midpoints — so this round benchmarks ours against theirs
and recalibrates where the evidence supports it.

- **Two cost-side defaults recalibrated toward local evidence.** Every
  metric ships an exact power-law decomposition over its assumptions, which
  makes gap attribution solvable in closed form: for each assumption, the
  value that would move our estimate onto the staff figure, classified
  in-band or out. Two staff comparisons whose ranges already overlapped ours
  (WillowWood Jul 2024, Davies Jun 2025) implied `marginal_cost_factor`
  0.30–0.34 and `students_per_unit` 0.057–0.073 — clustered, in-band, same
  direction. The defaults move partway: `marginal_cost_factor` 0.40 → 0.35
  [0.25..0.55]; `students_per_unit` rental 0.10 → 0.08 [0.05..0.12],
  for-sale 0.12 → 0.10 [0.05..0.16]. Deliberately above the implied points,
  and chosen jointly — the pair centers both evidence projects in their
  staff ranges without overshooting anywhere. The recomputed pipeline
  matched the closed-form predictions to the dollar (Davies +92,981 vs
  +93k predicted), so the decomposition is load-bearing, not decorative.
- **The doctrine boundary is now written down.** External estimates stay a
  benchmark — never averaged in, per-project divergence reported, not
  reconciled away — but benchmarks may inform a *default* as a considered,
  cited revision. The methodology report documents the calibration and its
  evidence; each changed assumption's `basis` names the staff reports.
  Applicant FIAs are excluded from calibration on the gross-receipts
  convention (they count displaced sales as new).
- **Paul-VI is for-sale, established by negation.** The documents commit to
  "No rental units shall be developed or offered." — the strongest possible
  tenure evidence, and structurally unacceptable to the evidence-token
  firewall, which reads the word "rental" as rental-class evidence. The
  extraction was correctly rejected three times; the value is now set by
  hand at the confirm gate with the verbatim quote recorded, and the spec
  note preserves the case for a future negation-aware firewall. Marginal
  net moved −$2.17M → −$1.50M. The four other tenure-missing projects were
  checked token-by-token and genuinely lack documentary evidence (what
  looked like evidence was Comprehensive-Plan boilerplate and neighboring
  parcels — "Fairfax Square Apartments" is the property next door), so
  their conservative rental defaults stand.
- All 16 residential evaluations re-evaluated under the new defaults and
  pushed. The two evidence projects now sit centered in their staff ranges;
  the residual gaps elsewhere are value-side (per-unit assessed values,
  unknown tenure) or structural (affordable housing has no modeling of
  assessment restrictions yet) — known, documented, and deliberately not
  chased with cost-side knobs.

## Unreleased — the wiki becomes the front door (August 2026)

The development detail page was really an impact-analysis page: it keyed on
a synthesized evaluation and 404'd otherwise, so 19 of 41 official records
had no page at all — while 38 of them carry a project wiki, the richest
record we maintain. The section is now wiki-first.

- **`/development/[slug]` is sub-route tabs under one shared header:
  Wiki (default), Impact analysis, Documents.** The wiki tab renders every
  concept page inline with `{{metric:...}}` markers still resolving against
  the live evaluation; `/analysis` carries everything the old page had
  (headline metrics, maps, assumptions lab, full report) and exists only
  when synthesized; `/documents` lists the city's document record un-capped
  — City Centre West shows all 60 where the topics page chips six. Old
  `/development/[slug]/wiki` URLs redirect permanently.
- **Every official project resolves.** New `GET /development/{slug}` shell
  endpoint: the full city record (requests, planner, documents, official
  timeline) plus `has_wiki`/`evaluation_status`/`no_analysis_reason`, 404
  only on unknown slugs. Projects without a wiki fall back to the city's
  own record; the missing analysis keeps its legible reason as a muted
  chip in the tab bar.
- **`has_wiki` now means "servable wiki" everywhere.** The entities route
  counted reserved index/log rows, so an entity whose concept pages were
  gone could advertise a wiki that 404s. One shared helper (concept-kind
  only, matching `wiki_payload`'s own 404 condition) now feeds all three
  flags, with a regression test.
- **The directory treats the project page as canonical.** Names link to
  `/development/[slug]` instead of the topic page, each wiki'd row carries
  a "wiki · synced <date>" chip (one grouped `wiki_pages` query, no N+1),
  "impact analysis" buttons point at the analysis tab, and meeting-derived
  rows get their `/topics/[slug]/wiki` chip.
- Side effect worth keeping: the default project page no longer ships
  Leaflet/KaTeX — ~216 B of route JS, with the heavy chunks loading only
  on `/analysis`.

- **Late minutes/actions reports re-trigger extraction.** The nightly
  structures a fresh meeting from its agenda alone and honestly records "no
  votes"; nothing revisited it when the decision documents landed days later.
  The July 28 council meeting sat on the homepage with zero votes while its
  actions report (with the 4-2 zoning vote) was already in the database, and
  four older meetings had the same gap. `structure_pending` now re-extracts
  any meeting whose minutes/actions report text arrived after its stored
  extraction, exactly once per late arrival.
- **Upcoming meetings came back.** Granicus moved the event id off the row's
  links and into a `data-event-id` attribute on the eComment anchor;
  `parse_upcoming` required an `event_id=`-bearing href/onclick and so hit
  `continue` on every row. Because `sync_upcoming` is a full replacement per
  view, the nightly then deleted the rows it already had — the homepage "Next
  up" panel, `next_meeting`, the topic-page "on the upcoming agenda" callouts,
  and `upcoming.ics` all went quiet while the city had 35 events posted, 5 of
  them council or planning commission. The rows with nothing else to match on
  are meetings announced before their agenda is posted: the agenda cell is
  empty, so there is no AgendaViewer link to fall back to. Falls back to
  `data-event-id`, skipping the `data-rollover-id="0"` on the same anchor.
  The weekly canary never caught this because every assertion it makes is
  about the archive, which never drifted — it now checks the upcoming table
  parses with ids, dates, and at least one in-scope body.
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
- Fly gotcha, hard-won: the depot builder pushes manifests the machine API
  cannot resolve. `flyctl deploy --build-only --push` reported success and a
  digest on two consecutive builds; both times `machine update` 404'd with
  `MANIFEST_UNKNOWN`, naming a repo (`jlyv9r73737vq8xr`) that is not
  `councilhound-jobs`. `--depot=false` pushes straight to `registry.fly.io`
  and worked first try, with a different digest. Build the jobs image with
  `--depot=false` until this is understood — same family as the depot-builder
  401 that once looked like a successful deploy.
- Fly gotcha, hard-won: `flyctl machine update` on the jobs machines **always**
  ends in `machine failed to reach desired start state, and restart policy was
  set to no restart`. That is flyctl waiting for a "started" state on a
  one-shot machine whose command runs and exits; the update itself succeeded.
  Confirm with `machine status --display-config` — image, `schedule`, and
  `cmd` all survive — rather than reading the error as a failed deploy. The
  cost of misreading it is a second update on top of a good one.
- The "watch deploy exit codes" rule in `docs/ARCHITECTURE.md` needs
  `set -o pipefail` to actually hold: `flyctl … | tail` reports the exit code
  of `tail`, so a failed deploy reads as 0. The first depot build above
  printed `error releasing builder: deadline_exceeded` beside a valid-looking
  `image:` line and still came back "successful" through a bare pipe.

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
