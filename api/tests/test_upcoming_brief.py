"""Annotated pre-meeting agenda: topic matching against fetched agenda text."""
import datetime

from councilhound.db.models import (
    CityProject, Entity, EntityAlias, EntityUpdate, Meeting, ProjectEvaluation,
    UpcomingMeeting,
)


def _seed(db):
    trail = Entity(entity_type="project", name="George Snyder Trail",
                   canonical_slug="george-snyder-trail", current_status="denied")
    person = Entity(entity_type="person", name="Stacy Hall", canonical_slug="stacy-hall")
    davies = Entity(entity_type="project", name="Davies Property",
                    canonical_slug="davies-property", current_status="approved")
    db.add_all([trail, person, davies])
    db.flush()
    db.add(EntityAlias(entity_id=davies.id, alias="4131 Chain Bridge Road Davies Property"))
    m = Meeting(granicus_view_id="13", granicus_clip_id="c1", body="city_council",
                meeting_type="council_meeting", title="City Council Meeting",
                meeting_date=datetime.date(2026, 6, 10))
    db.add(m)
    db.flush()
    db.add(EntityUpdate(entity_id=trail.id, meeting_id=m.id,
                        update_text="Cancelled on a 4-2 vote."))
    db.add(EntityUpdate(entity_id=davies.id, meeting_id=m.id,
                        update_text="GDP amendment approved."))
    cp = CityProject(external_slug="Davies-Property", name="Davies Property",
                     detail_url="https://example.gov/davies", entity_id=davies.id)
    db.add(cp)
    db.flush()
    db.add(ProjectEvaluation(city_project_id=cp.id, status="synthesized"))
    db.add(UpcomingMeeting(
        granicus_event_id="ev-42", granicus_view_id="13",
        title="City Council Meeting", body="city_council",
        starts_at=datetime.datetime(2026, 7, 28, 19, 0),
        agenda_url="https://example.gov/agenda.pdf",
        agenda_text="7a Public hearing on the Davies Property GDP amendment\n"
                    "8 Update on the George Snyder Trail cancellation\n"
                    "9 Council comments by Stacy Hall\n"))
    db.commit()


def test_upcoming_brief_matches_tracked_topics(db, client):
    _seed(db)
    resp = client.get("/meetings/upcoming/ev-42")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_agenda_text"] is True

    by_slug = {t["slug"]: t for t in data["topics"]}
    # persons never appear in the brief
    assert set(by_slug) == {"george-snyder-trail", "davies-property"}

    davies = by_slug["davies-property"]
    assert davies["current_status"] == "approved"
    assert "Public hearing on the Davies Property" in davies["agenda_context"]
    assert davies["latest_update"]["text"] == "GDP amendment approved."
    assert davies["evaluation_slug"] == "Davies-Property"

    trail = by_slug["george-snyder-trail"]
    assert trail["evaluation_slug"] is None
    assert trail["update_count"] == 1


def test_upcoming_brief_without_agenda(db, client):
    db.add(UpcomingMeeting(granicus_event_id="ev-77", granicus_view_id="13",
                           title="Board of Zoning Appeals"))
    db.commit()
    data = client.get("/meetings/upcoming/ev-77").json()
    assert data["has_agenda_text"] is False
    assert data["topics"] == []
    assert client.get("/meetings/upcoming/nope").status_code == 404
