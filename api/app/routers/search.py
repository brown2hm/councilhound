"""Hybrid transcript/agenda search: exact-phrase keyword hits (ILIKE,
trigram-indexed) ranked by recency, plus pgvector semantic hits for
paraphrases. Everything links back to the meeting and, where a timestamp
exists, the video moment. No LLM involved — this endpoint stays unlimited."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import AgendaItem, Meeting, TranscriptChunk
from councilhound.embeddings.embed import embed_query

from app.db import db_session
from app.links import clip_link

router = APIRouter()

KEYWORD_LIMIT = 20
SEMANTIC_LIMIT = 8
# cosine distance beyond this reads as "not actually about that"
SEMANTIC_MAX_DISTANCE = 0.55


def _chunk_result(chunk: TranscriptChunk, meeting: Meeting, match: str) -> dict:
    return {
        "kind": "transcript",
        "match": match,
        "meeting_id": meeting.id,
        "meeting_title": meeting.title,
        "body": meeting.body,
        "date": meeting.meeting_date.isoformat(),
        "text": chunk.text,
        "start_seconds": float(chunk.start_seconds) if chunk.start_seconds is not None else None,
        "watch_url": clip_link(meeting.granicus_view_id, meeting.granicus_clip_id,
                               float(chunk.start_seconds or 0)),
        "_key": ("chunk", chunk.id),
    }


def _item_result(item: AgendaItem, meeting: Meeting, match: str) -> dict:
    text = ". ".join(p for p in (item.title, item.outcome) if p)
    return {
        "kind": "agenda_item",
        "match": match,
        "meeting_id": meeting.id,
        "meeting_title": meeting.title,
        "body": meeting.body,
        "date": meeting.meeting_date.isoformat(),
        "item_label": item.label,
        "text": text,
        "start_seconds": float(item.start_seconds) if item.start_seconds is not None else None,
        "watch_url": clip_link(meeting.granicus_view_id, meeting.granicus_clip_id,
                               item.start_seconds) if item.start_seconds is not None else None,
        "_key": ("item", item.id),
    }


@router.get("/")
def search(
    q: str = Query(min_length=2, max_length=200),
    body: str | None = Query(None, description="city_council | planning_commission"),
    session: Session = Depends(db_session),
):
    needle = q.strip().lower()
    results: list[dict] = []
    seen: set = set()

    def add(res: dict) -> None:
        key = res.pop("_key")
        if key in seen:
            return
        seen.add(key)
        results.append(res)

    # exact-phrase keyword hits, newest first
    kq = (
        select(TranscriptChunk, Meeting)
        .join(Meeting, TranscriptChunk.meeting_id == Meeting.id)
        .where(func.lower(TranscriptChunk.text).contains(needle, autoescape=True))
        .order_by(Meeting.meeting_date.desc())
        .limit(KEYWORD_LIMIT)
    )
    iq = (
        select(AgendaItem, Meeting)
        .join(Meeting, AgendaItem.meeting_id == Meeting.id)
        .where(func.lower(func.coalesce(AgendaItem.title, "") + " "
                          + func.coalesce(AgendaItem.outcome, ""))
               .contains(needle, autoescape=True))
        .order_by(Meeting.meeting_date.desc())
        .limit(KEYWORD_LIMIT)
    )
    if body:
        kq = kq.where(Meeting.body == body)
        iq = iq.where(Meeting.body == body)
    for item, meeting in session.execute(iq):
        add(_item_result(item, meeting, "keyword"))
    for chunk, meeting in session.execute(kq):
        add(_chunk_result(chunk, meeting, "keyword"))

    # semantic hits for paraphrases the exact phrase misses
    vec = embed_query(q)
    sq = (
        select(TranscriptChunk, Meeting,
               TranscriptChunk.embedding.cosine_distance(vec).label("d"))
        .join(Meeting, TranscriptChunk.meeting_id == Meeting.id)
        .where(TranscriptChunk.embedding.isnot(None))
        .order_by("d")
        .limit(SEMANTIC_LIMIT)
    )
    if body:
        sq = sq.where(Meeting.body == body)
    for chunk, meeting, dist in session.execute(sq):
        if float(dist) <= SEMANTIC_MAX_DISTANCE:
            add(_chunk_result(chunk, meeting, "semantic"))

    return {"query": q, "results": results}
