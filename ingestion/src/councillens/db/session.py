"""DB engine/session helpers.

If DATABASE_URL is set (docker-compose, cloud), use it. If not, fall back to
an embedded dev Postgres (pgserver package) living under DATA_DIR/pgdev —
real Postgres 16 with pgvector, no Docker or managed instance needed for
local development.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from councillens.config import DATA_DIR, DATABASE_URL

_engine = None
_SessionLocal = None


def _resolve_database_url() -> str:
    if DATABASE_URL:
        url = DATABASE_URL
    else:
        import pgserver  # local-dev only dependency

        os.makedirs(DATA_DIR, exist_ok=True)
        server = pgserver.get_server(os.path.join(DATA_DIR, "pgdev"))
        url = server.get_uri()
    # psycopg (v3) driver regardless of how the URL was spelled
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_resolve_database_url())
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()
