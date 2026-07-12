"""Entity/topic tracker: list trackable entities with their current status,
and per-entity timeline — the 'progress over time' view."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councillens.db.models import AgendaItem, Entity, EntityUpdate, Meeting

from app.db import db_session

router = APIRouter()


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


@router.get("/{slug}")
def get_entity(slug: str, session: Session = Depends(db_session)):
    entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
    if entity is None:
        raise HTTPException(404, "entity not found")

    timeline = session.execute(
        select(EntityUpdate, Meeting, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id == entity.id)
        .order_by(Meeting.meeting_date)
    ).all()

    return {
        "slug": entity.canonical_slug,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "current_status": entity.current_status,
        "timeline": [
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
            }
            for u, m, item in timeline
        ],
    }
