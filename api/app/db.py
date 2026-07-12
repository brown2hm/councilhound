"""DB session dependency. The API reuses the councilhound package (models,
session resolution) — locally via PYTHONPATH=ingestion/src, in Docker the
image copies ingestion/src alongside app/."""
from councilhound.db.session import get_session


def db_session():
    session = get_session()
    try:
        yield session
    finally:
        session.close()
