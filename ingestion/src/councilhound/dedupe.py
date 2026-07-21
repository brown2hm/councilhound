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

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from councilhound.db.models import (
    CityProject, Entity, EntityAlias, EntityGeocode, EntityMention,
    EntityProfile, EntityUpdate, Meeting, TopicSubscription, TranscriptChunk,
    WikiPage,
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

# Token-level spelling drift observed in the July 2026 audit: the same street
# or phrase slugs differently depending on which document named it
# ("Blenheim Blvd" vs "Blenheim Boulevard", "drive-thru" vs "drive-through").
# Values may be multi-token ("masterplan" -> "master plan"). Deliberately
# conservative: no "st" (Saint) or "dr" (Doctor) expansion.
_TOKEN_CANON: dict[str, tuple[str, ...]] = {
    "blvd": ("boulevard",),
    "ave": ("avenue",),
    "rd": ("road",),
    "thru": ("through",),
    "masterplan": ("master", "plan"),
}

# A "Draft X" / "Proposed X" is the same tracked thread as X — the tracker
# follows the matter, not each revision of its paperwork.
_LEADING_STRIP = {"draft", "proposed"}


def _canonical_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        out.extend(_TOKEN_CANON.get(t, (t,)))
    while len(out) > 2 and out[0] in _LEADING_STRIP:
        out = out[1:]
    return out


def _strip_acronym_suffix(tokens: list[str]) -> list[str]:
    """['urban','forest','master','plan','ufmp'] -> drop the trailing token
    when it spells the initials of the rest (stopwords skipped)."""
    if len(tokens) < 3 or len(tokens[-1]) < 2:
        return tokens
    initials = "".join(t[0] for t in tokens[:-1] if t not in _ACRONYM_STOPWORDS)
    return tokens[:-1] if tokens[-1] == initials else tokens


def normalize_slug(slug: str) -> str:
    """Create-time canonicalization for non-person slugs (context-free)."""
    tokens = _canonical_tokens(slug.split("-"))
    while True:
        stripped = _strip_acronym_suffix(tokens)
        if len(stripped) >= 3 and stripped[-1] in CREATE_STRIP:
            stripped = stripped[:-1]
        if stripped == tokens:
            break
        tokens = stripped
    # trailing position only: "X Improvement (Project)" == "X Improvements",
    # but mid-name phrases ("Capital Improvement Program") must not mutate
    if len(tokens) >= 3 and tokens[-1] == "improvement":
        tokens = tokens[:-1] + ["improvements"]
    return "-".join(tokens)


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

    # official city-project link: the record must keep pointing at the
    # surviving thread (entity_id is unique — target's own link wins)
    target_linked = session.scalar(select(CityProject)
                                   .where(CityProject.entity_id == target.id))
    for cp in session.scalars(select(CityProject)
                              .where(CityProject.entity_id == source.id)):
        if target_linked is None:
            cp.entity_id = target.id
            target_linked = cp
        else:
            cp.entity_id = None

    # geocode: keep the source's fix if the target has none
    target_geo = session.scalar(select(EntityGeocode)
                                .where(EntityGeocode.entity_id == target.id))
    src_geo = session.scalar(select(EntityGeocode)
                             .where(EntityGeocode.entity_id == source.id))
    if src_geo is not None:
        if target_geo is None or (target_geo.status == "miss" and src_geo.status == "ok"):
            if target_geo is not None:
                session.delete(target_geo)
                session.flush()
            src_geo.entity_id = target.id
        else:
            session.delete(src_geo)

    # wiki pages: keep the source's bundle pages unless the target already
    # has its own (the OKF bundle reconciles paths on the next push)
    if session.scalar(select(WikiPage).where(WikiPage.entity_id == target.id)) is None:
        moved["wiki_pages"] = session.execute(
            update(WikiPage).where(WikiPage.entity_id == source.id)
            .values(entity_id=target.id)).rowcount

    # followers of the folded thread keep following the survivor
    target_subs = {s.email for s in session.scalars(
        select(TopicSubscription).where(TopicSubscription.entity_id == target.id))}
    for sub in session.scalars(select(TopicSubscription)
                               .where(TopicSubscription.entity_id == source.id)):
        if sub.email in target_subs:
            session.delete(sub)
        else:
            sub.entity_id = target.id

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


def _rename_to_canonical(session: Session, entity: Entity, canon: str) -> None:
    """Move an entity onto its canonical slug, leaving the old slug as an
    alias so existing URLs and future extractions still resolve."""
    from councilhound.entities import add_alias
    old = entity.canonical_slug
    entity.canonical_slug = canon
    session.flush()
    add_alias(session, entity, old)
    log.info("canonicalized slug %s -> %s", old, canon)


def dedupe_pass(session: Session, apply: bool = False) -> list[dict]:
    """Scan existing non-person entities: merge ones whose normalized slug
    matches another entity of the same type, and re-slug ones whose
    canonical form isn't taken (so future phrasing drift converges on them).
    When applying, each action executes before the next entity is examined,
    so chains resolve (a rename creates the target the next merge folds
    into). Dry-run reports against current state only."""
    actions = []
    slugs = session.scalars(
        select(Entity.canonical_slug).where(Entity.entity_type != "person")
        .order_by(Entity.canonical_slug)).all()
    for slug in slugs:
        e = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
        if e is None:  # already merged away earlier in this pass
            continue
        create_norm = normalize_slug(e.canonical_slug)
        base = None
        if create_norm != e.canonical_slug:
            candidate = _entity_by_slug_or_alias(session, create_norm)
            if candidate is not None and candidate.entity_type == e.entity_type:
                base = candidate
        if base is None:
            base = find_normalized_base(session, e.entity_type, create_norm)
        if base is not None and base.id != e.id:
            action = {"action": "merge", "source": e.canonical_slug,
                      "target": base.canonical_slug, "entity_type": e.entity_type}
        elif base is None and create_norm != e.canonical_slug:
            # the canonical slug may be held by an entity of ANOTHER type
            # (canonical_slug is globally unique) — renaming into it would
            # violate the constraint, and cross-type auto-merges are off
            # the table, so leave such entities where they are
            if session.scalar(select(Entity).where(
                    Entity.canonical_slug == create_norm)) is not None:
                continue
            action = {"action": "rename", "source": e.canonical_slug,
                      "target": create_norm, "entity_type": e.entity_type}
        else:
            continue
        if apply:
            # savepoint per action: one surprising conflict must not sink
            # the rest of the pass (or the nightly job it runs in)
            try:
                with session.begin_nested():
                    if action["action"] == "merge":
                        action["moved"] = merge_entities(session, e.canonical_slug,
                                                         action["target"])
                    else:
                        _rename_to_canonical(session, e, action["target"])
            except Exception as exc:
                log.exception("dedupe action failed: %s", action)
                action["error"] = str(exc)
        actions.append(action)
    if apply:
        session.commit()
    return actions


def _entity_by_slug_or_alias(session: Session, slug: str) -> Entity | None:
    entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
    if entity is not None:
        return entity
    alias = session.scalar(select(EntityAlias)
                           .where(func.lower(EntityAlias.alias) == slug.lower()))
    return session.get(Entity, alias.entity_id) if alias else None


def merge_batch(session: Session, entries: list[dict], apply: bool = False) -> list[dict]:
    """Apply a curated merge list: [{"source": slug, "target": slug,
    "force_cross_type": bool?, "note": str?}, ...]. Idempotent — a source
    whose slug already aliases the target reports 'already-merged', and
    missing slugs are skipped with a warning, so re-runs are safe."""
    results = []
    for entry in entries:
        src_slug, dst_slug = entry["source"], entry["target"]
        outcome = {"source": src_slug, "target": dst_slug}
        source = _entity_by_slug_or_alias(session, src_slug)
        target = _entity_by_slug_or_alias(session, dst_slug)
        if target is None:
            outcome["result"] = "skipped: target not found"
        elif source is None:
            outcome["result"] = "skipped: source not found"
        elif source.id == target.id:
            outcome["result"] = "already-merged"
        elif not apply:
            outcome["result"] = "would merge"
        else:
            try:
                moved = merge_entities(session, source.canonical_slug,
                                       target.canonical_slug,
                                       force_cross_type=bool(entry.get("force_cross_type")))
                outcome["result"] = f"merged {moved}"
            except ValueError as exc:
                session.rollback()
                outcome["result"] = f"error: {exc}"
        results.append(outcome)
    if apply:
        session.commit()
    return results
