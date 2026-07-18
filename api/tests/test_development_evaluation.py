"""Impact-evaluation endpoints: 404 states, response shape, list flag."""
from councilhound.db.models import CityProject, ProjectEvaluation


def _project(db, slug="circle-gateway"):
    project = CityProject(external_slug=slug, name="Circle Gateway",
                          detail_url=f"https://example.gov/{slug}")
    db.add(project)
    db.flush()
    return project


def _synthesized(db, project):
    evaluation = ProjectEvaluation(
        city_project_id=project.id,
        status="synthesized",
        spec={"name": project.name, "proposed": {"units": 261, "retail_sqft": 16530}},
        module_results=[{
            "module": "economic",
            "metrics": [{"name": "New households", "value": 248.0, "unit": "households",
                         "low": 235.0, "high": 253.0, "provenance": [], "assumptions": [],
                         "method": "units x occupancy", "headline": True}],
            "narrative_notes": ["screening estimate"],
        }],
        map_layers={"site": {"type": "FeatureCollection", "features": []}},
        assumptions=[{"key": "occupancy_rate", "value": 0.95, "low": 0.9, "high": 0.97,
                      "basis": "norm", "rationale": "r"}],
        sources=[{"source_name": "ACS", "url": "u", "vintage": "2023",
                  "retrieved_at": "2026-07-18T00:00:00Z"}],
        report_markdown="# Impact analysis\n\nThe 261 units...",
        report_model="claude-sonnet-4-6",
        report_prompt_version="v1",
    )
    db.add(evaluation)
    db.commit()
    return evaluation


def test_404_when_no_evaluation(client, db):
    _project(db)
    db.commit()
    assert client.get("/development/circle-gateway/evaluation").status_code == 404


def test_404_when_not_synthesized(client, db):
    project = _project(db)
    db.add(ProjectEvaluation(city_project_id=project.id, status="confirmed",
                             spec={"name": "x"}))
    db.commit()
    assert client.get("/development/circle-gateway/evaluation").status_code == 404


def test_evaluation_shape(client, db):
    project = _project(db)
    _synthesized(db, project)
    body = client.get("/development/circle-gateway/evaluation").json()
    assert body["slug"] == "circle-gateway"
    assert body["report_markdown"].startswith("# Impact analysis")
    assert body["metrics"][0]["module"] == "economic"
    assert body["metrics"][0]["headline"] is True
    assert body["assumptions"][0]["key"] == "occupancy_rate"
    assert body["sources"][0]["source_name"] == "ACS"
    assert body["map_layers"]["site"]["type"] == "FeatureCollection"
    assert body["narrative_notes"] == ["screening estimate"]
    assert body["spec"]["proposed"]["units"] == 261


def test_list_has_evaluation_flag(client, db):
    with_eval = _project(db, "with-eval")
    _synthesized(db, with_eval)
    _project(db, "without-eval")
    db.commit()
    rows = {r["slug"]: r for r in client.get("/development/").json()}
    assert rows["with-eval"]["has_evaluation"] is True
    assert rows["without-eval"]["has_evaluation"] is False
