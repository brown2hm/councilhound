-- Initial schema per fairfax-council-kb-PLAN.md section 3.
-- Loaded automatically into postgres on first container start (docker-entrypoint-initdb.d).
-- Treat as a starting point: expect migrations as extraction reveals real shape.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    granicus_clip_id TEXT NOT NULL,
    granicus_view_id TEXT NOT NULL,
    meeting_type TEXT NOT NULL,
    meeting_date DATE NOT NULL,
    title TEXT,
    video_url TEXT,
    agenda_url TEXT,
    minutes_url TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (granicus_view_id, granicus_clip_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES meetings(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT,
    agenda_item_label TEXT,
    raw_text TEXT,
    fetched_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS transcript_chunks (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES meetings(id) ON DELETE CASCADE,
    start_seconds NUMERIC,
    end_seconds NUMERIC,
    text TEXT NOT NULL,
    embedding vector(1536)
);

CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    canonical_slug TEXT UNIQUE NOT NULL,
    first_seen_meeting_id INTEGER REFERENCES meetings(id),
    summary TEXT
);

CREATE TABLE IF NOT EXISTS entity_mentions (
    id SERIAL PRIMARY KEY,
    entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    meeting_id INTEGER REFERENCES meetings(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id),
    transcript_chunk_id INTEGER REFERENCES transcript_chunks(id),
    context_text TEXT,
    role TEXT
);

CREATE TABLE IF NOT EXISTS votes (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES meetings(id) ON DELETE CASCADE,
    agenda_item_label TEXT,
    description TEXT,
    motion_result TEXT,
    vote_breakdown JSONB
);

CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings (meeting_date);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions (entity_id);
