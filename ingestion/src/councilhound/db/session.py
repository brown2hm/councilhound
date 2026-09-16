"""DB engine/session helpers.

If DATABASE_URL is set (docker-compose, cloud), use it. If not, fall back to
an embedded dev Postgres (pgserver package) living under DATA_DIR/pgdev —
real Postgres 16 with pgvector, no Docker or managed instance needed for
local development.
"""
import os
import threading
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from councilhound.config import DATA_DIR, DATABASE_URL

_engine = None
_SessionLocal = None
# Concurrent first requests (e.g. the API serving parallel page fetches)
# must not race pgserver's pg_ctl start — the losers cache a dead handle
# and every later request 500s.
_init_lock = threading.RLock()  # reentrant: get_session -> get_engine nests it


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
        with _init_lock:
            if _engine is None:
                _engine = create_engine(_resolve_database_url())
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        with _init_lock:
            if _SessionLocal is None:
                _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


# --- one runner per pipeline stage ----------------------------------------
# The jobs app runs a nightly `daily` machine, an hourly `catchup` machine and
# ad-hoc one-off machines against the same database. Every stage is
# idempotent in its *result*, but two runners in the same stage at the same
# time select the same pending rows (oldest first), both pay for the LLM /
# transcription call, and the loser dies on the unique constraint (seen
# 2026-09-16: catchup vs. a backfill both structuring meeting 242). A
# session-level Postgres advisory lock per stage lets the second runner see
# the first and skip. Session-level locks are released when the connection
# drops, so a machine that exits — or is killed — never leaves one behind.
#
# Keys are (namespace, stage) int pairs so they cannot collide with any other
# advisory-lock user of the same database.
ADVISORY_NAMESPACE = 0x434F554E  # "COUN"
STAGE_LOCK_KEYS = {
    "ingest": 1,
    "structure": 2,
    "transcribe": 3,
    "embed": 4,
    "profile": 5,
}


@contextmanager
def stage_lock(stage: str, engine=None):
    """Try to take the advisory lock for ``stage``; yield whether we hold it.

    Usage::

        with stage_lock("structure") as held:
            if not held:
                log.warning("another runner holds structure; skipping")
                return
            structure_pending(session)

    The lock lives on its own connection, checked out from the pool for the
    whole block, because a session-level advisory lock belongs to the
    Postgres backend that took it and an ORM session's connection goes back
    to the pool on every commit. Non-blocking: ``pg_try_advisory_lock``
    returns immediately, so a runner never waits on another. Released
    explicitly on exit and implicitly if the process dies.
    """
    try:
        key = STAGE_LOCK_KEYS[stage]
    except KeyError:
        raise ValueError(
            f"unknown stage {stage!r}; expected one of {sorted(STAGE_LOCK_KEYS)}") from None
    engine = engine if engine is not None else get_engine()
    params = {"ns": ADVISORY_NAMESPACE, "key": key}
    conn = engine.connect()
    try:
        held = bool(conn.execute(
            text("SELECT pg_try_advisory_lock(:ns, :key)"), params).scalar())
        conn.commit()  # end the autobegun transaction; the lock outlives it
        try:
            yield held
        finally:
            if held:
                conn.execute(text("SELECT pg_advisory_unlock(:ns, :key)"), params)
                conn.commit()
    finally:
        conn.close()
