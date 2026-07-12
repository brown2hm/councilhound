"""Scratch-database fixture for API endpoint tests, mirroring
ingestion/tests/conftest.py, plus a TestClient wired to it via FastAPI
dependency override."""
import re

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from councilhound.db import session as dbsession
from councilhound.db.models import Base

from app.db import db_session
from app.main import app

TEST_DB = "councilhound_api_test"


@pytest.fixture
def db(request):
    base_url = dbsession._resolve_database_url()
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f"DROP DATABASE IF EXISTS {TEST_DB} (FORCE)"))
        conn.execute(sa.text(f"CREATE DATABASE {TEST_DB}"))
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


@pytest.fixture
def client(db):
    app.dependency_overrides[db_session] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
