"""What a meeting says about tracked topics beyond the agenda links the
extractor filed.

The extractor links a topic to a meeting only through the minutes-level
record (entity_updates, entity_mentions). Across the transcribed council
meetings, 44% of the time members spend naming a wiki project falls in
meetings where that project has no such link — the Housing Trust Fund work
session that names Beacon Landing five times, say. This module reads the
transcript directly: how long each chaptered item ran, which tracked topics
it names, and which named topics the agenda never linked at all. Matching is
the deterministic name/alias scan from councilhound.hot_topics, so the
counts are a consistent lower bound rather than an LLM judgement.

It also gathers the context a reader needs to relate an agenda item to what
the wiki already knows: the overview lede, the open questions, and the
anchor of this meeting's own entry in the wiki's history page.
"""
import bisect
import re

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    CityProject, Entity, EntityAlias, EntityProfile, Meeting, TranscriptChunk, WikiPage,
)
from councilhound.hot_topics import MIN_VARIANT_LEN

EXCERPT_CHARS = 260
MAX_NAMED_PER_ITEM = 6
MAX_NAMED_UNLINKED = 12
MIN_PASSAGES_FOR_TOPIC = 3
MAX_OPEN_QUESTIONS = 3
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\d“(])")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def slugify(text: str) -> str:
    """Same rule as frontend/lib/wiki.ts slugify and okf.bundle.slugify, so
    a heading anchor computed here lands on the heading the page renders."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _lead(text: str | None, n: int = 2) -> str | None:
    if not text:
        return None
    return " ".join(_SENTENCE_END.split(text.strip())[:n]) or None


def _overview_lede(body: str) -> str | None:
    """First paragraph of an overview page, before any section heading and
    with the editor-facing comments gone."""
    text = _COMMENT.sub("", body)
    text = text.split("\n## ", 1)[0]
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if para and not para.startswith("#"):
            return _lead(para)
    return None


def candidates(session: Session) -> list[tuple[Entity, list[str], bool]]:
    """Non-person entities with a wiki or a profile — the topics that have
    something to say back when the transcript names them — with their
    matchable name variants, longest first, and whether they have a wiki."""
    has_wiki = exists().where(WikiPage.entity_id == Entity.id, WikiPage.kind == "concept")
    has_profile = exists().where(EntityProfile.entity_id == Entity.id)
    entities = session.scalars(
        select(Entity).where(Entity.entity_type != "person", has_wiki | has_profile)
    ).all()
    if not entities:
        return []
    ids = [e.id for e in entities]
    with_wiki = set(session.scalars(
        select(WikiPage.entity_id).where(WikiPage.entity_id.in_(ids), WikiPage.kind == "concept")))
    out = []
    for e, names in _variants(session, entities):
        out.append((e, names, e.id in with_wiki))
    return out


def _variants(session: Session, entities: list[Entity]) -> list[tuple[Entity, list[str]]]:
    """Each entity's matchable name variants (name + aliases, lowercased,
    short ones dropped), longest first."""
    aliases: dict[int, list[str]] = {}
    if entities:
        for eid, alias in session.execute(
            select(EntityAlias.entity_id, EntityAlias.alias)
            .where(EntityAlias.entity_id.in_([e.id for e in entities]))
        ):
            aliases.setdefault(eid, []).append(alias)
    out = []
    for e in entities:
        names = {v.lower() for v in [e.name, *aliases.get(e.id, [])]
                 if v and len(v) >= MIN_VARIANT_LEN}
        if names:
            out.append((e, sorted(names, key=len, reverse=True)))
    return out


def _excerpt(text: str, variant: str, width: int = EXCERPT_CHARS) -> str:
    """A window of the passage around the first time it names the topic,
    cut at word boundaries."""
    text = " ".join(text.split())
    pos = text.lower().find(variant)
    if pos < 0:
        pos = 0
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    if start > 0:
        start = text.find(" ", start) + 1 if " " in text[start:] else start
    if end < len(text):
        cut = text.rfind(" ", start, end)
        end = cut if cut > start else end
    piece = text[start:end].strip()
    return ("…" if start > 0 else "") + piece + ("…" if end < len(text) else "")


def transcript_discussion(
    session: Session,
    meeting: Meeting,
    items: list,
    linked_by_item: dict[int | None, set[int]],
    link,
) -> tuple[dict[int, dict], list[dict], bool]:
    """Per chaptered item: how long it ran in the transcript and which tracked
    topics it names that the item is not filed under. For the meeting: the
    tracked topics the transcript names that no agenda item links at all,
    each with its first passage. Returns (by_item, named_unlinked, transcribed).

    `items` is the whole agenda in filed order; an item with an index point
    owns the transcript from there to the next index point. That window is
    only the item's own when the next filed item is the next chaptered one —
    otherwise unchaptered items sit inside it and `exact` is False.
    `linked_by_item` maps agenda_item_id (None for matters outside the
    agenda) to the entity ids the record links there. `link(seconds)` builds
    the video deep link.

    A name that is part of a longer name present in the same passage does
    not count ("Master Plan" inside "Urban Forest Master Plan"), whether the
    longer name is another candidate's or belongs to a topic the agenda
    links. Places count only when they have a wiki; a passing street name
    is not a discussion of it."""
    chunks = session.execute(
        select(TranscriptChunk.start_seconds, TranscriptChunk.end_seconds, TranscriptChunk.text)
        .where(TranscriptChunk.meeting_id == meeting.id,
               TranscriptChunk.start_seconds.isnot(None))
        .order_by(TranscriptChunk.start_seconds, TranscriptChunk.id)
    ).all()
    if not chunks:
        return {}, [], False

    topics = candidates(session)
    linked_anywhere: set[int] = set().union(*linked_by_item.values()) if linked_by_item else set()
    linked_entities = session.scalars(
        select(Entity).where(Entity.id.in_(linked_anywhere))).all() if linked_anywhere else []
    linked_variants = [v for _, names in _variants(session, linked_entities) for v in names]

    timed = sorted((it for it in items if it.start_seconds is not None),
                   key=lambda it: it.start_seconds)
    starts = [float(it.start_seconds) for it in timed]
    exact: dict[int, bool] = {}
    for i, it in enumerate(items):
        if it.start_seconds is None:
            continue
        following = items[i + 1] if i + 1 < len(items) else None
        exact[it.id] = following is None or following.start_seconds is not None
    per_item: dict[int, dict] = {
        it.id: {"seconds": 0.0, "chunks": 0, "named": {}} for it in timed}
    meeting_named: dict[int, dict] = {}

    for start, end, text in chunks:
        start = float(start)
        duration = max(0.0, float(end) - start) if end is not None else 0.0
        idx = bisect.bisect_right(starts, start) - 1
        item = timed[idx] if idx >= 0 else None
        if item is not None:
            per_item[item.id]["seconds"] += duration
            per_item[item.id]["chunks"] += 1
        text_l = text.lower()
        present: list[tuple[str, tuple | None]] = []
        for entity, names, has_wiki in topics:
            if entity.entity_type == "location" and not has_wiki:
                continue
            hit = next((n for n in names if n in text_l), None)
            if hit is not None:
                present.append((hit, (entity, has_wiki)))
        if not present:
            continue
        for v in linked_variants:
            if v in text_l:
                present.append((v, None))
        for hit, found in present:
            if found is None or any(hit != other and hit in other for other, _ in present):
                continue
            entity, has_wiki = found
            if item is not None and entity.id not in linked_by_item.get(item.id, set()):
                named = per_item[item.id]["named"]
                named[entity.id] = named.get(entity.id, 0) + 1
            if entity.id not in linked_anywhere:
                row = meeting_named.setdefault(entity.id, {
                    "entity": entity, "has_wiki": has_wiki, "count": 0, "seconds": 0.0,
                    "first": {"start_seconds": int(start), "watch_url": link(start),
                              "excerpt": _excerpt(text, hit)},
                })
                row["count"] += 1
                row["seconds"] += duration

    by_id = {e.id: e for e, _, _ in topics}
    by_item = {}
    for item_id, d in per_item.items():
        if d["chunks"] == 0:
            continue
        named = sorted(d["named"].items(), key=lambda kv: (-kv[1], by_id[kv[0]].name))
        by_item[item_id] = {
            "seconds": round(d["seconds"]),
            "exact": exact[item_id],
            "chunks": d["chunks"],
            "named": [
                {"slug": by_id[eid].canonical_slug, "name": by_id[eid].name, "count": n}
                for eid, n in named[:MAX_NAMED_PER_ITEM]
            ],
        }
    # a project or a wiki topic earns a row on one passage; a plan, program
    # or fund needs to keep coming up before it is "discussed"
    unlinked = sorted(
        (r for r in meeting_named.values()
         if r["has_wiki"] or r["entity"].entity_type == "project" or r["count"] >= MIN_PASSAGES_FOR_TOPIC),
        key=lambda r: (-r["seconds"], r["entity"].name))[:MAX_NAMED_UNLINKED]
    return by_item, [
        {
            "slug": r["entity"].canonical_slug,
            "name": r["entity"].name,
            "entity_type": r["entity"].entity_type,
            "current_status": r["entity"].current_status,
            "count": r["count"],
            "seconds": round(r["seconds"]),
            "first": r["first"],
        }
        for r in unlinked
    ], True


def topic_context(session: Session, meeting: Meeting, entity_ids: set[int]) -> dict[int, dict]:
    """For each entity: whether it has a wiki and where (official slug when the
    city keeps a record, else the topic route), the overview lede or profile
    lead, the open questions, and the anchor of this meeting's heading in the
    wiki history page when the history already records it."""
    if not entity_ids:
        return {}
    ids = list(entity_ids)
    overview: dict[int, str] = {}
    history: dict[int, str] = {}
    has_wiki: set[int] = set()
    for row in session.scalars(
        select(WikiPage).where(WikiPage.entity_id.in_(ids), WikiPage.kind == "concept")
    ):
        has_wiki.add(row.entity_id)
        if row.page == "overview":
            overview[row.entity_id] = row.body
        elif row.page == "history":
            history[row.entity_id] = row.body
    profiles = {p.entity_id: p for p in session.scalars(
        select(EntityProfile).where(EntityProfile.entity_id.in_(ids)))}
    official = dict(session.execute(
        select(CityProject.entity_id, CityProject.external_slug)
        .where(CityProject.entity_id.in_(ids))).all())

    heading = f"{meeting.meeting_date.isoformat()} — {meeting.title}"
    anchor = slugify(heading)
    out = {}
    for eid in ids:
        profile = profiles.get(eid)
        lede = (_overview_lede(overview[eid]) if eid in overview else None) \
            or _lead(profile.summary if profile else None)
        questions = list(profile.open_questions or [])[:MAX_OPEN_QUESTIONS] if profile else []
        out[eid] = {
            "has_wiki": eid in has_wiki,
            "official_slug": official.get(eid),
            "lede": lede,
            "open_questions": questions,
            "history_anchor": anchor if f"## {heading}" in history.get(eid, "") else None,
        }
    return out
