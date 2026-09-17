"""Meetings: list/filter for the timeline view, detail (agenda items, votes,
documents) for the meeting page."""
import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    AgendaItem, CityProject, Document, Entity, EntityAlias, EntityMention,
    EntityUpdate, Meeting, ProjectEvaluation, TranscriptChunk, UpcomingMeeting, Vote,
)
from councilhound.hot_topics import MIN_VARIANT_LEN

from app.db import db_session
from app.links import clip_link

router = APIRouter()


@router.get("/")
def list_meetings(
    body: str | None = Query(None, description="body key: city_council, planning_commission, school_board, prab, hhcab"),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    include_decisions: bool = Query(False, description="attach each meeting's votes and discussed items (the /meetings list page)"),
    session: Session = Depends(db_session),
):
    q = select(Meeting).order_by(Meeting.meeting_date.desc())
    if body:
        q = q.where(Meeting.body == body)
    if date_from:
        q = q.where(Meeting.meeting_date >= date_from)
    if date_to:
        q = q.where(Meeting.meeting_date <= date_to)
    meetings = session.scalars(q.limit(limit).offset(offset)).all()

    item_counts = dict(session.execute(
        select(AgendaItem.meeting_id, func.count()).group_by(AgendaItem.meeting_id)
    ).all())
    decisions = _decisions([m.id for m in meetings], session) if include_decisions else {}
    return [
        {
            "id": m.id,
            "date": m.meeting_date.isoformat(),
            "title": m.title,
            "body": m.body,
            "meeting_type": m.meeting_type,
            "status": m.status,
            "duration_seconds": m.duration_seconds,
            "agenda_item_count": item_counts.get(m.id, 0),
            **decisions.get(m.id, _NO_DECISIONS if include_decisions else {}),
        }
        for m in meetings
    ]


# housekeeping items never make the list page: minutes, the agenda itself,
# remote-participation approvals, roll calls, adjournment
_PROCEDURAL = re.compile(
    r"\b(minutes|remote participation|adoption of (the )?agenda|adjourn|roll call)\b|call .*to order",
    re.I)
_NO_DECISIONS = {"decisions": [], "discussed": [], "votes_passed": 0, "votes_failed": 0}


def _decisions(meeting_ids: list[int], session: Session) -> dict[int, dict]:
    """Per meeting: every substantive vote (label, title, result) in agenda
    order, the items discussed without a vote, and the pass/fail tally."""
    if not meeting_ids:
        return {}
    items = session.execute(
        select(AgendaItem.id, AgendaItem.meeting_id, AgendaItem.label, AgendaItem.title)
        .where(AgendaItem.meeting_id.in_(meeting_ids))
        .order_by(AgendaItem.meeting_id, AgendaItem.id)).all()
    votes = session.execute(
        select(Vote.meeting_id, Vote.agenda_item_id, Vote.motion_result, Vote.description)
        .where(Vote.meeting_id.in_(meeting_ids))
        .order_by(Vote.id)).all()
    first_vote: dict[int, tuple] = {}
    loose: dict[int, list] = {}
    for mid, item_id, result, desc in votes:
        if item_id is not None:
            first_vote.setdefault(item_id, (result, desc))
        else:
            loose.setdefault(mid, []).append((result, desc))
    out: dict[int, dict] = {}
    for item_id, mid, label, title in items:
        d = out.setdefault(mid, {"decisions": [], "discussed": [], "votes_passed": 0, "votes_failed": 0})
        if _PROCEDURAL.search(title or ""):
            continue
        if item_id in first_vote:
            result, desc = first_vote[item_id]
            d["decisions"].append({"label": label, "title": title or desc or "", "result": result})
            if result == "passed":
                d["votes_passed"] += 1
            elif result == "failed":
                d["votes_failed"] += 1
        elif title:
            d["discussed"].append(title)
    for mid, rows in loose.items():
        d = out.setdefault(mid, {"decisions": [], "discussed": [], "votes_passed": 0, "votes_failed": 0})
        for result, desc in rows:
            if not desc or _PROCEDURAL.search(desc):
                continue
            d["decisions"].append({"label": None, "title": desc, "result": result})
            if result == "passed":
                d["votes_passed"] += 1
            elif result == "failed":
                d["votes_failed"] += 1
    return out


@router.get("/upcoming")
def list_upcoming(session: Session = Depends(db_session)):
    """Upcoming and in-progress events, soonest first (live events lead)."""
    rows = session.scalars(
        select(UpcomingMeeting)
        .order_by(UpcomingMeeting.in_progress.desc(),
                  UpcomingMeeting.starts_at.asc().nulls_last())
    ).all()
    return [
        {
            "event_id": u.granicus_event_id,
            "title": u.title,
            "body": u.body,
            "starts_at": u.starts_at.isoformat() if u.starts_at else None,
            "in_progress": u.in_progress,
            "agenda_url": u.agenda_url,
        }
        for u in rows
    ]


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


# Static VTIMEZONE for the city's zone so TZID references are self-contained.
_VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""


@router.get("/upcoming.ics")
def upcoming_calendar(session: Session = Depends(db_session)):
    """Upcoming meetings as an iCalendar feed — subscribe from any calendar
    app to keep the city's meeting schedule on your own calendar."""
    from fastapi.responses import Response

    rows = session.scalars(
        select(UpcomingMeeting)
        .where(UpcomingMeeting.starts_at.isnot(None))
        .order_by(UpcomingMeeting.starts_at)
    ).all()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CouncilHound//City of Fairfax meetings//EN",
        "X-WR-CALNAME:City of Fairfax meetings (CouncilHound)",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        _VTIMEZONE,
    ]
    for u in rows:
        start = u.starts_at.strftime("%Y%m%dT%H%M%S")
        end = (u.starts_at + datetime.timedelta(hours=2)).strftime("%Y%m%dT%H%M%S")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{u.granicus_event_id}@councilhound.net",
            f"DTSTAMP:{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;TZID=America/New_York:{start}",
            f"DTEND;TZID=America/New_York:{end}",
            f"SUMMARY:{_ics_escape(u.title)}",
        ]
        if u.agenda_url:
            lines.append(f"DESCRIPTION:Agenda: {_ics_escape(u.agenda_url)}")
            lines.append(f"URL:{_ics_escape(u.agenda_url)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar",
                    headers={"Content-Disposition": 'inline; filename="councilhound.ics"',
                             "Cache-Control": "public, max-age=3600"})


def _agenda_context(agenda_text: str, variant: str) -> str | None:
    """A ~200-char excerpt of the agenda centered on the entity's name.
    PDF extraction often yields one enormous line, so trimming from the
    line start would show header boilerplate instead of the actual item."""
    for line in agenda_text.splitlines():
        low = line.lower()
        pos = low.find(variant)
        if pos < 0:
            continue
        start = max(0, pos - 80)
        end = min(len(line), pos + len(variant) + 120)
        excerpt = " ".join(line[start:end].split())
        return (("…" if start > 0 else "") + excerpt
                + ("…" if end < len(line) else ""))
    return None


# top-level agenda items: "8. Public hearings." — numbered, in order
_ITEM_RE = re.compile(r"(?<![\d$:.,/-])(\d{1,2})\.\s+(?=[A-Za-z(])")


def _hearing_spans(text_low: str) -> list[tuple[int, int]]:
    """Character ranges of the agenda's public-hearing sections: from a
    top-level item whose heading names a public hearing to the next one.
    Item numbers must climb so stray numbers in the body text ("3
    minutes", "2.12 acres") don't open a section."""
    starts: list[int] = []
    last = 0
    for m in _ITEM_RE.finditer(text_low):
        if int(m.group(1)) > last:
            starts.append(m.start())
            last = int(m.group(1))
    if len(starts) < 3:
        return []
    spans = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text_low)
        if "public hearing" in text_low[s:min(e, s + 80)]:
            spans.append((s, e))
    return spans


def _is_hearing(text_low: str, pos: int, spans: list[tuple[int, int]]) -> bool:
    """Whether the name at `pos` sits inside a public-hearing section. Agendas
    without a numbered outline fall back to the line: a hearing if the words
    come earlier on the same line."""
    if spans:
        return any(s <= pos < e for s, e in spans)
    line_start = text_low.rfind("\n", 0, pos) + 1
    return "public hearing" in text_low[line_start:pos]


@router.get("/upcoming/{event_id}")
def upcoming_detail(event_id: str, session: Session = Depends(db_session)):
    """One upcoming meeting, annotated: every tracked topic named in its
    fetched agenda, with status, history stats, and the agenda line that
    names it — the pre-meeting brief."""
    u = session.scalar(select(UpcomingMeeting)
                       .where(UpcomingMeeting.granicus_event_id == event_id))
    if u is None:
        raise HTTPException(404, "upcoming meeting not found")

    topics = []
    if u.agenda_text:
        text_low = u.agenda_text.lower()
        hearing_spans = _hearing_spans(text_low)

        counts = (
            select(EntityUpdate.entity_id, func.count().label("n"),
                   func.max(Meeting.meeting_date).label("last_date"))
            .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
            .group_by(EntityUpdate.entity_id)
            .subquery()
        )
        tracked = session.execute(
            select(Entity, counts.c.n, counts.c.last_date)
            .join(counts, Entity.id == counts.c.entity_id)
            .where(Entity.entity_type != "person")
        ).all()
        aliases: dict[int, list[str]] = {}
        for a in session.scalars(select(EntityAlias).where(
                EntityAlias.entity_id.in_([e.id for e, _, _ in tracked]))):
            aliases.setdefault(a.entity_id, []).append(a.alias)

        for entity, n, last_date in tracked:
            variants = {v.lower() for v in [entity.name, *aliases.get(entity.id, [])]
                        if v and len(v) >= MIN_VARIANT_LEN}
            hit = next((v for v in sorted(variants, key=len, reverse=True)
                        if v in text_low), None)
            if hit is None:
                continue
            latest = session.execute(
                select(EntityUpdate, Meeting)
                .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
                .where(EntityUpdate.entity_id == entity.id)
                .order_by(Meeting.meeting_date.desc())
                .limit(1)
            ).first()
            project_row = session.execute(
                select(CityProject, ProjectEvaluation.status)
                .outerjoin(ProjectEvaluation,
                           ProjectEvaluation.city_project_id == CityProject.id)
                .where(CityProject.entity_id == entity.id)
            ).first()
            topics.append({
                "slug": entity.canonical_slug,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "current_status": entity.current_status,
                "update_count": n,
                "last_seen": last_date.isoformat() if last_date else None,
                "agenda_context": _agenda_context(u.agenda_text, hit),
                "hearing": _is_hearing(text_low, text_low.find(hit), hearing_spans),
                "latest_update": {
                    "date": str(latest[1].meeting_date),
                    "text": latest[0].update_text,
                } if latest else None,
                "evaluation_slug": (project_row[0].external_slug
                                    if project_row and project_row[1] == "synthesized"
                                    else None),
            })
        topics.sort(key=lambda t: t["update_count"], reverse=True)

    return {
        "event_id": u.granicus_event_id,
        "title": u.title,
        "body": u.body,
        "starts_at": u.starts_at.isoformat() if u.starts_at else None,
        "in_progress": u.in_progress,
        "agenda_url": u.agenda_url,
        "has_agenda_text": bool(u.agenda_text),
        "topics": topics,
    }


@router.get("/stats")
def get_stats(
    days: int = Query(30, ge=7, le=365),
    session: Session = Depends(db_session),
):
    """Aggregate counts for the briefing stat tiles."""
    since = datetime.date.today() - datetime.timedelta(days=days)
    meetings_held = session.scalar(
        select(func.count(Meeting.id)).where(Meeting.meeting_date >= since)) or 0
    hours = session.scalar(
        select(func.coalesce(func.sum(Meeting.duration_seconds), 0))
        .where(Meeting.meeting_date >= since)) or 0
    vote_rows = session.execute(
        select(Vote.motion_result, func.count())
        .join(Meeting, Vote.meeting_id == Meeting.id)
        .where(Meeting.meeting_date >= since)
        .group_by(Vote.motion_result)
    ).all()
    by_result = {r or "other": n for r, n in vote_rows}
    return {
        "days": days,
        "meetings_held": meetings_held,
        "hours_of_meetings": round(hours / 3600, 1),
        "votes_taken": sum(by_result.values()),
        "motions_passed": by_result.get("passed", 0),
        "motions_failed": by_result.get("failed", 0),
    }


@router.get("/{meeting_id}")
def get_meeting(meeting_id: int, session: Session = Depends(db_session)):
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "meeting not found")

    items = session.scalars(
        select(AgendaItem).where(AgendaItem.meeting_id == meeting.id).order_by(AgendaItem.id)
    ).all()
    votes_by_item: dict[int, list] = {}
    for vote in session.scalars(select(Vote).where(Vote.meeting_id == meeting.id)):
        votes_by_item.setdefault(vote.agenda_item_id, []).append({
            "description": vote.description,
            "motion_result": vote.motion_result,
            "vote_breakdown": vote.vote_breakdown,
        })
    documents = session.scalars(
        select(Document).where(Document.meeting_id == meeting.id).order_by(Document.id)
    ).all()
    docs_by_item: dict[int | None, list] = {}
    for d in documents:
        docs_by_item.setdefault(d.agenda_item_id, []).append({
            "doc_type": d.doc_type,
            "title": d.title,
            "source_url": d.source_url,
            "agenda_item_id": d.agenda_item_id,
        })

    # the topics each agenda item touches: tracked updates first, then bare
    # mentions, so a reader can jump from the meeting to a project's history
    # (the topic -> meeting link has always existed; this is the reverse)
    entities_by_item: dict[int | None, list] = {}
    seen_pairs: set[tuple[int | None, int]] = set()
    for item_id, entity, status_after in session.execute(
        select(EntityUpdate.agenda_item_id, Entity, EntityUpdate.status_after)
        .join(Entity, EntityUpdate.entity_id == Entity.id)
        .where(EntityUpdate.meeting_id == meeting.id,
               Entity.entity_type != "person")
        .order_by(EntityUpdate.id)
    ):
        if (item_id, entity.id) in seen_pairs:
            continue
        seen_pairs.add((item_id, entity.id))
        entities_by_item.setdefault(item_id, []).append({
            "slug": entity.canonical_slug,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "current_status": entity.current_status,
            "status_after": status_after,
        })
    for item_id, entity in session.execute(
        select(EntityMention.agenda_item_id, Entity)
        .join(Entity, EntityMention.entity_id == Entity.id)
        .where(EntityMention.meeting_id == meeting.id,
               EntityMention.agenda_item_id.isnot(None),
               Entity.entity_type != "person")
        .order_by(EntityMention.id)
    ):
        if (item_id, entity.id) in seen_pairs:
            continue
        seen_pairs.add((item_id, entity.id))
        entities_by_item.setdefault(item_id, []).append({
            "slug": entity.canonical_slug,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "current_status": entity.current_status,
            "status_after": None,
        })

    return {
        "id": meeting.id,
        "date": meeting.meeting_date.isoformat(),
        "title": meeting.title,
        "body": meeting.body,
        "meeting_type": meeting.meeting_type,
        "granicus_clip_id": meeting.granicus_clip_id,
        "duration_seconds": meeting.duration_seconds,
        "video_url": meeting.video_url,
        "agenda_url": meeting.agenda_url,
        "minutes_url": meeting.minutes_url,
        "agenda_items": [
            {
                "id": it.id,
                "label": it.label,
                "title": it.title,
                "description": it.description,
                "outcome": it.outcome,
                "start_seconds": it.start_seconds,
                "watch_url": clip_link(meeting.granicus_view_id, meeting.granicus_clip_id,
                                       it.start_seconds) if it.start_seconds is not None else None,
                "votes": votes_by_item.get(it.id, []),
                "entities": entities_by_item.get(it.id, []),
                "documents": docs_by_item.get(it.id, []),
            }
            for it in items
        ],
        "documents": [d for docs in docs_by_item.values() for d in docs],
        # matters raised outside any numbered item (member comments, staff
        # reports, public comment) — on the meeting, not on an item
        "other_discussion": entities_by_item.get(None, []),
    }


@router.get("/{meeting_id}/transcript")
def get_transcript(meeting_id: int, session: Session = Depends(db_session)):
    """The whole timestamped transcript, in order.

    These chunks have always been in the database — they back /search and
    /ask — but they only ever escaped as ~700-char fragments, so there was no
    way to actually read a meeting. Every segment carries its own Granicus
    deep link, and the agenda items are returned alongside so the page can
    show where each item starts.
    """
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "meeting not found")

    chunks = session.scalars(
        select(TranscriptChunk)
        .where(TranscriptChunk.meeting_id == meeting.id)
        .order_by(TranscriptChunk.start_seconds.asc().nulls_last(), TranscriptChunk.id)
    ).all()

    items = session.scalars(
        select(AgendaItem)
        .where(AgendaItem.meeting_id == meeting.id,
               AgendaItem.start_seconds.isnot(None))
        .order_by(AgendaItem.start_seconds)
    ).all()

    def link(seconds) -> str | None:
        if seconds is None:
            return None
        return clip_link(meeting.granicus_view_id, meeting.granicus_clip_id, seconds)

    return {
        "id": meeting.id,
        "date": meeting.meeting_date.isoformat(),
        "title": meeting.title,
        "body": meeting.body,
        "video_url": meeting.video_url,
        "duration_seconds": meeting.duration_seconds,
        "segments": [
            {
                "id": c.id,
                "start_seconds": float(c.start_seconds) if c.start_seconds is not None else None,
                "end_seconds": float(c.end_seconds) if c.end_seconds is not None else None,
                "text": c.text,
                # populated once the diarization pass runs; null until then
                "speaker_label": c.speaker_label,
                "watch_url": link(c.start_seconds),
            }
            for c in chunks
        ],
        "agenda_items": [
            {
                "id": it.id,
                "label": it.label,
                "title": it.title,
                "start_seconds": float(it.start_seconds),
            }
            for it in items
        ],
    }
