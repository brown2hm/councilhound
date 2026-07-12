# CouncilLens

Turns any [Granicus](https://granicus.com)-hosted public meeting archive —
the platform behind hundreds of US city/county "view meetings online" pages —
into a structured, searchable knowledge base: meeting history, project/topic
progress over time, and natural-language Q&A with citations back to the
original video timestamp or document.

The reference deployment is City of Fairfax, VA (`fairfax.granicus.com`);
`PLAN.md` is the phased build plan written against it. The pipeline itself is
Granicus-generic: point it at a different city's Granicus subdomain and view
IDs, and map that city's archive section names (see
[Adapting to your city](#adapting-to-your-city)).

## Services

- `ingestion/` — Phase 1-3: scraper, text extraction + transcription, LLM structuring pass. Python.
- `api/` — Phase 4: FastAPI app, RAG query endpoint, serves data to front end.
- `frontend/` — Phase 5: Next.js app (timeline, topic tracker, ask).
- `infra/` — Phase 6: containerization + (later) k8s manifests.

## Configuration

Everything city-specific is environment config (`.env`, see `.env.example`):

| Variable | Meaning |
|---|---|
| `GRANICUS_BASE_URL` | Your city's Granicus subdomain, e.g. `https://<city>.granicus.com` |
| `GRANICUS_VIEW_IDS` | Comma-separated archive view IDs (find them in the `?view_id=` param of the city's "view meetings" page) |
| `DATABASE_URL` | Postgres connection string; leave unset for the embedded local dev DB |
| `ANTHROPIC_API_KEY` | For the Phase 3 structuring pass and Phase 4 Q&A |

## Local dev (no Docker needed for ingestion)

Ingestion runs against an embedded Postgres 16 + pgvector (the `pgserver`
package) when `DATABASE_URL` is unset — data lives in `data/pgdev/`.

```
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python -r ingestion/requirements-dev.txt
cd ingestion
PYTHONPATH=src ../.venv/bin/python -m fairfax_kb.cli init-db
PYTHONPATH=src ../.venv/bin/python -m fairfax_kb.cli ingest --since 2024-07-01 --skip-media
PYTHONPATH=src ../.venv/bin/python -m fairfax_kb.cli status
```

Drop `--skip-media` to also download meeting MP3s (needed for transcription;
a full council meeting is ~80–150 MB, a 24-month backfill is roughly
10–20 GB). Transcription (`... cli transcribe`) prefers `mlx-whisper` on
Apple Silicon (~35x realtime on GPU) and falls back to `faster-whisper` on
CPU elsewhere.

Schema changes: edit `ingestion/src/fairfax_kb/db/models.py`, then
`cd ingestion && alembic revision --autogenerate -m "..."` and `init-db`.

### Docker (full stack)

```
cp .env.example .env   # fill in ANTHROPIC_API_KEY etc.
docker compose up --build
docker compose run ingestion python -m fairfax_kb.cli init-db
```

- Postgres (with pgvector) on :5432
- API on :8000 (http://localhost:8000/health)
- Frontend on :3000

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
   `ingestion/src/fairfax_kb/scraper/granicus.py` to map your city's section
   headers and meeting-title patterns to the bodies you want to track.
3. **Seeded entities** (Phase 3) — the LLM pass resolves people against a
   seeded list of council members / commissioners; seed your city's roster.

Two Granicus behaviors worth knowing, verified against the reference city:
requests need a browser-ish User-Agent (bare curl gets 403s), and the
caption endpoint (`/videos/<clip>/captions.vtt`) may exist but be empty —
CouncilLens transcribes the MP3 audio rather than relying on captions.

## Order of work

Follow the plan's phases in order. Implemented so far: Phase 1 (scraper +
raw ingest: `fairfax_kb/scraper/granicus.py`, `fairfax_kb/pipeline.py`) and
Phase 2 (text extraction: `fairfax_kb/extraction/pdf_text.py`, transcription:
`fairfax_kb/extraction/transcript.py`). Next up: Phase 3 — entity seeding and
the LLM structuring pass.
