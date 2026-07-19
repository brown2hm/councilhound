"""Entity/topic tracker: list trackable entities with their current status,
and per-entity timeline — the 'progress over time' view."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    AgendaItem, CityProject, Entity, EntityAlias, EntityGeocode, EntityMention, EntityProfile,
    EntityUpdate, Meeting, UpcomingMeeting, Vote,
)
from councilhound.hot_topics import MIN_VARIANT_LEN
from councilhound.hot_topics import entity_discussion_series, hot_topics

from app.db import db_session
from app.links import clip_link
from app.wiki import wiki_payload

router = APIRouter()


def _resolve_entity(session: Session, slug: str) -> Entity | None:
    entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
    if entity is None:
        # merged entities leave their old slug behind as an alias, so
        # bookmarked/indexed URLs keep resolving to the survivor
        entity = session.scalar(
            select(Entity).join(EntityAlias, EntityAlias.entity_id == Entity.id)
            .where(func.lower(EntityAlias.alias) == slug.lower())
        )
    return entity


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


@router.get("/map")
def map_locations(session: Session = Depends(db_session)):
    """Geocoded location entities with their strongest co-mentioned topics —
    the map page's pins. Pin color follows the top related topic's status."""
    rows = session.execute(
        select(Entity, EntityGeocode, CityProject, EntityProfile)
        .join(EntityGeocode, EntityGeocode.entity_id == Entity.id)
        .outerjoin(CityProject, CityProject.entity_id == Entity.id)
        .outerjoin(EntityProfile, EntityProfile.entity_id == Entity.id)
        .where(EntityGeocode.status == "ok")
    ).all()
    out = []
    for entity, geo, city_project, profile in rows:
        related = [r for r in _related_entities(session, entity, top=4)
                   if r["entity_type"] != "location"][:3]
        out.append({
            "slug": entity.canonical_slug,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "is_official_project": city_project is not None,
            "lat": float(geo.lat),
            "lng": float(geo.lng),
            "matched_address": geo.matched_address,
            "address": city_project.address if city_project else geo.matched_address,
            "current_status": entity.current_status,
            "official_status": city_project.official_status if city_project else None,
            "summary": (city_project.description if city_project else
                        profile.summary if profile else None),
            "status_hint": related[0]["current_status"] if related else entity.current_status,
            "related": related,
        })
    return out


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


def _on_upcoming_agendas(session: Session, entity: Entity) -> list[dict]:
    """Upcoming events whose fetched agenda text names this entity."""
    variants = {v.lower() for v in [
        entity.name,
        *session.scalars(select(EntityAlias.alias).where(EntityAlias.entity_id == entity.id)),
    ] if v and len(v) >= MIN_VARIANT_LEN}
    if not variants:
        return []
    hits = []
    for u in session.scalars(select(UpcomingMeeting)
                             .where(UpcomingMeeting.agenda_text.isnot(None))):
        text = u.agenda_text.lower()
        if any(v in text for v in variants):
            hits.append({
                "title": u.title,
                "body": u.body,
                "starts_at": u.starts_at.isoformat() if u.starts_at else None,
                "in_progress": u.in_progress,
                "agenda_url": u.agenda_url,
            })
    return hits


def _city_record(session: Session, entity: Entity) -> dict | None:
    row = session.scalar(select(CityProject).where(CityProject.entity_id == entity.id))
    if row is None:
        return None
    from councilhound.db.models import ProjectEvaluation
    has_evaluation = session.scalar(
        select(ProjectEvaluation.id).where(
            ProjectEvaluation.city_project_id == row.id,
            ProjectEvaluation.status == "synthesized")) is not None
    return {
        "slug": row.external_slug,
        "has_evaluation": has_evaluation,
        "name": row.name,
        "project_type": row.project_type,
        "division": row.division,
        "official_status": row.official_status,
        "description": row.description,
        "requests": row.requests,
        "address": row.address,
        "applicant": row.applicant,
        "planner_name": row.planner_name,
        "planner_phone": row.planner_phone,
        "planner_email": row.planner_email,
        "detail_url": row.detail_url,
        "image_url": row.image_url,
        "documents": row.documents or [],
        "official_timeline": row.official_timeline or [],
        "lat": float(row.lat) if row.lat is not None else None,
        "lng": float(row.lng) if row.lng is not None else None,
        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
    }


@router.get("/{slug}/wiki")
def get_entity_wiki(slug: str, session: Session = Depends(db_session)):
    """The project's OKF wiki (mirrored from the knowledge bundle)."""
    entity = _resolve_entity(session, slug)
    payload = wiki_payload(session, entity) if entity else None
    if payload is None:
        raise HTTPException(404, "no wiki for this entity")
    return payload


@router.get("/{slug}")
def get_entity(slug: str, session: Session = Depends(db_session)):
    entity = _resolve_entity(session, slug)
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
        "official": _city_record(session, entity),
        "discussion": (entity_discussion_series(session, entity)
                       if entity.entity_type != "person" else []),
        "upcoming": _on_upcoming_agendas(session, entity),
        "timeline": timeline_out,
    }
