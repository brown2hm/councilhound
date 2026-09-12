"""Hybrid transcript/agenda search: exact-phrase keyword hits (ILIKE,
trigram-indexed) ranked by recency, plus pgvector semantic hits for
paraphrases. Everything links back to the meeting and, where a timestamp
exists, the video moment. No LLM involved — this endpoint stays unlimited."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from councilhound.db.models import AgendaItem, Entity, EntityAlias, EntityUpdate, Meeting, TranscriptChunk
from councilhound.embeddings.embed import embed_query

from app.db import db_session
from app.links import clip_link

router = APIRouter()

KEYWORD_LIMIT = 20
SEMANTIC_LIMIT = 8
ENTITY_LIMIT = 6
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

    # tracked topics whose name/alias matches: the thing most searches are
    # really looking for, so they lead the page rather than hiding among
    # transcript fragments
    update_counts = (
        select(EntityUpdate.entity_id, func.count().label("n"),
               func.max(Meeting.meeting_date).label("last_date"))
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .group_by(EntityUpdate.entity_id)
        .subquery()
    )
    eq = (
        select(Entity, update_counts.c.n, update_counts.c.last_date)
        .join(update_counts, Entity.id == update_counts.c.entity_id)
        .where(Entity.entity_type != "person",
               or_(Entity.name.ilike(f"%{needle}%"),
                   exists(select(EntityAlias.id).where(
                       EntityAlias.entity_id == Entity.id,
                       EntityAlias.alias.ilike(f"%{needle}%")))))
        .order_by(update_counts.c.n.desc(), update_counts.c.last_date.desc())
        .limit(ENTITY_LIMIT)
    )
    if body:
        eq = eq.where(exists(
            select(EntityUpdate.id).join(Meeting, EntityUpdate.meeting_id == Meeting.id)
            .where(EntityUpdate.entity_id == Entity.id, Meeting.body == body)))
    entities = [
        {"slug": e.canonical_slug, "name": e.name, "entity_type": e.entity_type,
         "current_status": e.current_status, "update_count": n,
         "last_seen": last.isoformat() if last else None}
        for e, n, last in session.execute(eq)
    ]

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

    return {"query": q, "entities": entities, "results": results}
