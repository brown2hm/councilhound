import re

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from councilhound.db import session as dbsession
from councilhound.db.models import Base

TEST_DB = "councilhound_test"


@pytest.fixture
def db_session():
    """Session against a scratch database on the same Postgres instance the
    app uses (embedded pgserver locally, DATABASE_URL elsewhere). Created
    fresh and dropped per test."""
    base_url = dbsession._resolve_database_url()
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f"DROP DATABASE IF EXISTS {TEST_DB} (FORCE)"))
        conn.execute(sa.text(f"CREATE DATABASE {TEST_DB}"))

    # swap the database segment of the URL: .../<db>?host=... or .../<db>
    test_url = re.sub(r"/[^/?]+(\?|$)", f"/{TEST_DB}\\1", base_url, count=1)
    engine = sa.create_engine(test_url)
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f"DROP DATABASE IF EXISTS {TEST_DB} (FORCE)"))
        admin.dispose()
