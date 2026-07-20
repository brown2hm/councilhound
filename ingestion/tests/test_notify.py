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
