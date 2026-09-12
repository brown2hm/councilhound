"""Nightly topic-digest notifier: watermark advance only on successful send,
one digest per subscriber, and subscription carry-over through merges."""
from councilhound.db.models import Entity, EntityUpdate, Meeting, TopicSubscription
from councilhound import notify
from councilhound.dedupe import merge_entities
from councilhound.entities import resolve_entity


def _meeting(s, day):
    m = Meeting(granicus_view_id="13", granicus_clip_id=f"n{day}", body="city_council",
                meeting_type="council_meeting", title="City Council Meeting",
                meeting_date=f"2026-02-{day:02d}")
    s.add(m)
    s.flush()
    return m


def _subscribed_entity(s, name, email, confirmed=True):
    e = resolve_entity(s, "project", name)
    sub = TopicSubscription(email=email, entity_id=e.id, token=f"tok-{e.id}-{email}",
                            confirmed=confirmed, last_update_id=0)
    s.add(sub)
    s.flush()
    return e, sub


def test_notify_sends_one_digest_and_advances_watermark(db_session, monkeypatch):
    s = db_session
    m = _meeting(s, 1)
    trail, sub = _subscribed_entity(s, "George Snyder Trail", "a@example.com")
    plaza, sub2 = _subscribed_entity(s, "Courthouse Plaza", "a@example.com")
    u1 = EntityUpdate(entity_id=trail.id, meeting_id=m.id, update_text="cancelled")
    u2 = EntityUpdate(entity_id=plaza.id, meeting_id=m.id, update_text="phase 1 approved")
    s.add_all([u1, u2])
    s.flush()

    outbox = []
    monkeypatch.setattr(notify, "send_email",
                        lambda to, subject, text, html=None: outbox.append((to, subject, text)) or True)

    result = notify.notify_subscribers(s)
    assert result == {"emails_sent": 1, "subscriptions_caught_up": 2}
    to, subject, text = outbox[0]
    assert to == "a@example.com"
    assert "2 topics" in subject
    assert "cancelled" in text and "phase 1 approved" in text
    assert "unsubscribe?token=" in text
    assert sub.last_update_id == u1.id and sub2.last_update_id == u2.id

    # nothing new -> nothing sent
    outbox.clear()
    assert notify.notify_subscribers(s)["emails_sent"] == 0


def test_notify_keeps_watermark_on_send_failure_and_skips_unconfirmed(db_session, monkeypatch):
    s = db_session
    m = _meeting(s, 2)
    trail, sub = _subscribed_entity(s, "George Snyder Trail", "a@example.com")
    _, pending = _subscribed_entity(s, "Courthouse Plaza", "b@example.com", confirmed=False)
    s.add(EntityUpdate(entity_id=trail.id, meeting_id=m.id, update_text="news"))
    s.flush()

    monkeypatch.setattr(notify, "send_email", lambda *a, **k: False)
    result = notify.notify_subscribers(s)
    assert result["emails_sent"] == 0
    assert sub.last_update_id == 0  # unsent news goes out tomorrow instead
    assert pending.last_update_id == 0


def test_merge_carries_subscriptions_to_survivor(db_session):
    s = db_session
    target, t_sub = _subscribed_entity(s, "Davies Property", "a@example.com")
    source, s_sub = _subscribed_entity(s, "Davies Proposal", "b@example.com")
    # a@ follows both: the duplicate row must collapse, not violate unique
    s.add(TopicSubscription(email="a@example.com", entity_id=source.id,
                            token="tok-dup", confirmed=True, last_update_id=0))
    s.flush()

    merge_entities(s, source.canonical_slug, target.canonical_slug)
    s.commit()

    subs = s.query(TopicSubscription).all()
    assert {(x.email, x.entity_id) for x in subs} == {
        ("a@example.com", target.id), ("b@example.com", target.id)}


# --- the broadened follows: member, body, area, weekly briefing -------------
import datetime

from councilhound.db.models import AgendaItem, CityProject, UpcomingMeeting, Vote


def _follow(s, email, **kw):
    sub = TopicSubscription(email=email, token=f"tok-{email}-{kw.get('kind')}-{len(s.new)}",
                            confirmed=True, last_update_id=0, **kw)
    s.add(sub)
    s.flush()
    return sub


def _capture(monkeypatch):
    outbox = []
    monkeypatch.setattr(notify, "send_email",
                        lambda to, subject, text, html=None: outbox.append((to, subject, text)) or True)
    return outbox


def test_member_follow_digests_their_votes_only(db_session, monkeypatch):
    s = db_session
    m = _meeting(s, 3)
    mayor = resolve_entity(s, "person", "Catherine Read")
    item = AgendaItem(meeting_id=m.id, label="8", title="Adopt the budget", start_seconds=900)
    s.add(item)
    s.flush()
    s.add(Vote(meeting_id=m.id, agenda_item_id=item.id, description="Adopt",
               motion_result="passed", vote_breakdown={"Read": "yes", "Bates": "no"}))
    s.add(Vote(meeting_id=m.id, description="Adjourn", motion_result="passed",
               vote_breakdown={"Bates": "yes"}))  # the mayor didn't vote: not news
    s.flush()
    sub = _follow(s, "a@example.com", kind="member", entity_id=mayor.id)
    outbox = _capture(monkeypatch)

    assert notify.notify_subscribers(s)["emails_sent"] == 1
    to, subject, text = outbox[0]
    assert subject == "CouncilHound: news on Catherine Read"
    assert "voted YES on Adopt the budget (motion passed)" in text
    assert "Adjourn" not in text
    assert "entrytime=900" in text and "/members/catherine-read" in text
    assert sub.last_vote_id == s.query(Vote).order_by(Vote.id.desc()).first().id
    outbox.clear()
    assert notify.notify_subscribers(s)["emails_sent"] == 0


def test_body_and_area_follows(db_session, monkeypatch):
    s = db_session
    council = _meeting(s, 4)
    pc = Meeting(granicus_view_id="13", granicus_clip_id="pc4", body="planning_commission",
                 meeting_type="planning_commission", title="Planning Commission",
                 meeting_date="2026-02-05")
    s.add(pc)
    s.flush()
    trail = resolve_entity(s, "project", "George Snyder Trail")
    homes = resolve_entity(s, "project", "Willard Way Townhomes")
    s.add(CityProject(external_slug="willard", entity_id=homes.id, name="Willard Way Townhomes",
                      detail_url="https://example.gov", lat=38.8462, lng=-77.3064))
    s.add_all([
        EntityUpdate(entity_id=trail.id, meeting_id=council.id, update_text="trail news"),
        EntityUpdate(entity_id=homes.id, meeting_id=pc.id, update_text="homes recommended"),
    ])
    s.flush()
    body_sub = _follow(s, "b@example.com", kind="body", body="planning_commission")
    near_sub = _follow(s, "n@example.com", kind="area", lat=38.8465, lng=-77.3060,
                       radius_m=400, label="near Old Town")
    far_sub = _follow(s, "f@example.com", kind="area", lat=38.9, lng=-77.4, radius_m=400,
                      label="far away")
    outbox = _capture(monkeypatch)

    result = notify.notify_subscribers(s)
    assert result["emails_sent"] == 2
    by_to = {to: text for to, _subject, text in outbox}
    assert "homes recommended" in by_to["b@example.com"]
    assert "trail news" not in by_to["b@example.com"]  # council, not commission
    assert "Willard Way Townhomes: homes recommended" in by_to["n@example.com"]
    assert "near Old Town" in by_to["n@example.com"]
    assert "f@example.com" not in by_to
    # every watermark advanced — the far follow too, so it doesn't rescan
    high = s.query(EntityUpdate).order_by(EntityUpdate.id.desc()).first().id
    assert body_sub.last_update_id == near_sub.last_update_id == far_sub.last_update_id == high


def test_weekly_briefing_cadence(db_session, monkeypatch):
    s = db_session
    now = datetime.datetime(2026, 2, 10, 8, 0, tzinfo=datetime.timezone.utc)
    m = _meeting(s, 8)
    trail = resolve_entity(s, "project", "George Snyder Trail")
    item = AgendaItem(meeting_id=m.id, label="5", title="Trail phase 2", start_seconds=100)
    s.add(item)
    s.flush()
    s.add(Vote(meeting_id=m.id, agenda_item_id=item.id, motion_result="passed",
               vote_breakdown={"Read": "yes", "Bates": "yes", "Lim": "no"}))
    s.add(EntityUpdate(entity_id=trail.id, meeting_id=m.id, agenda_item_id=item.id,
                       update_text="Phase 2 funded.", status_after="approved"))
    s.add(UpcomingMeeting(granicus_event_id="ev-9", granicus_view_id="13",
                          title="City Council Meeting", body="city_council",
                          starts_at=datetime.datetime(2026, 2, 12, 19, 0)))
    s.flush()
    sub = _follow(s, "w@example.com", kind="briefing")
    outbox = _capture(monkeypatch)

    assert notify.notify_subscribers(s, now=now)["emails_sent"] == 1
    to, subject, text = outbox[0]
    assert subject == "CouncilHound: your weekly City of Fairfax briefing"
    assert "City Council passed 2–1: Trail phase 2" in text
    assert "New topic: George Snyder Trail" in text
    assert "Coming up: City Council Meeting" in text
    assert sub.last_sent_at == now

    # not again tomorrow, even with the same news in the window
    outbox.clear()
    assert notify.notify_subscribers(s, now=now + datetime.timedelta(days=1))["emails_sent"] == 0
    # a week later with a quiet record: nothing goes out, cadence carries over
    later = now + datetime.timedelta(days=8)
    monkeypatch.setattr(notify, "recent_changes", lambda *a, **k: [])
    s.query(Vote).delete()
    s.flush()
    assert notify.notify_subscribers(s, now=later)["emails_sent"] == 0
    assert sub.last_sent_at == now
