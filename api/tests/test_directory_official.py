"""Official records list regardless of the recurring-only minimum."""
from councilhound.db.models import CityProject, Entity


def test_official_records_ignore_min_updates(db, client):
    e = Entity(entity_type="project", name="RZ-2026-PR-00099", canonical_slug="rz-2026-pr-00099")
    db.add(e)
    db.flush()
    db.add(CityProject(external_slug="rz-2026-pr-00099", name="RZ-2026-PR-00099",
                       detail_url="https://plus.example/1", entity_id=e.id))
    db.commit()
    r = client.get("/entities/?official=true&min_updates=2")
    assert [x["slug"] for x in r.json()] == ["rz-2026-pr-00099"]
    # the meeting-derived list still hides the no-history tail
    assert client.get("/entities/?official=false&min_updates=2").json() == []
