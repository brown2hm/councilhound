# Fairfax City Council Knowledge Base — Build Plan

**Goal:** Ingest City of Fairfax, VA council meeting videos/transcripts + agenda/minutes documents into a structured, linked knowledge base, then serve a front end where users can browse meeting history, track project/topic progress over time, and ask natural-language questions with citations back to source (meeting + timestamp/document).

**Audience for this doc:** a coding agent (Claude Code / Codex) running headless, locally first, deployed to cloud later. Each phase has concrete tasks and a definition of done so the agent can self-check progress.

---

## 0. Source facts (verified live against fairfax.granicus.com on 2026-07-11)

- City of Fairfax council meetings are hosted on Granicus: `https://fairfax.granicus.com`
- Two known view IDs: `view_id=11` (older archive) and `view_id=13` (current).
- **`view_id=13` mixes many bodies** — City Council, Planning Commission, School Board, BZA, committees (~500 "Regular Meeting", ~170 School Board, ~161 Work Session, ~131 Planning Commission entries; clip_ids run past 4600). `meeting_type` must be parsed from the meeting title; there is no per-body view.
- URL patterns (corrected):
  - Meeting list/archive (past meetings, keyed by `clip_id`): `ViewPublisher.php?view_id=<id>`
  - RSS (upcoming events only, keyed by `event_id`, NOT clip_id): `ViewPublisherRSS.php?view_id=<id>&mode=agendas` and `&mode=minutes`. (`ViewPublisher.php?...&mode=rss` returns plain HTML — do not use.)
  - Video player: `player/clip/<clip_id>`
  - Agenda: `AgendaViewer.php?view_id=<id>&clip_id=<clip_id>` (past) or `&event_id=<event_id>` (upcoming). `GeneratedAgendaViewer.php` exists but can return "This agenda is not currently published."
  - Minutes: `MinutesViewer.php?view_id=<id>&clip_id=<clip_id>&doc_id=<uuid>` — note the `doc_id` UUID, scraped from the archive page rows.
  - Agenda-item document (PDF): `MetaViewer.php?view_id=<id>&clip_id=<clip_id>&meta_id=<meta_id>`
- **No captions exist.** `/videos/<clip_id>/captions.vtt` returns 200 but is an empty 40-byte stub for every clip sampled (old and new). Whisper transcription is REQUIRED for transcripts — do not build a caption path.
- **Video download is gated.** Direct MP4 (`archive-video.granicus.com/fairfax/fairfax_<uuid>.mp4`) and the HLS playlist both return 403 to plain curl. First Phase 1 task: spike audio acquisition with `yt-dlp` (it has a Granicus extractor) or replicate the player's session/headers. Treat this as a risk until proven.
- The city may separately post PDFs on `fairfaxva.gov` (agendas/minutes) even when Granicus also has them — treat `fairfaxva.gov` as a secondary source for anything Granicus is missing.

---

## 1. Architecture

```
[Granicus scraper] --> [raw store: PDFs, video/audio, captions]
        |
        v
[Extraction pass 1: raw text]   (PDF text extraction, caption/transcript text)
        |
        v
[Extraction pass 2: LLM structuring]  (Claude API — entities, votes, topics, summaries)
        |
        v
[Postgres: structured facts]  +  [pgvector: chunk embeddings]
        |
        v
[API layer: REST/GraphQL for front end + RAG query endpoint]
        |
        v
[Front end: timeline/dashboard + topic tracker + Q&A chat]
```

Design principle borrowed from claude-obsidian: separate the **raw ingest** (cheap, deterministic, idempotent) from the **LLM structuring pass** (expensive, re-runnable independently) from the **wiki/graph layer** (entities linked across meetings so "progress over time" is a query, not a re-summarization).

---

## 2. Tech stack (proposed — agent should confirm versions at setup time)

- **Language:** Python for ingestion/extraction (best PDF/video tooling), TypeScript for API + front end
- **DB:** Postgres 16 + `pgvector` extension (structured facts + embeddings in one place, avoids running two databases)
- **PDF extraction:** `pymupdf` (fitz)
- **Video/audio acquisition:** `yt-dlp` (Granicus extractor) — direct MP4/HLS URLs 403 without a session
- **Transcription:** `faster-whisper` locally, or a hosted transcription API if run in cloud. Required, not a fallback — no captions exist (section 0). Extract audio only (ffmpeg) before transcribing; don't store full video.
- **LLM:** Claude API (Sonnet for extraction, cheaper/faster model acceptable for simple entity tagging) — see `/mnt/skills/public/product-self-knowledge` for current model names when the agent gets there. Use tool-use / structured output for extraction, not "return only JSON" prompting.
- **Embeddings:** pick provider at Phase 4 start (e.g. Voyage = 1024 dims, OpenAI = 1536) — don't hardcode the vector dimension in the schema before then
- **Backend framework:** FastAPI
- **Front end:** Next.js + Tailwind
- **Local dev:** Docker Compose (Postgres + API + front end)
- **Cloud target:** containerized deploy (Fly.io / Render / AWS ECS — decide at Phase 5, don't lock in now)

---

## 3. Data model (Postgres — initial schema)

```sql
meetings (
  id, granicus_clip_id, granicus_view_id, meeting_type, -- 'council_regular','council_work_session','planning_commission' (parsed from title)
  meeting_date, title, video_url, agenda_url, minutes_url, status, -- 'discovered','fetched','extracted'
  UNIQUE (granicus_view_id, granicus_clip_id)
)

agenda_items (  -- first-class: the natural unit of a "thread"; votes and mentions FK here
  id, meeting_id, label, title, description, outcome,
  UNIQUE (meeting_id, label)
)

documents (
  id, meeting_id, agenda_item_id NULL, doc_type, -- 'agenda_item','minutes','agenda_packet','staff_report'
  source_url UNIQUE, local_path, raw_text, fetched_at
)

transcript_chunks (
  id, meeting_id, start_seconds, end_seconds, text, embedding vector -- dim set when provider chosen (Phase 4)
)

entities (
  id, entity_type, -- 'person','project','ordinance','case_number','location','topic'
  name, canonical_slug UNIQUE, first_seen_meeting_id,
  current_status -- 'proposed','in_progress','approved','completed','deferred', etc.; rolled up from latest entity_update
)

entity_aliases (  -- resolution: 'Mayor Read' -> catherine-read; LLM slugs drift without this
  id, entity_id, alias, UNIQUE (alias)
)

entity_updates (  -- replaces the mutable 'summary' blob: progress over time is a query, and re-runs are idempotent
  id, entity_id, meeting_id, agenda_item_id NULL,
  update_text, status_after NULL,
  UNIQUE (entity_id, meeting_id)  -- re-running Phase 3 replaces, never double-appends
)

entity_mentions (
  id, entity_id, meeting_id, agenda_item_id NULL, document_id NULL, transcript_chunk_id NULL,
  context_text, role, -- e.g. 'sponsor','vote_yes','vote_no','discussed'
  UNIQUE (entity_id, meeting_id, document_id, transcript_chunk_id, role)
)

votes (
  id, meeting_id, agenda_item_id, description, motion_result, -- 'passed','failed','deferred'
  vote_breakdown jsonb, -- {member: 'yes'/'no'/'abstain'/'absent'}
  UNIQUE (meeting_id, agenda_item_id, description)
)

extractions (  -- raw LLM output per meeting, so structuring can be re-run/diffed without re-scraping
  id, meeting_id, prompt_version, model, raw_json jsonb, created_at,
  UNIQUE (meeting_id, prompt_version)
)

ingest_runs (  -- job log for the scheduled pipeline (Phase 6)
  id, started_at, finished_at, phase, meetings_processed, errors jsonb
)
```

Seed `entities` with the known small lists before any LLM pass: current + recent council members, the mayor, Planning Commission members. LLM output must resolve against existing entities (exact slug → alias → fuzzy match) and only create a new entity when nothing matches.

Use Alembic migrations from the start (drop the hand-synced `schema.sql` + `models.py` pair) — this schema WILL churn as extraction reveals real-world shape (e.g. Fairfax uses tax map parcel numbers, ordinance numbers like "2020-27", resolution numbers like "R-25-xxx" — these are natural entity keys).

---

## 4. Phased build plan

### Phase 1 — Discovery & raw ingest
**Task:** Build a scraper that, given a `view_id`, lists all meetings from the archive page (date, clip_id, title, type parsed from title), filters to in-scope bodies (City Council + Planning Commission — see section 5 decisions), and downloads: agenda HTML, all linked agenda-item PDFs, minutes PDF (via `MinutesViewer.php` doc_id links), and the meeting audio.
**Spike first (risk):** audio acquisition. Direct MP4/HLS 403s to curl — try `yt-dlp` against `player/clip/<clip_id>` URLs; extract audio-only via ffmpeg. Prove this on one clip before building the rest.
**Definition of done:** Running the scraper for the last 24 months of Council + Planning Commission meetings populates `meetings` + `documents` rows and saves files (PDFs, audio) to disk, is idempotent (safe to re-run), rate-limits requests politely, and logs failures without crashing the whole run.

### Phase 2 — Raw text extraction + transcription
**Task:** For every `documents` row, extract raw text (PDF → text via pymupdf, OCR fallback for scanned PDFs). Transcribe every meeting's audio (no captions exist — this is required, not a fallback). Populate `raw_text` and `transcript_chunks` with timestamps.
**Speaker identification (two stages, second lands in Phase 3):**
1. *Diarization* — transcribe with speaker labels. Preferred: a hosted transcription API with built-in diarization (AssemblyAI / Deepgram / Rev, ~$0.12–0.40 per audio-hour → ~$50–180 for the whole backfill), one call returning timestamped speaker-labeled segments. Local fallback: faster-whisper + pyannote (WhisperX) — free but adds torch + days of compute. Schema: add `speaker_label` (raw diarization label, always kept) and `speaker_entity_id` (nullable FK to entities) to `transcript_chunks` via Alembic when this phase starts.
2. *Attribution* (Phase 3 LLM task) — council meetings are self-labeling: roll call, chair recognizing speakers by name, votes called by name, public commenters stating their names. Give Claude the diarized transcript + seeded member entities + minutes attendance and map each speaker label to a person per meeting. Only set `speaker_entity_id` on confident matches; leave the rest as unidentified — never guess an attribution into a public app.
**Definition of done:** Every fetched document/audio file has usable extracted text; transcripts carry speaker labels; spot-check 5 meetings by hand for extraction, transcription, and attribution quality (roll-call votes in the transcript should attribute to the right members). Transcription is resumable — a killed run picks up where it left off, never re-transcribes a finished meeting.
**Cost note:** ~24 months × Council + PC ≈ 100–150 meetings × 2–3 h audio. Hosted API with diarization ≈ $50–180 for the full backfill; local faster-whisper is free but slow (days of compute) and still needs pyannote for speakers. Hosted is the recommended default.

### Phase 3 — LLM structuring pass
**Task:** Per meeting: first parse the agenda into `agenda_items` rows, then segment the minutes by agenda item and extract **per item** (not one mega-prompt per meeting — 3-hour meetings blow the context and degrade extraction): entities mentioned, votes with breakdown, outcome, and a per-item plain-language summary. Use tool-use/structured output. Store the raw model output in `extractions` keyed by (meeting_id, prompt_version). Resolve entities against existing rows (exact slug → alias → fuzzy match) before creating new ones; write an `entity_updates` row per (entity, meeting) and roll up `current_status`. Minutes are the source of truth for votes/outcomes; transcript chunks provide timestamped citations and discussion color.
**Definition of done:** Given 2 meetings that both discuss the same project, the entity's `entity_updates` timeline reflects both, in order, with citations back to meeting_id/document_id for each claim — and re-running Phase 3 on the same meetings produces identical rows (no duplicates, no double-appends).

### Phase 4 — Embeddings + RAG API
**Task:** Embed `transcript_chunks` and document text; build a FastAPI endpoint that takes a natural-language question, retrieves relevant chunks + entity summaries, and returns an answer with citations (meeting date + link to Granicus clip/document).
**Definition of done:** Asking "what's the status of the George Snyder Trail project" returns an answer citing specific meetings/dates, not a hallucinated summary.

### Phase 5 — Front end
**Task:** Build the Next.js app with three views. The **project tracker is the core product** — build it first within this phase:
1. **Topic/project tracker** — pick an entity, see its status and full `entity_updates` timeline across meetings with links back to source (Granicus clip at timestamp, or PDF)
2. **Timeline/dashboard** — meetings list, filterable by body/date/topic, each meeting showing its agenda items and outcomes
3. **Ask** — chat interface hitting the Phase 4 RAG endpoint, showing citations as clickable links to the original Granicus video timestamp or PDF
**Definition of done:** A user can go from "what's happening with project X" to its status + dated history in two clicks, and from "ask a question" to "watch the exact council clip that answered it."

### Phase 6 — Cloud deployment (public-facing)
**Task:** Containerize all services, set up a scheduled job (cron/worker) to run Phase 1–3 automatically on a schedule (e.g. daily) so new meetings get ingested without manual re-runs. Move Postgres to a managed instance. Public hardening: rate-limit the `/ask` endpoint (it spends LLM tokens per request), cache read endpoints, put the frontend behind a domain + CDN. Never rehost video — always link back to Granicus (authoritative source, zero bandwidth cost). Note: transcription is the heavy step — either run ingestion on a box with a GPU and push results to the managed DB, or use a hosted transcription API in the cloud worker.
**Definition of done:** New Fairfax council meetings appear in the app within 24 hours of being posted, with no manual intervention, and a stranger hammering `/ask` can't run up the LLM bill.

---

## 5. Scope decisions (made 2026-07-11 — build to these)

- **Bodies:** City Council (regular, work session, special) + Planning Commission. Same pipeline; filter by title parse. Other bodies (School Board, BZA, committees) are out of scope for now but the filter should make adding them a config change.
- **Backfill:** ~24 months, then extend backward later if wanted. Documents are cheap to backfill deeper; transcripts are the cost.
- **Transcripts:** up front — Whisper transcription is part of the initial ingest, not deferred.
- **Audience:** public-facing from the start — see Phase 6 hardening notes. No user auth needed (read-only public data), but rate limiting on LLM-backed endpoints is required.

---

## 6. Instructions for the coding agent

- Work phase by phase; don't start Phase 3 until Phase 1–2 are producing verified output on real data.
- Keep ingestion idempotent — re-running should never duplicate rows or re-download unchanged files.
- Every structured claim in the DB should be traceable to a `document_id` or `transcript_chunk_id` — no ungrounded facts.
- Commit working code at the end of each phase before moving on.
