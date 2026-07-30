"""Public freshness surface.

Everything else the API serves is the *content* of the record; this is the
record's own state. Without it a visitor can't tell "the council didn't meet"
from "ingestion has been broken for a week" — the two look identical on a
machine-generated site, and only one of them means the page is trustworthy.

Reads `ingest_runs`, which the pipeline already writes per phase-1 pass and
which nothing has ever read back.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    Entity, IngestRun, Meeting, TranscriptChunk, UpcomingMeeting,
)

from app.db import db_session

router = APIRouter()


@router.get("/")
def get_status(session: Session = Depends(db_session)):
    run = session.scalar(
        select(IngestRun).order_by(IngestRun.started_at.desc()).limit(1)
    )
    latest = session.scalar(
        select(Meeting).order_by(Meeting.meeting_date.desc()).limit(1)
    )
    next_up = session.scalar(
        select(UpcomingMeeting)
        .where(UpcomingMeeting.starts_at.isnot(None))
        .order_by(UpcomingMeeting.starts_at.asc())
        .limit(1)
    )

    errors = list(run.errors or []) if run else []
    return {
        "last_run": {
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "phase": run.phase,
            "meetings_processed": run.meetings_processed or 0,
            "error_count": len(errors),
            # a run that never wrote finished_at died mid-pass
            "ok": run.finished_at is not None and not errors,
        } if run else None,
        "latest_meeting": {
            "id": latest.id,
            "date": latest.meeting_date.isoformat(),
            "title": latest.title,
            "body": latest.body,
        } if latest else None,
        "next_meeting": {
            "event_id": next_up.granicus_event_id,
            "title": next_up.title,
            "starts_at": next_up.starts_at.isoformat(),
        } if next_up else None,
        "counts": {
            "meetings": session.scalar(select(func.count(Meeting.id))) or 0,
            "meetings_transcribed": session.scalar(
                select(func.count(distinct(TranscriptChunk.meeting_id)))
            ) or 0,
            "topics": session.scalar(
                select(func.count(Entity.id)).where(Entity.entity_type != "person")
            ) or 0,
        },
    }
