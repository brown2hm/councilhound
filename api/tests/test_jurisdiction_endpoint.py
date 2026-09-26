"""GET /jurisdiction/ hands the front end the display config."""
from fastapi.testclient import TestClient

from app.main import app


def test_jurisdiction_payload_shape():
    client = TestClient(app)
    r = client.get("/jurisdiction/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=3600"
    j = r.json()
    assert j["slug"] == "fairfax_city_va" and j["identity"]["short_name"] == "City of Fairfax"
    assert [b["key"] for b in j["bodies"]][:2] == ["city_council", "planning_commission"]
    assert {b["color"] for b in j["bodies"]} == {0, 1, 2, 3, 4}
    assert [b["key"] for b in j["bodies"] if b["hot"]] == ["city_council", "planning_commission"]
    assert j["bodies"][1]["recommends"] is True
    assert j["bodies"][0]["roles"] == ["Mayor", "Councilmember"] and j["bodies"][3]["roles"] == []
    assert j["display"]["map_center"] == [38.8462, -77.3064]
    assert j["features"] == {"impact": True, "projects": True}
    assert j["identity"]["timezone"] == "America/New_York"


def test_impact_feature_off_hides_evaluations(db, client, monkeypatch):
    """With features.impact off, official projects never claim an analysis
    and the evaluation route is a 404, whatever the database holds."""
    from app.routers import development
    from councilhound.db.models import CityProject

    db.add(CityProject(external_slug="somewhere", name="Somewhere Plaza",
                       detail_url="https://example.gov/projects/somewhere"))
    db.commit()
    monkeypatch.setattr(development, "_IMPACT", False)
    r = client.get("/development/somewhere")
    assert r.status_code == 200
    assert r.json()["has_evaluation"] is False and r.json()["no_analysis_reason"] is None
    assert client.get("/development/somewhere/evaluation").status_code == 404
    assert client.get("/development/").json()[0]["no_analysis_reason"] is None
