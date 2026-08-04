"""GET /development/{slug} — the tab-shell payload: full official record
plus which views (wiki / analysis / documents) exist for the project."""
from councilhound.db.models import CityProject, Entity, ProjectEvaluation, WikiPage


def _project(db, slug="circle-gateway", **kwargs):
    project = CityProject(external_slug=slug, name="Circle Gateway",
                          detail_url=f"https://example.gov/{slug}", **kwargs)
    db.add(project)
    db.flush()
    return project


def _entity_with_wiki(db, project, slug="circle-gateway-entity"):
    entity = Entity(entity_type="project", name=project.name,
                    canonical_slug=slug, current_status="approved")
    db.add(entity)
    db.flush()
    project.entity_id = entity.id
    db.add(WikiPage(path=f"projects/{slug}/overview.md", entity_id=entity.id,
                    kind="concept", page="overview",
                    frontmatter={"title": project.name},
                    body="An overview.\n", content_hash="ov"))
    return entity


def test_404_for_unknown_slug(client, db):
    _project(db)
    db.commit()
    assert client.get("/development/does-not-exist").status_code == 404


def test_full_record_passthrough(client, db):
    _project(db,
             description="276 apartments over ground-floor retail",
             requests="Rezoning to PD-M",
             planner_name="A. Planner", planner_phone="555-0100",
             planner_email="planner@example.gov",
             documents=[{"label": "Staff report", "url": "https://x/sr.pdf"}],
             official_timeline=["2026-01-05 — Application accepted"])
    db.commit()
    body = client.get("/development/circle-gateway").json()
    assert body["slug"] == "circle-gateway"
    assert body["description"].startswith("276 apartments")
    assert body["requests"] == "Rezoning to PD-M"
    assert body["planner_email"] == "planner@example.gov"
    assert body["documents"] == [{"label": "Staff report", "url": "https://x/sr.pdf"}]
    assert body["official_timeline"] == ["2026-01-05 — Application accepted"]


def test_wiki_only_project(client, db):
    project = _project(db, description="276 apartments (multifamily units)")
    _entity_with_wiki(db, project)
    db.commit()
    body = client.get("/development/circle-gateway").json()
    assert body["has_wiki"] is True
    assert body["wiki_pushed_at"] is not None
    assert body["entity_slug"] == "circle-gateway-entity"
    assert body["evaluation_status"] is None
    assert body["has_evaluation"] is False
    assert body["no_analysis_reason"] == "not yet evaluated"


def test_synthesized_project(client, db):
    project = _project(db)
    db.add(ProjectEvaluation(city_project_id=project.id, status="synthesized",
                             spec={"name": project.name},
                             report_markdown="# Impact analysis\n"))
    db.commit()
    body = client.get("/development/circle-gateway").json()
    assert body["evaluation_status"] == "synthesized"
    assert body["has_evaluation"] is True
    assert body["no_analysis_reason"] is None
    assert body["has_wiki"] is False
    assert body["wiki_pushed_at"] is None


def test_mid_pipeline_evaluation(client, db):
    project = _project(db)
    db.add(ProjectEvaluation(city_project_id=project.id, status="confirmed",
                             spec={"name": project.name}))
    db.commit()
    body = client.get("/development/circle-gateway").json()
    assert body["evaluation_status"] == "confirmed"
    assert body["has_evaluation"] is False
    assert body["no_analysis_reason"] == "analysis in preparation"
