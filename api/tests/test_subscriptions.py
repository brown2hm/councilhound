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


def test_follow_member_body_area_and_briefing(db, client, monkeypatch):
    from councilhound.db.models import EntityAlias
    # the per-IP signup window is process-wide; this test alone needs a dozen
    monkeypatch.setattr("app.ratelimit.SUBSCRIBE_PER_HOUR", 100)
    mayor = Entity(entity_type="person", name="Catherine Read", canonical_slug="catherine-read")
    db.add(mayor)
    db.flush()
    db.add(EntityAlias(entity_id=mayor.id, alias="Mayor Read"))
    db.commit()

    def post(payload):
        return client.post("/subscriptions/", json={"email": "r@example.com", **payload})

    assert post({"kind": "member", "entity_slug": "catherine-read"}).status_code == 200
    # a person can't be followed as a topic, and vice versa
    assert post({"kind": "topic", "entity_slug": "catherine-read"}).status_code == 422
    assert post({"kind": "body", "body": "school_board"}).status_code == 422
    assert post({"kind": "body", "body": "planning_commission"}).status_code == 200
    assert post({"kind": "area", "lat": 38.8462, "lng": -77.3064}).status_code == 422
    assert post({"kind": "area", "lat": 38.8462, "lng": -77.3064, "radius_m": 20,
                 "label": "near Old Town"}).status_code == 200
    assert post({"kind": "briefing"}).status_code == 200
    assert post({"kind": "weather"}).status_code == 422

    subs = {s.kind: s for s in db.query(TopicSubscription).all()}
    assert set(subs) == {"member", "body", "area", "briefing"}
    assert subs["member"].entity_id == mayor.id
    assert subs["area"].radius_m == 100  # clamped to the minimum
    assert subs["area"].label == "near Old Town"

    # confirm/unsubscribe pages describe the thing followed
    resp = client.get(f"/subscriptions/confirm?token={subs['area'].token}")
    assert "near Old Town" in resp.text
    db.refresh(subs["area"])
    assert subs["area"].confirmed
    # confirming again reports already-following rather than a duplicate row
    dup = post({"kind": "area", "lat": 38.8462, "lng": -77.3064, "radius_m": 100})
    assert dup.json()["status"] == "already-following"
    resp = client.get(f"/subscriptions/unsubscribe?token={subs['body'].token}")
    assert "Planning Commission meetings" in resp.text
