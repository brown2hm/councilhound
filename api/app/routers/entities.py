"""Entity/topic tracker: list trackable entities with their current status,
and per-entity timeline — the 'progress over time' view."""
import datetime
import math
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import String, case, exists, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from councilhound.db.models import (
    AgendaItem, CityProject, Entity, EntityAlias, EntityGeocode, EntityMention, EntityProfile,
    EntityUpdate, Meeting, ProjectEvaluation, UpcomingMeeting, Vote, WikiPage,
)
from councilhound.hot_topics import MIN_VARIANT_LEN
from councilhound.hot_topics import entity_discussion_series, hot_topics
from councilhound.changes import recent_changes as compute_recent_changes, status_words
from councilhound.notify import SITE_BASE_URL

from app.db import db_session
from app.links import clip_link
from app.ratelimit import check_geocode_rate
from app.wiki import entity_has_wiki, wiki_payload

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


def _update_counts():
    """Per-entity rollup of the tracked record: how many updates, when the
    first and latest landed, and which bodies produced them."""
    return (
        select(EntityUpdate.entity_id,
               func.count().label("n"),
               func.max(Meeting.meeting_date).label("last_date"),
               func.min(Meeting.meeting_date).label("first_date"),
               func.array_agg(Meeting.body.distinct(), type_=ARRAY(String)).label("bodies"))
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .group_by(EntityUpdate.entity_id)
        .subquery()
    )


def _synthesized_project_ids(session: Session) -> set[int]:
    return set(session.scalars(
        select(ProjectEvaluation.city_project_id)
        .where(ProjectEvaluation.status == "synthesized")))


def _wiki_entity_ids(session: Session) -> set[int]:
    return set(session.scalars(
        select(WikiPage.entity_id).where(WikiPage.kind == "concept").distinct()))


@router.get("/")
def list_entities(
    entity_type: str | None = Query(None, description="project | ordinance | resolution | case_number | topic | location | person"),
    status: str | None = None,
    body: str | None = Query(None, description="only topics this body has acted on: city_council | planning_commission"),
    days: int | None = Query(None, ge=1, le=730, description="only topics updated within the last N days"),
    min_updates: int = Query(1, ge=1, description="hide topics with fewer tracked updates (the one-mention tail)"),
    official: bool | None = Query(None, description="true: only official city project records; false: only meeting-derived"),
    q: str | None = Query(None, description="substring match on name or alias"),
    sort: str = Query("recent", description="recent | active | name"),
    limit: int = Query(50, le=200),
    offset: int = 0,
    session: Session = Depends(db_session),
):
    """The directory behind /topics: every tracked entity with its status,
    activity rollup, and — where the city has a record or a geocode — the
    project card fields (image, address, coordinates) and which views exist."""
    uc = _update_counts()
    geo = (select(EntityGeocode.entity_id, EntityGeocode.lat, EntityGeocode.lng)
           .where(EntityGeocode.status == "ok").subquery())
    query = (
        select(Entity, uc.c.n, uc.c.last_date, uc.c.first_date, uc.c.bodies,
               CityProject,
               func.coalesce(CityProject.lat, geo.c.lat).label("lat"),
               func.coalesce(CityProject.lng, geo.c.lng).label("lng"))
        .join(uc, Entity.id == uc.c.entity_id)
        .outerjoin(CityProject, CityProject.entity_id == Entity.id)
        .outerjoin(geo, geo.c.entity_id == Entity.id)
    )
    if sort == "active":
        query = query.order_by(uc.c.n.desc(), uc.c.last_date.desc(), Entity.name)
    elif sort == "name":
        query = query.order_by(Entity.name)
    else:
        query = query.order_by(uc.c.last_date.desc(), uc.c.n.desc(), Entity.name)
    if entity_type:
        query = query.where(Entity.entity_type == entity_type)
    if status:
        query = query.where(Entity.current_status == status)
    if body:
        query = query.where(exists(
            select(EntityUpdate.id)
            .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
            .where(EntityUpdate.entity_id == Entity.id, Meeting.body == body)))
    if days:
        query = query.where(
            uc.c.last_date >= datetime.date.today() - datetime.timedelta(days=days))
    if min_updates > 1:
        query = query.where(uc.c.n >= min_updates)
    if official is True:
        query = query.where(CityProject.id.isnot(None))
    elif official is False:
        query = query.where(CityProject.id.is_(None))
    if q:
        needle = f"%{q}%"
        query = query.where(or_(
            Entity.name.ilike(needle),
            exists(select(EntityAlias.id).where(EntityAlias.entity_id == Entity.id,
                                                EntityAlias.alias.ilike(needle)))))

    rows = session.execute(query.limit(limit).offset(offset)).all()
    synthesized = _synthesized_project_ids(session)
    wiki_ids = _wiki_entity_ids(session)
    return [
        {
            "slug": e.canonical_slug,
            "name": e.name,
            "entity_type": e.entity_type,
            "current_status": e.current_status,
            "update_count": n,
            "last_seen": last.isoformat() if last else None,
            "first_seen": first.isoformat() if first else None,
            "bodies": sorted(b for b in (bodies or []) if b),
            "lat": float(lat) if lat is not None else None,
            "lng": float(lng) if lng is not None else None,
            "has_wiki": e.id in wiki_ids,
            "official": {
                "slug": cp.external_slug,
                "official_status": cp.official_status,
                "project_type": cp.project_type,
                "address": cp.address,
                "image_url": cp.image_url,
                "description": cp.description,
                "has_evaluation": cp.id in synthesized,
            } if cp else None,
        }
        for e, n, last, first, bodies, cp, lat, lng in rows
    ]


@router.get("/suggest")
def suggest_entities(
    q: str = Query(min_length=2, max_length=80),
    limit: int = Query(8, le=20),
    session: Session = Depends(db_session),
):
    """Typeahead for the site-wide search box: tracked topics whose name or
    alias contains the text, prefix matches first, then busiest first. Council
    members and commissioners are included as `kind: member`."""
    from app.routers.members import _roster

    needle = f"%{q.strip()}%"
    uc = _update_counts()
    alias_hit = exists(select(EntityAlias.id).where(
        EntityAlias.entity_id == Entity.id, EntityAlias.alias.ilike(needle)))
    prefix_first = case((Entity.name.ilike(f"{q.strip()}%"), 0), else_=1)
    rows = session.execute(
        select(Entity, uc.c.n, uc.c.last_date)
        .outerjoin(uc, Entity.id == uc.c.entity_id)
        .where(or_(Entity.name.ilike(needle), alias_hit))
        .order_by(prefix_first, func.coalesce(uc.c.n, 0).desc(), Entity.name)
        .limit(limit * 3)
    ).all()
    roster = _roster(session)
    out = []
    for e, n, last in rows:
        if e.entity_type == "person":
            if e.id not in roster:
                continue  # people who aren't members have no page of their own
            out.append({"kind": "member", "slug": e.canonical_slug, "name": e.name,
                        "entity_type": "person", "current_status": None,
                        "update_count": 0, "last_seen": None,
                        "href": f"/members/{e.canonical_slug}"})
        else:
            if not n:
                continue  # never tracked: nothing to show on its page
            out.append({"kind": "topic", "slug": e.canonical_slug, "name": e.name,
                        "entity_type": e.entity_type, "current_status": e.current_status,
                        "update_count": n, "last_seen": last.isoformat() if last else None,
                        "href": f"/topics/{e.canonical_slug}"})
        if len(out) >= limit:
            break
    return out


def _recent_changes(session: Session, days: int) -> list[dict]:
    out = []
    for c in compute_recent_changes(session, days):
        c = dict(c)
        view_id, clip_id = c.pop("granicus_view_id"), c.pop("granicus_clip_id")
        start = c.pop("start_seconds")
        c["watch_url"] = (clip_link(view_id, clip_id, start)
                          if start is not None else None)
        out.append(c)
    return out


@router.get("/changes")
def recent_changes(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, le=200),
    session: Session = Depends(db_session),
):
    """What changed: topics whose status moved, and topics that appeared for
    the first time, in the last N days — newest first."""
    changes = _recent_changes(session, days)
    return {
        "days": days,
        "since": (datetime.date.today() - datetime.timedelta(days=days)).isoformat(),
        "changes": changes[:limit],
    }


@router.get("/changes.atom")
def recent_changes_feed(session: Session = Depends(db_session)):
    """The change feed as Atom, for feed readers — the topic-tracking
    counterpart of the meeting calendar's .ics."""
    changes = _recent_changes(session, days=30)[:100]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = f"{changes[0]['date']}T00:00:00Z" if changes else now
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        "<title>CouncilHound — what changed in City of Fairfax council business</title>",
        f'<link href="{xml_escape(SITE_BASE_URL)}/topics?view=changes"/>',
        f'<link rel="self" href="{xml_escape(SITE_BASE_URL)}/entities/changes.atom"/>',
        f"<id>{xml_escape(SITE_BASE_URL)}/entities/changes.atom</id>",
        f"<updated>{updated}</updated>",
        "<author><name>CouncilHound</name></author>",
    ]
    for c in changes:
        link = f"{SITE_BASE_URL}/topics/{c['slug']}#m-{c['meeting_id']}"
        if c["kind"] == "new":
            title = f"New topic: {c['name']}"
        else:
            title = (f"{c['name']}: {status_words(c['from_status'])} → "
                     f"{status_words(c['to_status'])}")
        summary = f"{c['meeting_title']} ({c['date']}): {c['update_text']}"
        lines += [
            "<entry>",
            f"<title>{xml_escape(title)}</title>",
            f'<link href="{xml_escape(link)}"/>',
            f"<id>tag:councilhound.net,2026:change/{c['id']}</id>",
            f"<updated>{c['date']}T00:00:00Z</updated>",
            f"<summary>{xml_escape(summary)}</summary>",
            "</entry>",
        ]
    lines.append("</feed>")
    return Response("\n".join(lines) + "\n", media_type="application/atom+xml",
                    headers={"Cache-Control": "public, max-age=1800"})


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@router.get("/near")
def near(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius_m: int = Query(1600, ge=100, le=10000),
    limit: int = Query(60, le=200),
    session: Session = Depends(db_session),
):
    """Projects and named locations within a radius of a point, nearest
    first — the 'what's happening near me' entry point. Coordinates come from
    the city's own project records first, then our geocoded locations."""
    uc = _update_counts()
    rows = session.execute(
        select(Entity, EntityGeocode, CityProject, EntityProfile, uc.c.n, uc.c.last_date)
        .outerjoin(EntityGeocode, (EntityGeocode.entity_id == Entity.id)
                   & (EntityGeocode.status == "ok"))
        .outerjoin(CityProject, CityProject.entity_id == Entity.id)
        .outerjoin(EntityProfile, EntityProfile.entity_id == Entity.id)
        .outerjoin(uc, uc.c.entity_id == Entity.id)
        .where(or_(EntityGeocode.id.isnot(None), CityProject.lat.isnot(None)))
    ).all()
    synthesized = _synthesized_project_ids(session)
    out = []
    for entity, geo, cp, profile, n, last in rows:
        plat = cp.lat if cp and cp.lat is not None else (geo.lat if geo else None)
        plng = cp.lng if cp and cp.lng is not None else (geo.lng if geo else None)
        if plat is None or plng is None:
            continue
        d = _haversine_m(lat, lng, float(plat), float(plng))
        if d > radius_m:
            continue
        out.append({
            "slug": entity.canonical_slug,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "current_status": entity.current_status,
            "distance_m": round(d),
            "lat": float(plat),
            "lng": float(plng),
            "address": (cp.address if cp and cp.address else
                        geo.matched_address if geo else None),
            "summary": (cp.description if cp and cp.description else
                        profile.summary if profile else None),
            "update_count": n or 0,
            "last_seen": last.isoformat() if last else None,
            "official": {
                "slug": cp.external_slug,
                "official_status": cp.official_status,
                "project_type": cp.project_type,
                "image_url": cp.image_url,
                "has_evaluation": cp.id in synthesized,
            } if cp else None,
        })
    # official city records without a tracked entity still belong on the list
    for cp in session.scalars(select(CityProject).where(
            CityProject.entity_id.is_(None), CityProject.lat.isnot(None))):
        d = _haversine_m(lat, lng, float(cp.lat), float(cp.lng))
        if d > radius_m:
            continue
        out.append({
            "slug": None, "name": cp.name, "entity_type": "project",
            "current_status": None, "distance_m": round(d),
            "lat": float(cp.lat), "lng": float(cp.lng),
            "address": cp.address, "summary": cp.description,
            "update_count": 0, "last_seen": None,
            "official": {"slug": cp.external_slug, "official_status": cp.official_status,
                         "project_type": cp.project_type, "image_url": cp.image_url,
                         "has_evaluation": cp.id in synthesized},
        })
    out.sort(key=lambda r: r["distance_m"])
    return {"lat": lat, "lng": lng, "radius_m": radius_m, "results": out[:limit]}


@router.get("/geocode")
def geocode(request: Request, q: str = Query(min_length=3, max_length=200)):
    """Resolve a street address to coordinates for /near, via the same free
    Census geocoder the pipeline uses. Rate-limited per IP: it's an upstream
    call we don't control."""
    check_geocode_rate(request)
    from councilhound.geocode import geocode_address

    try:
        hit = geocode_address(q)
    except Exception:
        raise HTTPException(502, "the geocoder is unavailable right now")
    if not hit:
        raise HTTPException(404, "no match for that address")
    return hit


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
                "event_id": u.granicus_event_id,
                "title": u.title,
                "body": u.body,
                "starts_at": u.starts_at.isoformat() if u.starts_at else None,
                "in_progress": u.in_progress,
                "agenda_url": u.agenda_url,
            })
    return hits


def _location(session: Session, entity: Entity) -> dict | None:
    """Where this is on the map, if anywhere: the city's project coordinates
    first, then our geocode of a named address."""
    cp = session.scalar(select(CityProject).where(CityProject.entity_id == entity.id))
    if cp is not None and cp.lat is not None and cp.lng is not None:
        return {"lat": float(cp.lat), "lng": float(cp.lng), "source": "city"}
    geo = session.scalar(select(EntityGeocode).where(
        EntityGeocode.entity_id == entity.id, EntityGeocode.status == "ok"))
    if geo is not None:
        return {"lat": float(geo.lat), "lng": float(geo.lng), "source": "geocode"}
    return None


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
        # meeting-derived entities have no /development route, so the topics
        # page is the only place their wiki can be linked from
        "has_wiki": entity_has_wiki(session, entity.id),
        "official": _city_record(session, entity),
        "location": _location(session, entity),
        "discussion": (entity_discussion_series(session, entity)
                       if entity.entity_type != "person" else []),
        "upcoming": _on_upcoming_agendas(session, entity),
        "timeline": timeline_out,
    }
