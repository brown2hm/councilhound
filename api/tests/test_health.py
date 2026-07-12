"""Smoke tests: the app imports, mounts its routers, and serves /health.
Catches broken imports/routing before deploy; real endpoint tests arrive
with Phase 4 implementations."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_routers_mounted():
    assert client.get("/meetings/").status_code == 200
    assert client.get("/entities/some-slug").status_code == 200
    assert client.post("/ask/", json={"question": "test"}).status_code == 200
