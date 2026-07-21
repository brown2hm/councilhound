"""Follow-a-topic subscription flow and the iCalendar feed."""
import datetime

from councilhound.db.models import Entity, TopicSubscription, UpcomingMeeting


def _entity(db, name="George Snyder Trail", slug="george-snyder-trail"):
    e = Entity(entity_type="project", name=name, canonical_slug=slug)
    db.add(e)
    db.flush()
    return e


def test_subscribe_confirm_unsubscribe_roundtrip(db, client):
    entity = _entity(db)
    db.commit()

    resp = client.post("/subscriptions/", json={
        "email": "Resident@Example.com", "entity_slug": "george-snyder-trail"})
    assert resp.status_code == 200
    # SMTP is unconfigured in tests, so the mail is dropped but the row exists
    assert resp.json()["status"] == "email-unavailable"
    sub = db.query(TopicSubscription).one()
    assert sub.email == "resident@example.com"  # normalized
    assert sub.confirmed is False

    resp = client.get(f"/subscriptions/confirm?token={sub.token}")
    assert resp.status_code == 200
    db.refresh(sub)
    assert sub.confirmed is True

    resp = client.get(f"/subscriptions/unsubscribe?token={sub.token}")
    assert resp.status_code == 200
    assert db.query(TopicSubscription).count() == 0


def test_subscribe_rejects_junk(db, client):
    _entity(db)
    db.commit()
    assert client.post("/subscriptions/", json={
        "email": "not-an-email", "entity_slug": "george-snyder-trail"}).status_code == 422
    assert client.post("/subscriptions/", json={
        "email": "a@b.co", "entity_slug": "nope"}).status_code == 404


def test_upcoming_ics_feed(db, client):
    db.add(UpcomingMeeting(
        granicus_event_id="ev-1", granicus_view_id="13",
        title="City Council Meeting; special",
        body="city_council",
        starts_at=datetime.datetime(2026, 7, 28, 19, 0),
        agenda_url="https://example.gov/agenda.pdf"))
    db.commit()

    resp = client.get("/meetings/upcoming.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    text = resp.text
    assert "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text
    assert "UID:ev-1@councilhound.net" in text
    assert "DTSTART;TZID=America/New_York:20260728T190000" in text
    assert "SUMMARY:City Council Meeting\\; special" in text  # escaped
    assert "BEGIN:VTIMEZONE" in text
