"""Meetings: list/filter for the timeline view, detail (agenda items, votes,
documents) for the meeting page."""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import AgendaItem, Document, Meeting, Vote

from app.db import db_session
from app.links import clip_link

router = APIRouter()


@router.get("/")
def list_meetings(
    body: str | None = Query(None, description="city_council | planning_commission"),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
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
        }
        for m in meetings
    ]


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

    return {
        "id": meeting.id,
        "date": meeting.meeting_date.isoformat(),
        "title": meeting.title,
        "body": meeting.body,
        "meeting_type": meeting.meeting_type,
        "granicus_clip_id": meeting.granicus_clip_id,
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
            }
            for it in items
        ],
        "documents": [
            {"doc_type": d.doc_type, "title": d.title, "source_url": d.source_url}
            for d in documents
        ],
    }
