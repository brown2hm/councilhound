"""Wiki endpoints: payload shape, page ordering, 404s, has_wiki flag."""
from councilhound.db.models import CityProject, Entity, ProjectEvaluation, WikiPage


def _wiki_project(db, slug="circle-gateway", official_slug="circle-gateway-official"):
    entity = Entity(entity_type="project", name="Circle Gateway",
                    canonical_slug=slug, current_status="approved")
    db.add(entity)
    db.flush()
    project = CityProject(external_slug=official_slug, entity_id=entity.id,
                          name="Circle Gateway",
                          detail_url=f"https://example.gov/{official_slug}")
    db.add(project)
    db.flush()
    pages = [
        ("history", {"type": "project-history", "title": "Circle Gateway — meeting history",
                     "timestamp": "2026-06-09"}, "## 2026-06-09 — City Council\n"),
        ("overview", {"type": "development-project", "title": "Circle Gateway",
                      "description": "A mixed-use redevelopment.",
                      "timestamp": "2026-06-09"}, "Circle Gateway is a project.\n"),
        ("positions", {"type": "project-positions", "title": "Positions",
                       "timestamp": "2026-06-09"}, "## Open questions\n"),
    ]
    for page, frontmatter, body in pages:
        db.add(WikiPage(path=f"projects/{slug}/{page}.md", entity_id=entity.id,
                        kind="concept", page=page, frontmatter=frontmatter,
                        body=body, content_hash=page))
    db.add(WikiPage(path=f"projects/{slug}/log.md", entity_id=entity.id,
                    kind="log", page="log", frontmatter=None,
                    body="# Log\n\n## 2026-07-19\n\n- Seeded.\n", content_hash="log"))
    db.add(WikiPage(path=f"projects/{slug}/index.md", entity_id=entity.id,
                    kind="index", page="index", frontmatter=None,
                    body="# Circle Gateway\n", content_hash="idx"))
    db.commit()
    return entity, project


def test_development_wiki_payload(client, db):
    _wiki_project(db)
    body = client.get("/development/circle-gateway-official/wiki").json()
    assert body["entity_slug"] == "circle-gateway"
    assert body["official_slug"] == "circle-gateway-official"
    # concept pages only, in reading order; reserved files never appear
    assert [p["page"] for p in body["pages"]] == ["overview", "history", "positions"]
    assert body["pages"][0]["title"] == "Circle Gateway"
    assert body["pages"][0]["description"] == "A mixed-use redevelopment."
    assert body["log"].startswith("# Log")
    assert body["pushed_at"] is not None


def test_entity_wiki_payload(client, db):
    _wiki_project(db)
    body = client.get("/entities/circle-gateway/wiki").json()
    assert body["entity_slug"] == "circle-gateway"
    assert len(body["pages"]) == 3


def test_wiki_404s(client, db):
    entity = Entity(entity_type="project", name="No Wiki",
                    canonical_slug="no-wiki")
    db.add(entity)
    db.flush()
    db.add(CityProject(external_slug="no-wiki-official", entity_id=entity.id,
                       name="No Wiki", detail_url="https://example.gov/no-wiki"))
    db.commit()
    assert client.get("/development/no-wiki-official/wiki").status_code == 404
    assert client.get("/development/does-not-exist/wiki").status_code == 404
    assert client.get("/entities/no-wiki/wiki").status_code == 404


def test_evaluation_has_wiki_flag(client, db):
    entity, project = _wiki_project(db)
    db.add(ProjectEvaluation(
        city_project_id=project.id, status="synthesized",
        spec={"name": project.name, "proposed": {}},
        module_results=[], report_markdown="# Impact analysis\n"))
    db.commit()
    body = client.get("/development/circle-gateway-official/evaluation").json()
    assert body["has_wiki"] is True
