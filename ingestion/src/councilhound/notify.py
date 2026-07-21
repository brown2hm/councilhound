"""Nightly topic-digest notifier. For every confirmed subscription, collect
entity_updates newer than the subscription's watermark, batch them into one
email per subscriber, and advance the watermark only after a successful
send (an SMTP outage just means a bigger digest tomorrow)."""
import logging
import os
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, EntityUpdate, Meeting, TopicSubscription
from councilhound.mail import send_email

log = logging.getLogger(__name__)

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://councilhound.net")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.councilhound.net")


def _pending_updates(session: Session, sub: TopicSubscription):
    return session.execute(
        select(EntityUpdate, Meeting)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .where(EntityUpdate.entity_id == sub.entity_id,
               EntityUpdate.id > sub.last_update_id)
        .order_by(Meeting.meeting_date)
    ).all()


def notify_subscribers(session: Session) -> dict:
    """Returns {"emails_sent": n, "subscriptions_caught_up": n}."""
    subs = session.scalars(
        select(TopicSubscription).where(TopicSubscription.confirmed.is_(True))
    ).all()

    # one digest per subscriber, covering all their topics with news
    by_email: dict[str, list[tuple[TopicSubscription, list]]] = defaultdict(list)
    for sub in subs:
        rows = _pending_updates(session, sub)
        if rows:
            by_email[sub.email].append((sub, rows))

    sent = caught_up = 0
    for email, topics in by_email.items():
        text_parts: list[str] = []
        html_parts: list[str] = []
        for sub, rows in topics:
            entity = session.get(Entity, sub.entity_id)
            topic_url = f"{SITE_BASE_URL}/topics/{entity.canonical_slug}"
            text_parts.append(f"\n{entity.name}\n{topic_url}")
            html_parts.append(
                f'<h3 style="margin:18px 0 6px"><a href="{topic_url}">{entity.name}</a></h3>')
            for upd, meeting in rows:
                date = str(meeting.meeting_date)  # date object or ISO string
                text_parts.append(f"  - [{date}] {upd.update_text}")
                html_parts.append(
                    f'<p style="margin:4px 0"><strong>{date}</strong> — {upd.update_text}</p>')
            unsub = f"{API_BASE_URL}/subscriptions/unsubscribe?token={sub.token}"
            text_parts.append(f"  (unfollow this topic: {unsub})")
            html_parts.append(
                f'<p style="margin:4px 0;font-size:12px"><a href="{unsub}">Unfollow this topic</a></p>')

        n_topics = len(topics)
        first_name = session.get(Entity, topics[0][0].entity_id).name
        subject = (f"CouncilHound: news on {first_name}" if n_topics == 1
                   else f"CouncilHound: news on {n_topics} topics you follow")
        text = ("Topics you follow on CouncilHound had new council activity:\n"
                + "\n".join(text_parts)
                + "\n\nSummaries are machine-generated — verify against the "
                  "linked source documents.\n")
        html = ("<p>Topics you follow on CouncilHound had new council activity:</p>"
                + "".join(html_parts)
                + '<p style="font-size:12px;color:#666">Summaries are machine-'
                  "generated — verify against the linked source documents.</p>")
        if send_email(email, subject, text, html):
            sent += 1
            for sub, rows in topics:
                sub.last_update_id = max(upd.id for upd, _ in rows)
                caught_up += 1
    session.commit()
    return {"emails_sent": sent, "subscriptions_caught_up": caught_up}
