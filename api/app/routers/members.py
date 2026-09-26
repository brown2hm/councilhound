"""Council members, commissioners & school board members: roster derived
from title aliases ("Mayor Read", "Commissioner Cunningham", "School Board
Chair Pitches"), voting records matched by the
last-name keys the minutes use in vote breakdowns, and per-topic commentary
pulled back out of the entity profiles.

The detail endpoint also reads the record the way a reader would: which
votes were contested, where the member stood on them, who they vote with,
how the body tends to split, and which matters the votes were about."""
import datetime
import re
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    AgendaItem, Document, Entity, EntityAlias, EntityMention, EntityProfile,
    EntityUpdate, Meeting, UpcomingMeeting, Vote,
)
from councilhound.bodies import REGISTRY
from councilhound.config import LOCAL_TZ
from councilhound.entities import resolve_entity
from councilhound.people import last_name
from councilhound.seed import parse_roster

from app.db import db_session
from app.links import clip_link

router = APIRouter()

# Title-alias prefix -> role title, longest prefix first so a body-qualified
# title ("school board chair ") is not claimed by the bare one ("chair ");
# role display order and role -> body, all from the jurisdiction's roster
# config (bodies[].roster.roles).
_TITLE_ROLES = [(prefix, title) for prefix, title, _body in REGISTRY.title_roles()]
_ROLE_ORDER = REGISTRY.role_order()
_ROLE_BODY = {title: body for _prefix, title, body in REGISTRY.title_roles()}

# Kinds of item a vote can be about, from the agenda title and the motion
# text as filed. Order matters: the first match wins.
_CATEGORIES = [
    ("consent", "Consent agenda", r"consent agenda"),
    ("hearing", "Public hearings", r"^public hearing"),
    ("closed", "Closed meetings", r"closed (meeting|session)"),
    ("minutes", "Minutes", r"\bminutes\b"),
    ("appointment", "Appointments", r"\bappointment"),
    ("budget", "Budget, taxes and appropriations",
     r"budget|tax rate|\btax\b|\blevies\b|appropriation|capital improvement|\bcip\b|utility rate"),
    ("ordinance", "Ordinances", r"\bordinance"),
    ("resolution", "Resolutions", r"\bresolution"),
    ("contract", "Contracts and agreements", r"\bcontract|\baward|\bagreement|\bpurchas"),
]
# Below this many contested votes the comparative panels say more about the
# sample than the member; the page hides them.
MIN_CONTESTED_FOR_COMPARISONS = 10
# How many colleagues' casts a split pattern needs before it is reported.
MAX_SPLIT_PATTERNS = 5
MAX_MATTERS = 12


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


def _current_slugs(session: Session) -> set[str]:
    """Slugs of people on each body's CURRENT roster, parsed from the most
    recent agenda header that yields names (the 24-month window spans a
    council turnover, so membership can't be assumed from aliases alone)."""
    current: set[str] = set()
    for body in REGISTRY.bodies.values():
        if body.roster is None:
            continue
        docs = session.execute(
            select(Document.raw_text)
            .join(Meeting, Document.meeting_id == Meeting.id)
            .where(Meeting.body == body.key, Document.doc_type == "agenda",
                   Document.raw_text.isnot(None))
            .order_by(Meeting.meeting_date.desc())
            .limit(5)
        ).scalars()
        for raw_text in docs:
            names = [n for v in parse_roster(raw_text, body).values() for n in v]
            if not names:
                continue  # malformed/special-meeting header; try the next one
            for name in names:
                entity = resolve_entity(session, "person", name, create=False)
                if entity is not None:
                    current.add(entity.canonical_slug)
            break
    return current


def _vote_rows(session: Session) -> list[tuple]:
    return session.execute(
        select(Vote, Meeting, AgendaItem)
        .join(Meeting, Vote.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, Vote.agenda_item_id == AgendaItem.id)
        .order_by(Meeting.meeting_date.desc(), Vote.id.desc())
    ).all()


def _sorted_roles(roles: set) -> list[str]:
    return sorted(roles, key=lambda r: _ROLE_ORDER.get(r, 9))


def _cast_keys(name: str) -> set[str]:
    """Breakdown keys that count as this member: the last name, and for a
    hyphenated one its final part too (minutes write "Chandler" for
    Hardy-Chandler)."""
    last = last_name(name).lower()
    keys = {last}
    if "-" in last:
        keys.add(last.rsplit("-", 1)[-1])
    return keys


def _cast_for(breakdown: dict | None, keys: set[str]) -> str | None:
    for member_name, cast in (breakdown or {}).items():
        if member_name.lower() in keys:
            return cast
    return None


def _tally(breakdown: dict | None) -> dict[str, int]:
    return dict(Counter(v for v in (breakdown or {}).values()))


def _category(item_title: str | None, description: str | None) -> tuple[str, str]:
    text = f"{item_title or ''} {description or ''}".lower()
    for key, label, pattern in _CATEGORIES:
        if re.search(pattern, item_title.lower() if key == "hearing" and item_title else text):
            return key, label
    return "other", "Other business"


def _in_minority(cast: str | None, result: str | None) -> bool:
    return (cast == "no" and result == "passed") or (cast == "yes" and result == "failed")


@router.get("/")
def list_members(session: Session = Depends(db_session)):
    """The roster with each member's record: how many votes, the yes/no/
    absent split, the share cast on the winning side, and the last no vote
    — enough for the /members table to show how a member votes, not just
    how often."""
    members = _roster(session)
    counts: dict[str, int] = defaultdict(int)
    stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    decided: dict[str, int] = defaultdict(int)
    with_outcome: dict[str, int] = defaultdict(int)
    last_vote: dict[str, str] = {}
    last_no: dict[str, dict] = {}
    for vote, meeting, item in _vote_rows(session):  # newest first
        for member_name, cast in (vote.vote_breakdown or {}).items():
            key = member_name.lower()
            counts[key] += 1
            stats[key][cast] += 1
            last_vote.setdefault(key, meeting.meeting_date.isoformat())
            if cast in ("yes", "no") and vote.motion_result in ("passed", "failed"):
                decided[key] += 1
                if (cast == "yes") == (vote.motion_result == "passed"):
                    with_outcome[key] += 1
            if cast == "no" and key not in last_no:
                last_no[key] = {
                    "date": meeting.meeting_date.isoformat(),
                    "meeting_id": meeting.id,
                    "item_label": item.label if item else None,
                    "subject": vote.description or (item.title if item else None),
                    "motion_result": vote.motion_result,
                }

    current = _current_slugs(session)
    out = []
    for m in members.values():
        e, roles = m["entity"], _sorted_roles(m["roles"])
        key = last_name(e.name).lower()
        out.append({
            "slug": e.canonical_slug,
            "name": e.name,
            "roles": roles,
            "is_current": e.canonical_slug in current,
            "votes_cast": counts.get(key, 0),
            "last_vote": last_vote.get(key),
            "vote_stats": dict(stats.get(key, {})),
            "with_outcome_pct": (round(100 * with_outcome[key] / decided[key])
                                 if decided.get(key) else None),
            "last_no": last_no.get(key),
        })
    out.sort(key=lambda r: (not r["is_current"],
                            _ROLE_ORDER.get(r["roles"][0], 9) if r["roles"] else 9,
                            -r["votes_cast"], r["name"]))
    return out


def _topics_by_item(session: Session, item_ids: set[int]) -> dict[int, list[dict]]:
    """Non-person entities each agenda item is about (tracked updates first,
    then bare mentions), so votes can be grouped by matter."""
    if not item_ids:
        return {}
    out: dict[int, list[dict]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    for source in (EntityUpdate, EntityMention):
        rows = session.execute(
            select(source.agenda_item_id, Entity)
            .join(Entity, source.entity_id == Entity.id)
            .where(source.agenda_item_id.in_(item_ids), Entity.entity_type != "person")
            .order_by(source.id)
        )
        for item_id, entity in rows:
            if (item_id, entity.id) in seen:
                continue
            seen.add((item_id, entity.id))
            out[item_id].append({
                "slug": entity.canonical_slug,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "current_status": entity.current_status,
            })
    return out


def _body_for(roles: list[str], vote_bodies: Counter) -> str | None:
    if vote_bodies:
        return vote_bodies.most_common(1)[0][0]
    for r in roles:
        if r in _ROLE_BODY:
            return _ROLE_BODY[r]
    return None


def _upcoming_for_body(session: Session, body: str | None) -> list[dict]:
    if not body:
        return []
    today = datetime.datetime.now(LOCAL_TZ).replace(tzinfo=None)
    rows = session.scalars(
        select(UpcomingMeeting)
        .where(UpcomingMeeting.body == body)
        .order_by(UpcomingMeeting.in_progress.desc(),
                  UpcomingMeeting.starts_at.asc().nulls_last())
    ).all()
    out = []
    for u in rows:
        if not u.in_progress and u.starts_at is not None and u.starts_at < today - datetime.timedelta(hours=6):
            continue
        out.append({
            "event_id": u.granicus_event_id,
            "title": u.title,
            "body": u.body,
            "starts_at": u.starts_at.isoformat() if u.starts_at else None,
            "in_progress": u.in_progress,
            "agenda_url": u.agenda_url,
        })
        if len(out) == 2:
            break
    return out


@router.get("/{slug}")
def get_member(slug: str, session: Session = Depends(db_session)):
    entity = session.scalar(select(Entity).where(
        Entity.canonical_slug == slug, Entity.entity_type == "person"))
    if entity is None:
        raise HTTPException(404, "member not found")
    members = _roster(session)
    roles = _sorted_roles(members.get(entity.id, {}).get("roles", set()))
    keys = _cast_keys(entity.name)
    current = _current_slugs(session)

    # ---- this member's votes, with the whole body's tally on each ----
    rows = _vote_rows(session)
    mine: list[tuple] = []
    for vote, meeting, item in rows:
        cast = _cast_for(vote.vote_breakdown, keys)
        if cast is not None:
            mine.append((vote, meeting, item, cast))
    topics = _topics_by_item(session, {item.id for _, _, item, _ in mine if item})

    votes, stats = [], defaultdict(int)
    vote_bodies: Counter = Counter()
    by_meeting: dict[int, dict] = {}
    categories: dict[str, dict] = {}
    matters: dict[str, dict] = {}
    minority_no = minority_yes = 0
    close_total = close_lost = lone_no = 0
    decided = with_outcome = 0
    contested_count = 0
    for vote, meeting, item, cast in mine:
        stats[cast] += 1
        vote_bodies[meeting.body] += 1
        tally = _tally(vote.vote_breakdown)
        contested = tally.get("no", 0) > 0
        minority = _in_minority(cast, vote.motion_result)
        item_topics = topics.get(item.id, []) if item else []
        cat_key, cat_label = _category(item.title if item else None, vote.description)

        contested_count += contested
        if minority:
            if cast == "no":
                minority_no += 1
            else:
                minority_yes += 1
        if cast in ("yes", "no") and vote.motion_result in ("passed", "failed"):
            decided += 1
            with_outcome += (cast == "yes") == (vote.motion_result == "passed")
            if abs(tally.get("yes", 0) - tally.get("no", 0)) <= 1:
                close_total += 1
                close_lost += minority
        if cast == "no" and tally.get("no", 0) == 1:
            lone_no += 1

        m = by_meeting.setdefault(meeting.id, {
            "meeting_id": meeting.id, "date": meeting.meeting_date.isoformat(),
            "title": meeting.title, "body": meeting.body,
            "votes": 0, "no": 0, "contested": 0, "absent": 0,
        })
        m["votes"] += 1
        m["no"] += cast == "no"
        m["contested"] += contested
        m["absent"] += cast == "absent"

        c = categories.setdefault(cat_key, {"key": cat_key, "label": cat_label, "votes": 0, "no": 0, "absent": 0})
        c["votes"] += 1
        c["no"] += cast == "no"
        c["absent"] += cast == "absent"

        for t in item_topics:
            if t["entity_type"] in ("ordinance", "resolution", "case_number"):
                continue  # instrument numbers, not matters
            mt = matters.setdefault(t["slug"], {**t, "n": 0, "votes": defaultdict(int)})
            mt["n"] += 1
            mt["votes"][cast] += 1

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
            "tally": tally,
            "contested": contested,
            "in_minority": minority,
            "breakdown": vote.vote_breakdown or {},
            "category": cat_key,
            "topics": item_topics,
            "watch_url": clip_link(meeting.granicus_view_id, meeting.granicus_clip_id,
                                   item.start_seconds)
            if item and item.start_seconds is not None else None,
        })

    body = _body_for(roles, vote_bodies)

    # ---- colleagues on the same body: their record, and alignment ----
    colleagues = []
    for m in members.values():
        e = m["entity"]
        if e.id == entity.id or e.canonical_slug not in current:
            continue
        their_roles = _sorted_roles(m["roles"])
        if _body_for(their_roles, Counter()) != body:
            continue
        colleagues.append({"entity": e, "roles": their_roles, "keys": _cast_keys(e.name)})

    col_stats = {c["entity"].id: {"votes_cast": 0, "no_votes": 0, "agree": 0, "agree_n": 0}
                 for c in colleagues}
    for vote, meeting, item in rows:
        if meeting.body != body:
            continue
        for c in colleagues:
            their = _cast_for(vote.vote_breakdown, c["keys"])
            if their is None:
                continue
            s = col_stats[c["entity"].id]
            s["votes_cast"] += 1
            s["no_votes"] += their == "no"
    for vote, meeting, item, cast in mine:
        if cast not in ("yes", "no") or "no" not in (vote.vote_breakdown or {}).values():
            continue
        for c in colleagues:
            their = _cast_for(vote.vote_breakdown, c["keys"])
            if their in ("yes", "no"):
                s = col_stats[c["entity"].id]
                s["agree_n"] += 1
                s["agree"] += their == cast

    colleague_rows = []
    for c in colleagues:
        s = col_stats[c["entity"].id]
        colleague_rows.append({
            "slug": c["entity"].canonical_slug,
            "name": c["entity"].name,
            "roles": c["roles"],
            "votes_cast": s["votes_cast"],
            "no_votes": s["no_votes"],
            "agree_pct": round(100 * s["agree"] / s["agree_n"]) if s["agree_n"] else None,
            "agree_n": s["agree_n"],
        })
    colleague_rows.sort(key=lambda r: (r["agree_pct"] is None, -(r["agree_pct"] or 0), r["name"]))

    # ---- how the body splits: line-ups on this member's contested votes ----
    # The order is the member first, then colleagues by alignment, so the
    # dots on the page cluster allies together. Members who rarely vote
    # (a mayor breaking ties) are left out of the pattern.
    voting_colleagues = [c for c in colleagues if col_stats[c["entity"].id]["votes_cast"] >= 0.5 * max(1, len(mine))]
    order = [entity.canonical_slug] + [r["slug"] for r in colleague_rows
                                        if r["slug"] in {c["entity"].canonical_slug for c in voting_colleagues}]
    keys_by_slug = {entity.canonical_slug: keys, **{c["entity"].canonical_slug: c["keys"] for c in colleagues}}
    patterns: Counter = Counter()
    for vote, meeting, item, cast in mine:
        bd = vote.vote_breakdown or {}
        if "no" not in bd.values():
            continue
        nos = tuple(s for s in order if _cast_for(bd, keys_by_slug[s]) == "no")
        if nos:
            patterns[nos] += 1
    splits = [{"no": list(nos), "count": n} for nos, n in patterns.most_common(MAX_SPLIT_PATTERNS)]

    # ---- commentary ----
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

    meetings_list = list(by_meeting.values())
    meetings_list.sort(key=lambda m: m["date"])
    absent_meetings = [{"meeting_id": m["meeting_id"], "date": m["date"]}
                       for m in meetings_list if m["votes"] and m["absent"] == m["votes"]]
    matters_list = sorted(matters.values(), key=lambda m: (-m["n"], m["name"]))[:MAX_MATTERS]
    for m in matters_list:
        m["votes"] = dict(m["votes"])

    return {
        "slug": entity.canonical_slug,
        "name": entity.name,
        "roles": roles,
        "body": body,
        "is_current": entity.canonical_slug in current,
        "vote_stats": dict(stats),
        "record": {
            "votes": len(votes),
            "meetings": len(by_meeting),
            "first_vote": votes[-1]["date"] if votes else None,
            "last_vote": votes[0]["date"] if votes else None,
            "with_outcome_pct": round(100 * with_outcome / decided) if decided else None,
            "contested": contested_count,
            "minority": {"total": minority_no + minority_yes,
                         "no_on_passed": minority_no, "yes_on_failed": minority_yes},
            "close_votes": {"total": close_total, "lost": close_lost},
            "lone_no": lone_no,
            "absent_meetings": absent_meetings,
            "comparisons": contested_count >= MIN_CONTESTED_FOR_COMPARISONS,
        },
        "votes": votes,
        "by_meeting": meetings_list,
        "categories": sorted(categories.values(), key=lambda c: (-c["votes"], c["label"])),
        "matters": matters_list,
        "colleagues": colleague_rows,
        "split_order": order,
        "splits": splits,
        "commentary": commentary,
        "upcoming": _upcoming_for_body(session, body),
    }
