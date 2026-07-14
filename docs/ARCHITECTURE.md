# CouncilHound architecture

How the system turns a Granicus meeting archive into a tracked, searchable,
askable knowledge base. Written July 2026 against the deployed system;
diagrams are Mermaid (GitHub renders them inline).

Companion docs: [PLAN.md](../PLAN.md) (original phased build plan),
[ROADMAP.md](../ROADMAP.md) (feature backlog), [README.md](../README.md)
(setup + adapting to another city).

## System overview

```mermaid
flowchart LR
    subgraph Granicus["Granicus (city-hosted)"]
        VP["ViewPublisher.php<br/>archive + upcoming events"]
        MP["MediaPlayer.php / player/clip<br/>video + index points"]
        AV["archive-video.granicus.com<br/>MP3/MP4"]
        DOCS["Agenda/Minutes/MetaViewer<br/>PDF + HTML documents"]
    end

    subgraph Jobs["councilhound-jobs (nightly Fly machine)"]
        PIPE["ingestion pipeline<br/>councilhound.cli daily"]
    end

    subgraph DB["councilhound-db (Fly, pgvector/pgvector:pg16)"]
        PG[("Postgres 16<br/>+ pgvector")]
    end

    subgraph API["councilhound-api (FastAPI, 4GB)"]
        REST["REST routers<br/>meetings · entities · members · search · ask"]
        EMB["bge-base-en-v1.5<br/>(baked into image, warmed at startup)"]
    end

    subgraph Web["councilhound-web (Next.js 14)"]
        FE["Server components +<br/>client Ask/Search pages"]
    end

    CLAUDE["Claude API<br/>(structuring · profiles · /ask answers)"]

    VP -->|scrape| PIPE
    MP -->|index points| PIPE
    AV -->|MP3 download| PIPE
    DOCS -->|PDF text| PIPE
    PIPE <-->|SQLAlchemy| PG
    PIPE <-->|tool-use extraction| CLAUDE
    REST <--> PG
    REST <-->|/ask answers| CLAUDE
    FE -->|server-side fetch| REST
    Browser((Public browser)) --> FE
    Browser -->|/ask, /search fetch| REST
    Browser -.->|watch links, never proxied| MP
```

Two hard rules shape everything:

1. **Video is never hosted or embedded.** Every "watch" affordance is a deep
   link into the city's own player, seeked with `starttime` (legacy player)
   + `entrytime` (modern player) — see `api/app/links.py`.
2. **The LLM never owns identity.** Extraction emits *names*; code resolves
   names to entities (`entities.resolve_entity`) and code merges duplicates
   (`dedupe.py`). An LLM output can never create or collapse identity on
   its own.

## Ingestion pipeline (nightly `cli daily`)

```mermaid
sequenceDiagram
    autonumber
    participant G as Granicus
    participant P as pipeline
    participant DB as Postgres
    participant W as Whisper (faster-whisper CPU)
    participant C as Claude

    P->>G: ViewPublisher archive scrape (view_id 13)
    P->>DB: upsert Meetings + Documents (idempotent)
    P->>G: sync upcoming events + agenda text
    P->>G: download meeting MP3s
    P->>P: extract PDF text (sanitize NULs, OCR bucket)
    P->>W: transcribe new audio → TranscriptChunks (~700 chars, timestamped)
    P->>C: structure meeting (tool-use JSON: items, votes, entities, statuses)
    Note over P,C: prompt includes already-tracked entity names<br/>so recurring threads keep one canonical name
    P->>DB: apply extraction (delete+recreate per meeting = idempotent)
    P->>G: fetch player index points → AgendaItem.start_seconds
    P->>DB: seed people from agenda headers (rosters, title aliases)
    P->>C: refresh stale EntityProfiles (summary, open questions, per-member commentary)
    P->>DB: embed new chunks + items (bge-base-en-v1.5, 768d, HNSW)
```

Every stage is idempotent and independently runnable via the CLI
(`discover`, `ingest`, `extract-text`, `transcribe`, `structure`,
`index-points`, `seed-entities`, `profile`, `embed`, `upcoming`,
`dedupe-entities`, `merge-entity`, `status`). `daily` chains them; the
scheduled machine boots once a day, runs it, and stops.

Transcription backends: `mlx-whisper` on Apple-Silicon dev machines
(~35x realtime on GPU), `faster-whisper` (distil-large-v3) on the CPU cloud
machine. Granicus caption files exist but are empty, so transcription is
mandatory, and canceled-meeting clips are skipped (title-card music makes
Whisper hallucinate).

## Data model

```mermaid
erDiagram
    MEETINGS ||--o{ DOCUMENTS : has
    MEETINGS ||--o{ AGENDA_ITEMS : has
    MEETINGS ||--o{ TRANSCRIPT_CHUNKS : has
    MEETINGS ||--o{ VOTES : has
    MEETINGS ||--o{ EXTRACTIONS : "raw LLM output per prompt_version"
    AGENDA_ITEMS ||--o{ VOTES : "voted on"
    ENTITIES ||--o{ ENTITY_ALIASES : "alternate names + old slugs"
    ENTITIES ||--o{ ENTITY_UPDATES : "one per (entity, meeting)"
    ENTITIES ||--o{ ENTITY_MENTIONS : "where it came up"
    ENTITIES ||--o| ENTITY_PROFILES : "LLM rollup cache"
    MEETINGS ||--o{ ENTITY_UPDATES : at
    MEETINGS ||--o{ ENTITY_MENTIONS : at
    AGENDA_ITEMS ||--o{ ENTITY_UPDATES : "via agenda item"
    TRANSCRIPT_CHUNKS }o--o| ENTITIES : "speaker_entity_id (future diarization)"

    MEETINGS {
        string granicus_clip_id UK "with view_id"
        string body "city_council | planning_commission"
        date meeting_date
        int duration_seconds
        string status "discovered → fetched → extracted"
    }
    AGENDA_ITEMS {
        string label UK "per meeting, e.g. 7a"
        text outcome
        numeric start_seconds "official Granicus index point"
        vector embedding "768d bge"
    }
    TRANSCRIPT_CHUNKS {
        numeric start_seconds
        numeric end_seconds
        text text "~700 chars"
        vector embedding "768d bge, HNSW cosine"
    }
    ENTITIES {
        string entity_type "project|topic|ordinance|resolution|location|case_number|person"
        string canonical_slug UK "normalized (dedupe.py)"
        string current_status "rolled up from latest update"
    }
    VOTES {
        string motion_result "passed|failed|deferred"
        json vote_breakdown "member last name → yes|no|abstain|absent"
    }
    UPCOMING_MEETINGS {
        string granicus_event_id UK
        datetime starts_at "NULL while live"
        text agenda_text "for on-the-agenda matching"
    }
```

Not shown: `upcoming_meetings` is standalone (fully refreshed each sync —
past events graduate into real `meetings` via the archive), and
`ingest_runs` records per-run bookkeeping.

### Entity identity & dedup

```mermaid
flowchart TD
    N["name from extraction/seed<br/>'Courthouse Plaza Redevelopment'"] --> S["slugify + create-time normalize<br/>strip 'project(s)' + acronym twins"]
    S --> A{"slug exists?"}
    A -- yes --> E[return entity]
    A -- no --> B{"alias match?<br/>(case-insensitive)"}
    B -- yes --> E
    B -- no --> C{"wider-suffix base exists?<br/>(-development, -review, -zoning, year …<br/>same entity_type only)"}
    C -- yes --> D["alias the drifted name<br/>to the base"] --> E
    C -- no --> F["create entity +<br/>self-aliases"]
```

Three reinforcing layers keep one real-world thread = one entity:
resolve-time normalization (above), the extraction prompt listing
already-tracked names to reuse, and `merge-entity`/`dedupe-entities` for
anything that slips through — merges move all history and leave the old
name *and slug* as aliases, so old URLs redirect (the API falls back to
alias lookup on slug miss).

## Query surfaces

| Surface | Path | How it works |
|---|---|---|
| Briefing | `/` | recent decisions derived from meeting details (procedural noise filtered); 30-day stat tiles; Next up (upcoming events); per-body hot panels |
| Hot topics | `/entities/hot` | named discussion time = Σ durations of transcript chunks whose text contains an entity name/alias, windowed by days + body; deterministic, no LLM |
| Topic page | `/entities/{slug}` | status stepper + provenance, profile (LLM cache), vote pills, discussion sparkline, related-by-co-mention, upcoming-agenda flags, full timeline with watch links |
| Members | `/members` | roster = people with title aliases; current vs former parsed from each body's latest agenda header; votes matched by the breakdown's last-name keys |
| Ask | `/ask` | embed question (bge, query prefix) → pgvector cosine top-K over chunks+items → Claude answers from numbered sources only → markdown with [n] citations linking to sources |
| Search | `/search` | hybrid: trigram keyword match + pgvector semantic match over chunks and items, merged with source labels |

`/ask` is the only LLM-per-request endpoint and is defended by a per-IP
sliding window plus a global daily budget (in-memory — the API runs as a
single instance; see `api/app/ratelimit.py`).

## Deployment

```mermaid
flowchart TD
    subgraph Fly["Fly.io (iad)"]
        WEB["councilhound-web<br/>Next.js standalone"]
        APIA["councilhound-api<br/>FastAPI · shared-cpu-2x/4GB<br/>embedding model in image"]
        DBM["councilhound-db<br/>pgvector/pgvector:pg16 + volume"]
        JOBS["councilhound-jobs<br/>--schedule daily machine<br/>python -m councilhound.cli daily"]
    end
    CF["Cloudflare DNS<br/>(gray-cloud/DNS-only for Fly certs)"]
    GH["GitHub<br/>CI: ingestion+api pytest vs pgvector service,<br/>frontend tsc+build, ruff<br/>weekly live-Granicus canary"]

    CF --> WEB & APIA
    WEB -->|API_URL internal| APIA
    APIA --> DBM
    JOBS --> DBM
    GH -.push/deploy from laptop.-> Fly
```

Operational notes (learned the hard way):

- **Fly managed Postgres lacks pgvector** — hence the self-run
  `pgvector/pgvector:pg16` machine with a volume.
- **The API must preload the embedding model** in the FastAPI lifespan;
  torch import + model load (~20s on shared CPU) otherwise stampedes with
  health checks on first `/ask` and looks hung. 4GB is the floor.
- **Jobs deploys never run `flyctl deploy`** against the app (it would
  clobber the scheduled machine's command back to the placeholder). Build
  with `flyctl deploy -c ingestion/fly.toml --build-only --push
  --image-label <tag> .` from `ingestion/`, then
  `flyctl machine update <id> --image … -y` (schedule + command survive).
  One-off admin (migrations, backfills, merges) runs the same image via
  `flyctl machine run … --rm -- python -m councilhound.cli <cmd>` — secrets
  ride along, credentials never leave Fly.
- **Watch deploy exit codes** — piping flyctl output through `tail` masks
  failures (a depot-builder auth 401 once looked like a successful deploy).
- **Migrations**: Alembic; `cli init-db` upgrades to head. Local dev uses
  an embedded pgserver Postgres when `DATABASE_URL` is unset (engine init
  is lock-guarded — concurrent first requests once raced pg_ctl).
- **Granicus quirks**: requests need a browser User-Agent (bare curl gets
  403); `MediaPlayer.php` redirects to `/player/clip/…` preserving the
  query string; only `entrytime` seeks the modern player; the weekly canary
  workflow catches markup drift under a green unit-test suite.
