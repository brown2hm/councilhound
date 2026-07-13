"""Entity/topic tracker: list trackable entities with their current status,
and per-entity timeline — the 'progress over time' view."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    AgendaItem, Entity, EntityAlias, EntityMention, EntityProfile, EntityUpdate,
    Meeting, Vote,
)
from councilhound.hot_topics import hot_topics

from app.db import db_session
from app.links import clip_link

router = APIRouter()


@router.get("/hot")
def get_hot_topics(
    days: int = Query(60, ge=7, le=730),
    body: str | None = Query(None, description="city_council | planning_commission"),
    top: int = Query(30, le=100),
    session: Session = Depends(db_session),
):
    """Topics ranked by named discussion time across transcribed meetings
    in the look-back window, optionally per body."""
    return hot_topics(session, days=days, body=body, top=top)


@router.get("/")
def list_entities(
    entity_type: str | None = Query(None, description="project | ordinance | resolution | case_number | topic | location | person"),
    status: str | None = None,
    q: str | None = Query(None, description="substring match on name"),
    limit: int = Query(50, le=200),
    session: Session = Depends(db_session),
):
    update_counts = (
        select(EntityUpdate.entity_id, func.count().label("n"),
               func.max(Meeting.meeting_date).label("last_date"))
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .group_by(EntityUpdate.entity_id)
        .subquery()
    )
    query = (
        select(Entity, update_counts.c.n, update_counts.c.last_date)
        .join(update_counts, Entity.id == update_counts.c.entity_id)
        .order_by(update_counts.c.last_date.desc(), update_counts.c.n.desc())
    )
    if entity_type:
        query = query.where(Entity.entity_type == entity_type)
    if status:
        query = query.where(Entity.current_status == status)
    if q:
        query = query.where(Entity.name.ilike(f"%{q}%"))

    rows = session.execute(query.limit(limit)).all()
    return [
        {
            "slug": e.canonical_slug,
            "name": e.name,
            "entity_type": e.entity_type,
            "current_status": e.current_status,
            "update_count": n,
            "last_seen": last.isoformat() if last else None,
        }
        for e, n, last in rows
    ]


def _related_entities(session: Session, entity: Entity, top: int = 6) -> list[dict]:
    """Non-person entities co-mentioned in the most shared meetings —
    'discussed alongside' navigation, and a soft net for near-duplicates."""
    other = select(EntityMention.entity_id, EntityMention.meeting_id).where(
        EntityMention.entity_id != entity.id).subquery()
    rows = session.execute(
        select(Entity, func.count(func.distinct(other.c.meeting_id)).label("shared"))
        .join(other, other.c.entity_id == Entity.id)
        .join(EntityMention, (EntityMention.meeting_id == other.c.meeting_id)
              & (EntityMention.entity_id == entity.id))
        .where(Entity.entity_type != "person")
        .group_by(Entity.id)
        .having(func.count(func.distinct(other.c.meeting_id)) >= 2)
        .order_by(func.count(func.distinct(other.c.meeting_id)).desc())
        .limit(top)
    ).all()
    return [
        {"slug": e.canonical_slug, "name": e.name, "entity_type": e.entity_type,
         "current_status": e.current_status, "shared_meetings": shared}
        for e, shared in rows
    ]


@router.get("/{slug}")
def get_entity(slug: str, session: Session = Depends(db_session)):
    entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
    if entity is None:
        # merged entities leave their old slug behind as an alias, so
        # bookmarked/indexed URLs keep resolving to the survivor
        entity = session.scalar(
            select(Entity).join(EntityAlias, EntityAlias.entity_id == Entity.id)
            .where(func.lower(EntityAlias.alias) == slug.lower())
        )
    if entity is None:
        raise HTTPException(404, "entity not found")

    timeline = session.execute(
        select(EntityUpdate, Meeting, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id == entity.id)
        .order_by(Meeting.meeting_date)
    ).all()

    # votes for every agenda item on the timeline, one query
    item_ids = [item.id for _, _, item in timeline if item is not None]
    votes_by_item: dict[int, list] = {}
    if item_ids:
        for v in session.scalars(select(Vote).where(Vote.agenda_item_id.in_(item_ids))):
            votes_by_item.setdefault(v.agenda_item_id, []).append({
                "description": v.description,
                "motion_result": v.motion_result,
                "vote_breakdown": v.vote_breakdown,
            })

    profile = session.scalar(
        select(EntityProfile).where(EntityProfile.entity_id == entity.id)
    )
    timeline_out = [
        {
            "date": m.meeting_date.isoformat(),
            "meeting_id": m.id,
            "meeting_title": m.title,
            "body": m.body,
            "agenda_item_label": item.label if item else None,
            "agenda_item_title": item.title if item else None,
            "update_text": u.update_text,
            "status_after": u.status_after,
            "agenda_url": m.agenda_url,
            "minutes_url": m.minutes_url,
            "watch_url": clip_link(m.granicus_view_id, m.granicus_clip_id, item.start_seconds)
            if item and item.start_seconds is not None else None,
            "votes": votes_by_item.get(item.id, []) if item else [],
        }
        for u, m, item in timeline
    ]
    # provenance: the most recent timeline entry that set a status
    status_source = next(
        (t for t in reversed(timeline_out) if t["status_after"]), None)

    return {
        "slug": entity.canonical_slug,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "current_status": entity.current_status,
        "status_source": {
            "date": status_source["date"],
            "meeting_id": status_source["meeting_id"],
            "meeting_title": status_source["meeting_title"],
            "watch_url": status_source["watch_url"],
        } if status_source else None,
        "profile": {
            "summary": profile.summary,
            "open_questions": profile.open_questions or [],
            "member_commentary": profile.member_commentary or [],
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        } if profile else None,
        "related": _related_entities(session, entity),
        "timeline": timeline_out,
    }
