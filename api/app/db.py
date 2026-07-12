"""DB session dependency. The API reuses the councillens package (models,
session resolution) — locally via PYTHONPATH=ingestion/src, in Docker the
image copies ingestion/src alongside app/."""
from councillens.db.session import get_session


def db_session():
    session = get_session()
    try:
        yield session
    finally:
        session.close()
