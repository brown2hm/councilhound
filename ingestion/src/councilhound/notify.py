"""Nightly digest notifier. For every confirmed follow, collect what's new
since its watermark — entity updates for a topic, a member's votes, a body's
meetings, updates inside an area, or the week's changes for the briefing —
batch everything for one address into one email, and advance the watermarks
only after a successful send (an SMTP outage just means a bigger digest
tomorrow)."""
import datetime
import logging
import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.changes import recent_changes, status_words
from councilhound.config import API_BASE_URL, GRANICUS_BASE_URL, JURISDICTION, LOCAL_TZ, SITE_BASE_URL  # noqa: F401
from councilhound.db.models import (
    AgendaItem, CityProject, Entity, EntityGeocode, EntityUpdate, Meeting, TopicSubscription,
    UpcomingMeeting, Vote,
)
from councilhound.bodies import BODY_LABELS
from councilhound.mail import send_email
from councilhound.people import vote_cast_by

log = logging.getLogger(__name__)

_ID = JURISDICTION.identity

BRIEFING_EVERY = datetime.timedelta(days=7)
MAX_LINES_PER_SECTION = 40


def _watch(meeting: Meeting, item: AgendaItem | None) -> str | None:
    if item is None or item.start_seconds is None:
        return None
    return (f"{GRANICUS_BASE_URL}/MediaPlayer.php?view_id={meeting.granicus_view_id}"
            f"&clip_id={meeting.granicus_clip_id}&starttime={int(item.start_seconds)}"
            f"&entrytime={int(item.start_seconds)}")


def describe(session: Session, sub: TopicSubscription) -> tuple[str, str]:
    """(human name of what's followed, its page on the site)."""
    if sub.kind == "member":
        e = session.get(Entity, sub.entity_id)
        return e.name, f"{SITE_BASE_URL}/members/{e.canonical_slug}"
    if sub.kind == "body":
        return (f"{BODY_LABELS.get(sub.body, sub.body)} meetings",
                f"{SITE_BASE_URL}/meetings?body={sub.body}")
    if sub.kind == "area":
        return (sub.label or f"an area of the {_ID.noun}",
                f"{SITE_BASE_URL}/nearby?lat={sub.lat}&lng={sub.lng}&r={sub.radius_m}")
    if sub.kind == "briefing":
        return "the weekly briefing", SITE_BASE_URL
    e = session.get(Entity, sub.entity_id)
    return e.name, f"{SITE_BASE_URL}/topics/{e.canonical_slug}"


# A section is one followed thing's news: header + lines + how to advance
# the watermark once the email carrying it is sent.
class _Section:
    def __init__(self, sub, title, url, lines, commit):
        self.sub, self.title, self.url, self.lines, self.commit = sub, title, url, lines, commit


def _topic_section(session, sub) -> _Section | None:
    rows = session.execute(
        select(EntityUpdate, Meeting, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id == sub.entity_id,
               EntityUpdate.id > sub.last_update_id)
        .order_by(Meeting.meeting_date, EntityUpdate.id)
    ).all()
    if not rows:
        return None
    title, url = describe(session, sub)
    lines = [(str(m.meeting_date), upd.update_text, _watch(m, item)) for upd, m, item in rows]
    high = max(upd.id for upd, _, _ in rows)

    def commit():
        sub.last_update_id = high
    return _Section(sub, title, url, lines, commit)


def _member_section(session, sub) -> _Section | None:
    member = session.get(Entity, sub.entity_id)
    rows = session.execute(
        select(Vote, Meeting, AgendaItem)
        .join(Meeting, Vote.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, Vote.agenda_item_id == AgendaItem.id)
        .where(Vote.id > sub.last_vote_id)
        .order_by(Meeting.meeting_date, Vote.id)
    ).all()
    lines, high = [], sub.last_vote_id
    for vote, m, item in rows:
        high = max(high, vote.id)
        cast = vote_cast_by(vote.vote_breakdown, member.name)
        if cast is None:
            continue
        what = (item.title if item and item.title else vote.description) or "a motion"
        result = f" (motion {vote.motion_result})" if vote.motion_result else ""
        lines.append((str(m.meeting_date), f"voted {cast.upper()} on {what}{result}",
                      _watch(m, item)))
    if not lines:
        if high > sub.last_vote_id:
            sub.last_vote_id = high  # nothing to say; don't rescan these tomorrow
        return None
    title, url = describe(session, sub)

    def commit():
        sub.last_vote_id = high
    return _Section(sub, title, url, lines, commit)


def _body_section(session, sub) -> _Section | None:
    rows = session.execute(
        select(EntityUpdate, Meeting, Entity, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .join(Entity, EntityUpdate.entity_id == Entity.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(Meeting.body == sub.body, EntityUpdate.id > sub.last_update_id,
               Entity.entity_type != "person")
        .order_by(Meeting.meeting_date, EntityUpdate.id)
    ).all()
    if not rows:
        return None
    title, url = describe(session, sub)
    lines = [(str(m.meeting_date), f"{e.name}: {upd.update_text}", _watch(m, item))
             for upd, m, e, item in rows]
    high = max(upd.id for upd, _, _, _ in rows)

    def commit():
        sub.last_update_id = high
    return _Section(sub, title, url, lines, commit)


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def _area_section(session, sub) -> _Section | None:
    rows = session.execute(
        select(EntityUpdate, Meeting, Entity, AgendaItem, CityProject, EntityGeocode)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .join(Entity, EntityUpdate.entity_id == Entity.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .outerjoin(CityProject, CityProject.entity_id == Entity.id)
        .outerjoin(EntityGeocode, (EntityGeocode.entity_id == Entity.id)
                   & (EntityGeocode.status == "ok"))
        .where(EntityUpdate.id > sub.last_update_id, Entity.entity_type != "person")
        .order_by(Meeting.meeting_date, EntityUpdate.id)
    ).all()
    lines, high = [], sub.last_update_id
    for upd, m, e, item, cp, geo in rows:
        high = max(high, upd.id)
        lat = cp.lat if cp and cp.lat is not None else (geo.lat if geo else None)
        lng = cp.lng if cp and cp.lng is not None else (geo.lng if geo else None)
        if lat is None or lng is None:
            continue
        if _haversine_m(float(sub.lat), float(sub.lng), float(lat), float(lng)) > sub.radius_m:
            continue
        lines.append((str(m.meeting_date), f"{e.name}: {upd.update_text}", _watch(m, item)))
    if not lines:
        if high > sub.last_update_id:
            sub.last_update_id = high
        return None
    title, url = describe(session, sub)

    def commit():
        sub.last_update_id = high
    return _Section(sub, title, url, lines, commit)


def _briefing_section(session, sub, now: datetime.datetime) -> _Section | None:
    if sub.last_sent_at is not None and now - sub.last_sent_at < BRIEFING_EVERY:
        return None
    since = (now - BRIEFING_EVERY).date()
    lines = []
    for vote, m, item in session.execute(
        select(Vote, Meeting, AgendaItem)
        .join(Meeting, Vote.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, Vote.agenda_item_id == AgendaItem.id)
        .where(Meeting.meeting_date >= since)
        .order_by(Meeting.meeting_date.desc(), Vote.id)
    ):
        what = (item.title if item and item.title else vote.description) or "a motion"
        counts = list((vote.vote_breakdown or {}).values())
        tally = f" {counts.count('yes')}–{counts.count('no')}" if counts else ""
        lines.append((str(m.meeting_date),
                      f"{BODY_LABELS.get(m.body, m.body)} {vote.motion_result or 'voted'}{tally}: {what}",
                      _watch(m, item)))
    for c in recent_changes(session, 7, since=since):
        if c["kind"] == "new":
            text = f"New topic: {c['name']} — {c['update_text']}"
        else:
            text = (f"{c['name']}: {status_words(c['from_status'])} → "
                    f"{status_words(c['to_status'])} — {c['update_text']}")
        lines.append((c["date"], text, f"{SITE_BASE_URL}/topics/{c['slug']}"))
    if not lines:
        return None  # a quiet week sends nothing; the next one carries over
    for u in session.scalars(
        select(UpcomingMeeting)
        .where(UpcomingMeeting.starts_at.isnot(None),
               # starts_at is naive local time; compare in the jurisdiction's zone
               UpcomingMeeting.starts_at >= now.astimezone(LOCAL_TZ).replace(tzinfo=None),
               UpcomingMeeting.starts_at <= (now + BRIEFING_EVERY).astimezone(LOCAL_TZ).replace(tzinfo=None))
        .order_by(UpcomingMeeting.starts_at)
    ):
        lines.append((u.starts_at.strftime("%Y-%m-%d"), f"Coming up: {u.title}",
                      f"{SITE_BASE_URL}/meetings/upcoming/{u.granicus_event_id}"))
    title, url = describe(session, sub)

    def commit():
        sub.last_sent_at = now
    return _Section(sub, title, url, lines, commit)


def _section_for(session, sub, now) -> _Section | None:
    if sub.kind == "member":
        return _member_section(session, sub)
    if sub.kind == "body":
        return _body_section(session, sub)
    if sub.kind == "area":
        return _area_section(session, sub)
    if sub.kind == "briefing":
        return _briefing_section(session, sub, now)
    return _topic_section(session, sub)


def _render(sections: list[_Section]) -> tuple[str, str, str]:
    """(subject, text, html) for one address."""
    text_parts, html_parts = [], []
    for sec in sections:
        text_parts.append(f"\n{sec.title}\n{sec.url}")
        html_parts.append(
            f'<h3 style="margin:18px 0 6px"><a href="{sec.url}">{sec.title}</a></h3>')
        shown = sec.lines[:MAX_LINES_PER_SECTION]
        for date, body, link in shown:
            text_parts.append(f"  - [{date}] {body}" + (f" ({link})" if link else ""))
            html_parts.append(
                f'<p style="margin:4px 0"><strong>{date}</strong> — {body}'
                + (f' <a href="{link}">↗</a>' if link else "") + "</p>")
        if len(sec.lines) > len(shown):
            more = len(sec.lines) - len(shown)
            text_parts.append(f"  … and {more} more: {sec.url}")
            html_parts.append(f'<p style="margin:4px 0">… and <a href="{sec.url}">{more} more</a></p>')
        unsub = f"{API_BASE_URL}/subscriptions/unsubscribe?token={sec.sub.token}"
        text_parts.append(f"  (unfollow: {unsub})")
        html_parts.append(
            f'<p style="margin:4px 0;font-size:12px"><a href="{unsub}">Unfollow</a></p>')

    kinds = {sec.sub.kind for sec in sections}
    if kinds == {"briefing"}:
        subject = f"CouncilHound: your weekly {_ID.short_name} briefing"
    elif len(sections) == 1:
        subject = f"CouncilHound: news on {sections[0].title}"
    elif kinds == {"topic"}:
        subject = f"CouncilHound: news on {len(sections)} topics you follow"
    else:
        subject = f"CouncilHound: news on {len(sections)} things you follow"
    intro = (f"This week in {_ID.short_name} {_ID.record_phrase}:"
             if kinds == {"briefing"} else
             f"Things you follow on CouncilHound had new {_ID.activity_noun} activity:")
    text = (intro + "\n" + "\n".join(text_parts)
            + "\n\nSummaries are machine-generated — verify against the "
              "linked source documents.\n")
    html = (f"<p>{intro}</p>" + "".join(html_parts)
            + '<p style="font-size:12px;color:#666">Summaries are machine-'
              "generated — verify against the linked source documents.</p>")
    return subject, text, html


def notify_subscribers(session: Session, now: datetime.datetime | None = None) -> dict:
    """Returns {"emails_sent": n, "subscriptions_caught_up": n}."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    subs = session.scalars(
        select(TopicSubscription).where(TopicSubscription.confirmed.is_(True))
    ).all()

    by_email: dict[str, list[_Section]] = defaultdict(list)
    for sub in subs:
        section = _section_for(session, sub, now)
        if section:
            by_email[sub.email].append(section)

    sent = caught_up = 0
    for email, sections in by_email.items():
        subject, text, html = _render(sections)
        if send_email(email, subject, text, html):
            sent += 1
            for sec in sections:
                sec.commit()
                caught_up += 1
    session.commit()
    return {"emails_sent": sent, "subscriptions_caught_up": caught_up}
