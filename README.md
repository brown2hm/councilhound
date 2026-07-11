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

## Local dev

```
cp .env.example .env   # fill in ANTHROPIC_API_KEY etc.
docker compose up --build
```

- Postgres (with pgvector) on :5432
- API on :8000 (http://localhost:8000/health)
- Frontend on :3000

## Order of work

Follow the plan's phases in order. Phase 1 (`ingestion/src/fairfax_kb/scraper/granicus.py`)
comes first — nothing downstream matters until real meeting data is landing
in Postgres.
