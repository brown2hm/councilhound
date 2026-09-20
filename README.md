# CouncilHound 🐕

[![CI](https://github.com/brown2hm/councilhound/actions/workflows/ci.yml/badge.svg)](https://github.com/brown2hm/councilhound/actions/workflows/ci.yml)
[![Granicus canary](https://github.com/brown2hm/councilhound/actions/workflows/granicus-canary.yml/badge.svg)](https://github.com/brown2hm/councilhound/actions/workflows/granicus-canary.yml)

*The good dog that reads your city council's paperwork so you don't have to.*

**Live at [councilhound.net](https://councilhound.net)**, tracking the City of
Fairfax, VA.

Turns any [Granicus](https://granicus.com)-hosted public meeting archive —
the platform behind hundreds of US city/county "view meetings online" pages —
into a structured, searchable knowledge base. The pipeline is
Granicus-generic: point it at a different city's Granicus subdomain and view
IDs, and map that city's archive section names (see
[Adapting to your city](#adapting-to-your-city)). `PLAN.md` is the phased
build plan written against the reference city;
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the system diagrams, data
model, and ops notes.

## What it does

- **Briefing** — the latest decisions and votes across City Council and
  Planning Commission, filtered of procedural noise. The School Board, Parks
  and Recreation Advisory Board, and Housing and Healthy Communities Advisory
  Board are tracked too (meetings, search, follows); the two advisory boards
  publish no recordings, so they have documents but no transcripts.
- **Topic tracker** — every project, ordinance, and development gets a
  profile: LLM-synthesized summary, current status, recent updates, open
  questions, and per-member commentary, rebuilt as new meetings land.
- **Hot topics** — topics ranked by how much meeting time each body actually
  spent discussing them over the last 60 days (measured from transcript
  timestamps, not mention counts).
- **Watch the moment** — agenda items, votes, and timeline entries deep-link
  to the exact timestamp in the city's own Granicus video player. Videos are
  never hosted or embedded here.
- **Ask the hound** — natural-language Q&A over transcripts and agenda items
  (pgvector retrieval + Claude), with citations that link back to the source
  video or document. Rate-limited per IP and capped by a global daily budget.
- **Impact analysis** — per-project economic (Huff retail capture +
  foot-traffic index) and fiscal (revenue/cost ranges, comps-based projected
  value, school-split service costs) screening estimates over open data, with
  every number carrying provenance and named assumptions with sensitivity
  bounds — and an interactive assumptions panel on each project page that
  recomputes the estimates live as you adjust them. See
  [Impact analysis](#impact-analysis-local-run-stage) below.
- **Projects & topics directory** — one faceted directory (`/topics`) of
  official city project records and every topic surfaced from meetings:
  filter by type, official vs. meeting-derived, status, body, recency, and
  "recurring only"; sort; flip to a map of the filtered set; cards carry the
  city's project images. Meeting pages link each agenda item to the topics
  it touches and to the staff reports behind it.
- **What changed** — a "Changed this week" panel on the briefing and an
  Atom feed (`/entities/changes.atom`) of status transitions and
  first appearances.
- **Near me** — `/nearby` lists projects and named places within ½, 1, or 2
  miles of an address (Census-geocoded) or your browser location, nearest
  first; the map filters by kind and status and takes `?focus=slug`.
- **Site-wide search** — typeahead over tracked topics and members in the
  nav, with the full-text search of transcripts and agenda items behind it
  (filterable by body); `/glossary` explains the agenda vocabulary and terms
  carry hover definitions across the site.
- **Project wikis** — a per-project knowledge base in the
  [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format):
  durable markdown pages (overview, meeting history, positions, impact)
  maintained by incremental curator edits instead of regeneration, with
  impact figures resolved live via metric markers so prose never carries
  stale numbers. See [Project wikis](#project-wikis-okf-knowledge-bundle).
- **Follow by email** — a topic, a member's votes, a body's meetings, an
  area of the city, or the weekly briefing (tokened confirmation, one digest
  per subscriber from the nightly job, one-click unsubscribe), plus an
  iCalendar feed of upcoming meetings (`/meetings/upcoming.ics`).
- **Pre-meeting briefs** — every upcoming meeting gets an annotated
  agenda: the tracked topics it names, each with current status, what
  happened last time, and links to full history and impact analysis.

## How it works

Meetings flow through a pipeline of idempotent stages, all runnable
individually via the CLI or together via `councilhound.cli daily` (which the
nightly job runs):

1. **Scrape** — parse the Granicus archive for meetings, agendas, minutes,
   and MP3 audio (`scraper/granicus.py`, `pipeline.py`).
2. **Extract & transcribe** — pull text from PDFs; transcribe audio with
   Whisper (`mlx-whisper` on Apple Silicon GPU, `faster-whisper` on CPU).
   Granicus caption files exist but are empty, so transcription is mandatory.
3. **Structure** — a Claude tool-use pass turns each meeting into agenda
   items, votes, statuses, and entity mentions. Entity resolution
   (slug → alias → create) is owned by code, never the LLM.
4. **Link video** — official Granicus index points give per-agenda-item
   timestamps for the deep links.
5. **Profile & embed** — synthesize topic profiles; embed chunks and items
   with `bge-base-en-v1.5` (local sentence-transformers, 768-dim, HNSW
   cosine indexes) for retrieval.

## Repo layout

- `ingestion/` — scraper, transcription, LLM structuring, profiles,
  embeddings. Python 3.12, SQLAlchemy 2 + pgvector, Alembic.
- `api/` — FastAPI: meetings, topics, hot-topic rankings, and the
  rate-limited `/ask` RAG endpoint.
- `frontend/` — Next.js 14 App Router + Tailwind. Design system in
  `frontend/DESIGN.md`; brand assets in `frontend/public/brand/`.
- Each service carries its own `Dockerfile` and `fly.toml`.

## Configuration

Everything city-specific is environment config (`.env`, see `.env.example`):

| Variable | Meaning |
|---|---|
| `GRANICUS_BASE_URL` | Your city's Granicus subdomain, e.g. `https://<city>.granicus.com` |
| `GRANICUS_VIEW_IDS` | Comma-separated archive view IDs (find them in the `?view_id=` param of the city's "view meetings" page) |
| `DATABASE_URL` | Postgres connection string; leave unset for the embedded local dev DB |
| `ANTHROPIC_API_KEY` | For the structuring pass, topic profiles, and Q&A |

API-only knobs: `ALLOWED_ORIGINS` (CORS), `ASK_RATE_PER_MINUTE` /
`ASK_RATE_GLOBAL_PER_DAY` (defaults 6 and 500). Ingestion-only:
`TRANSCRIBE_BACKEND` (`mlx` / `faster-whisper`) and `WHISPER_MODEL`.

## Local dev (no Docker needed for ingestion)

Ingestion runs against an embedded Postgres 16 + pgvector (the `pgserver`
package) when `DATABASE_URL` is unset — data lives in `data/pgdev/`.

```
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python -r ingestion/requirements-dev.txt
cd ingestion
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli init-db
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli ingest --since 2024-07-01 --skip-media
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli status
```

Drop `--skip-media` to also download meeting MP3s (needed for transcription;
a full council meeting is ~80–150 MB, a 24-month backfill is roughly
10–20 GB). The remaining stages, in pipeline order: `extract-text`,
`transcribe`, `structure`, `index-points`, `seed-entities`, `profile`,
`embed` — or run `daily` to do all of it for recent meetings.

Schema changes: edit `ingestion/src/councilhound/db/models.py`, then
`cd ingestion && alembic revision --autogenerate -m "..."` and `init-db`.

### Impact analysis (local-run stage)

`councilhound.impact` evaluates development projects across economic and
fiscal lenses (methodology: deterministic models over open data; the LLM
only extracts document facts under a verbatim-quote firewall and writes the
narrative over computed JSON). It runs **locally only** — the geo stack
lives in `ingestion/requirements-impact.txt`, fairfaxva.gov IP-blocks
datacenter ranges, and results are persisted to Postgres where the deployed
API serves them read-only:

```
uv pip install -p .venv/bin/python -r ingestion/requirements-impact.txt
export CENSUS_API_KEY=...   # free: https://api.census.gov/data/key_signup.html
cd ingestion
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli impact-setup-jurisdiction  # pin tax rates (one-time, interactive)
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli impact-context             # build cached context layers
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli impact-extract <slug>      # LLM spec extraction
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli impact-confirm <slug>      # human gate: review the YAML
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli impact-evaluate <slug>     # modules + synthesized report
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli impact-push --all          # upsert synthesized results to prod
```

`impact-push` is how results ship: it upserts every synthesized evaluation
into the production Postgres (DSN via `--dsn` or `$IMPACT_PUSH_DATABASE_URL`,
e.g. through `fly proxy`), matching projects by slug and skipping any the
cloud ingest hasn't synced. Each project page then serves headline tiles, the
capture/walkability maps, a short summary with the full narrative collapsed,
and an interactive assumptions panel — every metric ships an exact power-law
decomposition over its assumptions, so sliders recompute the pipeline's own
arithmetic client-side (formulas and citations:
`docs/impact-methodology-report.tex`).

Jurisdiction-specific values (FIPS, CRS, layer URLs, tax and budget rates
with source + fiscal year — including the school-split cost inputs and the
personal-property/BPOL rate schedule) live in
`ingestion/jurisdictions/<slug>.yaml`; unpinned rates make the dependent
metrics refuse to run rather than guess.

### Project wikis (OKF knowledge bundle)

`councilhound.okf` maintains a wiki-style knowledge base — one directory of
markdown concept files per tracked project, per the
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
v0.2 spec (YAML frontmatter, reserved `index.md`/`log.md`; the root
`index.md` declares `okf_version`). Every concept page carries the v0.2
trust family: `generated: {by, at}` names the producer under the spec's
actor convention (`process:councilhound-okf` for the deterministic pipeline,
`councilhound-curator/<model>` for the LLM curator) and the ISO 8601 instant
of the last meaningful change — the meeting date a page is current through,
so re-running the pipeline on unchanged data stays a no-op. The v0.1
`timestamp` is written alongside for one release while readers move to
`generated.at`. Because v0.2 reserves `status` for lifecycle
(draft/stable/deprecated), the city's project status lives under
`project_status`. `okf-refresh` migrates pages written under v0.1 in place.
The bundle
(default `knowledge/councilhound-fairfax/`, override `$OKF_BUNDLE_DIR`) is
canonical for narrative knowledge and designed for incremental maintenance
instead of wholesale profile regeneration. It is **version-controlled** — it
deliberately does not live under the gitignored `data/`, because the
curator-owned pages hold human edits and every regeneration should land as a
reviewable diff. Ownership is per-file:
`history.md` and all indexes are **pipeline-owned** (regenerated
deterministically); `overview.md`/`positions.md`/`impact.md` are
**curator-owned** — seeded once, then edited minimally by the LLM curator as
new meetings land, so human edits survive (`<!-- curator:off -->` regions are
enforced untouchable). Ownership is finer-grained than the file where a
passage is *derived* rather than written: the "In this wiki" nav on
`overview.md` and the analysis-page links on `impact.md` sit in `curator:off`
regions that `okf-refresh` rebuilds, so a project the city renames or drops
does not leave a 404 in the prose. Impact figures never appear literally in
wiki prose:
pages carry `{{metric:...}}` markers the frontend resolves against the live
evaluation, so wiki text can't go stale.

```
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli okf-seed      # one-time draft per project
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli okf-refresh   # deterministic: history, indexes, status
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli okf-curate    # LLM: minimal edits for stale wikis
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli okf-lint      # OKF conformance + marker/link checks
PYTHONPATH=src ../.venv/bin/python -m councilhound.cli okf-push      # mirror into wiki_pages (--dsn for prod)
```

The API serves the mirror at `/development/{slug}/wiki` and
`/entities/{slug}/wiki`; each project's analysis page links to its wiki at
`/development/{slug}/wiki` (beta, read-only shadow of the profile summary).

### Docker (full stack)

```
cp .env.example .env   # fill in ANTHROPIC_API_KEY etc.
docker compose up --build
docker compose run ingestion python -m councilhound.cli init-db
```

- Postgres (with pgvector) on :5432
- API on :8000 (http://localhost:8000/health)
- Frontend on :3000

## Deployment (Fly.io)

The reference deployment runs four Fly apps:

| App | What | Notes |
|---|---|---|
| `councilhound-web` | Next.js frontend | `flyctl deploy` from `frontend/` |
| `councilhound-api` | FastAPI + embedding model | model baked into the image and warmed at startup; 4 GB VM |
| `councilhound-db` | Postgres + pgvector | self-run `pgvector/pgvector:pg16` machine with a volume — Fly's managed Postgres images don't ship pgvector |
| `councilhound-jobs` | nightly ingest | a `--schedule daily` machine that boots, runs `councilhound.cli daily`, and stops (see `ingestion/fly.toml` for setup) |

DNS is on Cloudflare in DNS-only (gray-cloud) mode so Fly can issue
Let's Encrypt certs. The API trusts `fly-client-ip` for rate limiting.

## Testing

`pytest` in `ingestion/` and `api/` (parser fixtures, entity resolution,
hot-topic windowing, structuring idempotency, rate limiting, endpoint
shapes). CI runs both suites against a real pgvector Postgres plus a
frontend type-check/build. A separate weekly canary parses the live Granicus
archive to catch markup drift that fixture-pinned tests can't.

## Adapting to your city

Granicus archive pages share the same skeleton everywhere (`ViewPublisher.php`
listing tables, `AgendaViewer.php`/`MinutesViewer.php`/`MetaViewer.php`
documents, `archive-video.granicus.com` MP3/MP4 links), but three things are
per-city:

1. **Base URL + view IDs** — set `GRANICUS_BASE_URL` and `GRANICUS_VIEW_IDS`
   in `.env`.
2. **Archive section names → bodies** — cities name their archive sections
   differently ("City Council Meetings", "Board of Supervisors", ...). Edit
   `SECTION_BODIES` and `classify()` in
   `ingestion/src/councilhound/scraper/granicus.py` to map your city's section
   headers and meeting-title patterns to the bodies you want to track.
3. **Seeded entities** — the LLM pass resolves people against a seeded
   roster; `seed-entities` parses it from agenda headers, so check its
   parsers match your city's agenda format (`councilhound/seed.py`).

Two Granicus behaviors worth knowing, verified against the reference city:
requests need a browser-ish User-Agent (bare curl gets 403s), and the
caption endpoint (`/videos/<clip>/captions.vtt`) may exist but be empty —
CouncilHound transcribes the MP3 audio rather than relying on captions.
