"""App boots and serves /health (no DB). Endpoint coverage lives in
test_endpoints.py against a scratch database."""
from fastapi.testclient import TestClient

from app.main import app


def test_health():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
