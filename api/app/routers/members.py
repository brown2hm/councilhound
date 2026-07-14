"""Council members & commissioners: roster derived from title aliases
("Mayor Read", "Commissioner Cunningham"), voting records matched by the
last-name keys the minutes use in vote breakdowns, and per-topic commentary
pulled back out of the entity profiles."""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    AgendaItem, Entity, EntityAlias, EntityProfile, Meeting, Vote,
)

from app.db import db_session
from app.links import clip_link

router = APIRouter()

_TITLE_ROLES = [
    ("mayor ", "Mayor"),
    ("councilmember ", "Councilmember"),
    ("council member ", "Councilmember"),
    ("councilwoman ", "Councilmember"),
    ("councilman ", "Councilmember"),
    ("vice-chair ", "Vice-Chair"),
    ("vice chair ", "Vice-Chair"),
    ("chairman ", "Chair"),
    ("chair ", "Chair"),
    ("commissioner ", "Commissioner"),
]
_ROLE_ORDER = {"Mayor": 0, "Councilmember": 1, "Chair": 2, "Vice-Chair": 3, "Commissioner": 4}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _roster(session: Session) -> dict[int, dict]:
    """person entity id -> {entity, roles} for people with a title alias."""
    rows = session.execute(
        select(Entity, EntityAlias.alias)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(Entity.entity_type == "person")
    ).all()
    members: dict[int, dict] = {}
    for entity, alias in rows:
        a = alias.lower()
        for prefix, role in _TITLE_ROLES:
            if a.startswith(prefix):
                m = members.setdefault(entity.id, {"entity": entity, "roles": set()})
                m["roles"].add(role)
                break
    return members


def _last_name(name: str) -> str:
    tokens = [t for t in name.replace(",", " ").split()
              if t.lower().rstrip(".") not in _SUFFIXES]
    return tokens[-1] if tokens else ""


def _vote_rows(session: Session) -> list[tuple]:
    return session.execute(
        select(Vote, Meeting, AgendaItem)
        .join(Meeting, Vote.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, Vote.agenda_item_id == AgendaItem.id)
        .order_by(Meeting.meeting_date.desc())
    ).all()


def _sorted_roles(roles: set) -> list[str]:
    return sorted(roles, key=lambda r: _ROLE_ORDER.get(r, 9))


@router.get("/")
def list_members(session: Session = Depends(db_session)):
    members = _roster(session)
    counts: dict[str, int] = defaultdict(int)
    last_vote: dict[str, str] = {}
    for vote, meeting, _item in _vote_rows(session):
        for member_name in (vote.vote_breakdown or {}):
            counts[member_name.lower()] += 1
            last_vote.setdefault(member_name.lower(), meeting.meeting_date.isoformat())

    out = []
    for m in members.values():
        e, roles = m["entity"], _sorted_roles(m["roles"])
        key = _last_name(e.name).lower()
        out.append({
            "slug": e.canonical_slug,
            "name": e.name,
            "roles": roles,
            "votes_cast": counts.get(key, 0),
            "last_vote": last_vote.get(key),
        })
    out.sort(key=lambda r: (_ROLE_ORDER.get(r["roles"][0], 9) if r["roles"] else 9,
                            -r["votes_cast"], r["name"]))
    return out


@router.get("/{slug}")
def get_member(slug: str, session: Session = Depends(db_session)):
    entity = session.scalar(select(Entity).where(
        Entity.canonical_slug == slug, Entity.entity_type == "person"))
    if entity is None:
        raise HTTPException(404, "member not found")
    members = _roster(session)
    roles = _sorted_roles(members.get(entity.id, {}).get("roles", set()))
    last = _last_name(entity.name)

    votes, stats = [], defaultdict(int)
    for vote, meeting, item in _vote_rows(session):
        cast = None
        for member_name, v in (vote.vote_breakdown or {}).items():
            if member_name.lower() == last.lower():
                cast = v
                break
        if cast is None:
            continue
        stats[cast] += 1
        votes.append({
            "date": meeting.meeting_date.isoformat(),
            "meeting_id": meeting.id,
            "meeting_title": meeting.title,
            "body": meeting.body,
            "item_label": item.label if item else None,
            "item_title": item.title if item else None,
            "description": vote.description,
            "motion_result": vote.motion_result,
            "vote": cast,
            "watch_url": clip_link(meeting.granicus_view_id, meeting.granicus_clip_id,
                                   item.start_seconds)
            if item and item.start_seconds is not None else None,
        })

    commentary = []
    profile_rows = session.execute(
        select(EntityProfile, Entity)
        .join(Entity, EntityProfile.entity_id == Entity.id)
        .where(EntityProfile.member_commentary.isnot(None))
    ).all()
    for profile, topic in profile_rows:
        for entry in profile.member_commentary or []:
            if entry.get("slug") == entity.canonical_slug:
                commentary.append({
                    "topic_slug": topic.canonical_slug,
                    "topic_name": topic.name,
                    "topic_status": topic.current_status,
                    "summary": entry.get("summary", ""),
                })

    return {
        "slug": entity.canonical_slug,
        "name": entity.name,
        "roles": roles,
        "vote_stats": dict(stats),
        "votes": votes,
        "commentary": commentary,
    }
