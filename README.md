# Fairfax City Council Knowledge Base

Ingests City of Fairfax, VA council meeting videos/transcripts + agenda/minutes
documents into a structured knowledge base, and serves a front end for
browsing meeting history, tracking project/topic progress, and asking
natural-language questions with citations.

See `PLAN.md` for the full phased build plan. This repo is the skeleton — most
modules are stubs with docstrings pointing at the plan phase they implement.

## Services

- `ingestion/` — Phase 1-3: scraper, text extraction, LLM structuring pass. Python.
- `api/` — Phase 4: FastAPI app, RAG query endpoint, serves data to front end.
- `frontend/` — Phase 5: Next.js app (timeline, topic tracker, ask).
- `infra/` — Phase 6: containerization + (later) k8s manifests.

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

Drop `--skip-media` to also download meeting MP3s (needed for Phase 2
transcription; a full council meeting is ~80–150 MB, the 24-month backfill
is roughly 10–20 GB).

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

## Order of work

Follow the plan's phases in order. Phase 1 (scraper + raw ingest) is
implemented: `fairfax_kb/scraper/granicus.py` (archive parsing) and
`fairfax_kb/pipeline.py` (discover / fetch_documents / fetch_media).
Next up: Phase 2 — PDF/HTML text extraction and Whisper transcription.
