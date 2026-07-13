"""
Entity dedup (July 2026 audit: 84% of non-person entities were
single-mention, with clusters like courthouse-plaza x5 split by phrasing
drift). Two mechanisms:

1. Slug normalization used by entity resolution — strips redundant suffixes
   ("X Project" == "X", "Urban Forest Master Plan (UFMP)" == acronym twin)
   so drifting phrasings land on one canonical slug. Create-time strips are
   deliberately minimal (they apply with no context); resolve-time fallback
   tries a wider suffix list but only merges into an entity that already
   exists with the same type.

2. merge_entities() — collapses an existing duplicate into a canonical one,
   reassigning mentions/updates/aliases/speaker links, keeping the earliest
   first-seen, recomputing status, and leaving the old name AND old slug as
   aliases so future extractions and old URLs resolve to the survivor.
"""
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from councilhound.db.models import (
    Entity, EntityAlias, EntityMention, EntityProfile, EntityUpdate,
    Meeting, TranscriptChunk,
)

log = logging.getLogger(__name__)

# Safe with zero context: "X Project" is the same thread as "X".
CREATE_STRIP = {"project", "projects"}

# Wider list, only applied when the stripped slug matches an existing entity
# of the same type ("Courthouse Plaza Redevelopment" -> courthouse-plaza).
# "review"/"development" stay out of CREATE_STRIP because they can be
# integral ("Board of Architectural Review" — which resolves by exact slug
# long before any stripping happens, but a fresh name must not be truncated).
RESOLVE_STRIP = CREATE_STRIP | {
    "program", "development", "redevelopment", "update", "updates",
    "review", "process", "zoning", "initiative",
}

_ACRONYM_STOPWORDS = {"and", "of", "the", "for", "a", "an"}


def _strip_acronym_suffix(tokens: list[str]) -> list[str]:
    """['urban','forest','master','plan','ufmp'] -> drop the trailing token
    when it spells the initials of the rest (stopwords skipped)."""
    if len(tokens) < 3 or len(tokens[-1]) < 2:
        return tokens
    initials = "".join(t[0] for t in tokens[:-1] if t not in _ACRONYM_STOPWORDS)
    return tokens[:-1] if tokens[-1] == initials else tokens


def normalize_slug(slug: str) -> str:
    """Create-time canonicalization for non-person slugs (context-free)."""
    tokens = slug.split("-")
    while True:
        stripped = _strip_acronym_suffix(tokens)
        if len(stripped) >= 3 and stripped[-1] in CREATE_STRIP:
            stripped = stripped[:-1]
        if stripped == tokens:
            return "-".join(tokens)
        tokens = stripped


def _is_year_token(token: str) -> bool:
    return (len(token) == 4 and token.isdigit() and token.startswith(("19", "20"))) \
        or (token.startswith("fy") and token[2:].isdigit())


def find_normalized_base(session: Session, entity_type: str, slug: str) -> Entity | None:
    """Strip suffix tokens one at a time; return the first existing entity of
    the same type whose slug matches. Never invents a base that doesn't
    already exist, so integral-word names can't be truncated into nonsense."""
    tokens = slug.split("-")
    while len(tokens) > 2:
        last = tokens[-1]
        stripped = _strip_acronym_suffix(tokens)
        if stripped == tokens:
            if last in RESOLVE_STRIP or _is_year_token(last):
                stripped = tokens[:-1]
            else:
                return None
        tokens = stripped
        base = session.scalar(select(Entity).where(
            Entity.canonical_slug == "-".join(tokens),
            Entity.entity_type == entity_type,
        ))
        if base is not None:
            return base
    return None


def merge_entities(session: Session, source_slug: str, target_slug: str,
                   force_cross_type: bool = False) -> dict:
    """Fold `source` into `target`. Returns a summary of what moved."""
    source = session.scalar(select(Entity).where(Entity.canonical_slug == source_slug))
    target = session.scalar(select(Entity).where(Entity.canonical_slug == target_slug))
    if source is None or target is None:
        raise ValueError(f"unknown slug: {source_slug if source is None else target_slug}")
    if source.id == target.id:
        raise ValueError("source and target are the same entity")
    if source.entity_type != target.entity_type and not force_cross_type:
        raise ValueError(
            f"type mismatch ({source.entity_type} -> {target.entity_type}); "
            "pass force_cross_type to merge anyway")

    moved = {"mentions": 0, "updates": 0, "aliases": 0, "speaker_chunks": 0}

    # mentions: reassign unless the target already has the identical row
    target_mention_keys = {
        (m.meeting_id, m.document_id, m.transcript_chunk_id, m.role)
        for m in session.scalars(select(EntityMention)
                                 .where(EntityMention.entity_id == target.id))
    }
    for m in session.scalars(select(EntityMention)
                             .where(EntityMention.entity_id == source.id)):
        key = (m.meeting_id, m.document_id, m.transcript_chunk_id, m.role)
        if key in target_mention_keys:
            session.delete(m)
        else:
            m.entity_id = target.id
            target_mention_keys.add(key)
            moved["mentions"] += 1

    # updates: one row per (entity, meeting) — target's row wins on conflict
    target_update_meetings = set(session.scalars(
        select(EntityUpdate.meeting_id).where(EntityUpdate.entity_id == target.id)))
    for u in session.scalars(select(EntityUpdate)
                             .where(EntityUpdate.entity_id == source.id)):
        if u.meeting_id in target_update_meetings:
            session.delete(u)
        else:
            u.entity_id = target.id
            target_update_meetings.add(u.meeting_id)
            moved["updates"] += 1

    # aliases are globally unique strings, so reassignment can't collide
    moved["aliases"] = session.execute(
        update(EntityAlias).where(EntityAlias.entity_id == source.id)
        .values(entity_id=target.id)).rowcount
    moved["speaker_chunks"] = session.execute(
        update(TranscriptChunk).where(TranscriptChunk.speaker_entity_id == source.id)
        .values(speaker_entity_id=target.id)).rowcount

    # source profile dies; the target's goes stale via through_meeting_id
    # once newer mentions arrive, and the nightly profile pass regenerates it
    src_profile = session.scalar(select(EntityProfile)
                                 .where(EntityProfile.entity_id == source.id))
    if src_profile is not None:
        session.delete(src_profile)

    _keep_earliest_first_seen(session, source, target)
    session.flush()  # reassignments must land before recompute/delete
    _recompute_status(session, target)

    # old name and old slug keep resolving/linking to the survivor
    from councilhound.entities import add_alias
    add_alias(session, target, source.name)
    add_alias(session, target, source.canonical_slug)
    session.delete(source)
    session.flush()

    log.info("merged %s -> %s: %s", source_slug, target_slug, moved)
    return moved


def _keep_earliest_first_seen(session: Session, source: Entity, target: Entity) -> None:
    if source.first_seen_meeting_id is None:
        return
    if target.first_seen_meeting_id is None:
        target.first_seen_meeting_id = source.first_seen_meeting_id
        return
    dates = {
        m.id: m.meeting_date for m in session.scalars(select(Meeting).where(
            Meeting.id.in_([source.first_seen_meeting_id, target.first_seen_meeting_id])))
    }
    if dates.get(source.first_seen_meeting_id) < dates.get(target.first_seen_meeting_id):
        target.first_seen_meeting_id = source.first_seen_meeting_id


def _recompute_status(session: Session, entity: Entity) -> None:
    latest = session.execute(
        select(EntityUpdate.status_after)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .where(EntityUpdate.entity_id == entity.id,
               EntityUpdate.status_after.isnot(None))
        .order_by(Meeting.meeting_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is not None:
        entity.current_status = latest


def dedupe_pass(session: Session, apply: bool = False) -> list[dict]:
    """Scan existing non-person entities for ones whose normalized slug
    matches another entity of the same type; optionally merge them."""
    proposals = []
    entities = session.scalars(
        select(Entity).where(Entity.entity_type != "person")
        .order_by(Entity.canonical_slug)).all()
    for e in entities:
        create_norm = normalize_slug(e.canonical_slug)
        base = None
        if create_norm != e.canonical_slug:
            base = session.scalar(select(Entity).where(
                Entity.canonical_slug == create_norm,
                Entity.entity_type == e.entity_type))
        if base is None:
            base = find_normalized_base(session, e.entity_type, e.canonical_slug)
        if base is None or base.id == e.id:
            continue
        proposals.append({"source": e.canonical_slug, "target": base.canonical_slug,
                          "entity_type": e.entity_type})
    if apply:
        # longest sources first so chains (x -> y, y -> z) fold x into y
        # before y itself is merged away into z
        for p in sorted(proposals, key=lambda p: len(p["source"]), reverse=True):
            p["moved"] = merge_entities(session, p["source"], p["target"])
        session.commit()
    return proposals
