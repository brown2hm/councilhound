"""
Entity resolution shared by seeding (Phase 3 setup) and the LLM structuring
pass. The LLM never invents canonical slugs — names are resolved here:
exact slug match, then alias table, then create. This is what keeps
"Mayor Read", "Catherine S. Read" and "Catherine Read" one entity.
"""
import logging
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, EntityAlias

log = logging.getLogger(__name__)

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _name_tokens(name: str) -> list[str]:
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[,.]", " ", name)
    return [t for t in name.split() if t]


def display_name(name: str) -> str:
    """'Catherine S. Read' -> 'Catherine Read'; 'D. Thomas Ross' -> 'Thomas Ross';
    'Jon R. Stehle, Jr.' -> 'Jon Stehle Jr.'. Single-letter initials dropped."""
    tokens = [t for t in _name_tokens(name) if len(t) > 1 or t.lower() in _SUFFIXES]
    return " ".join(tokens)


def slugify(name: str) -> str:
    tokens = _name_tokens(display_name(name))
    # leading articles don't identify anything: 'the George Snyder Trail'
    # and 'George Snyder Trail' must be one entity
    while tokens and tokens[0].lower() in ("the", "a", "an"):
        tokens.pop(0)
    slug = "-".join(tokens).lower()
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def add_alias(session: Session, entity: Entity, alias: str) -> None:
    """Register an alias unless it's taken. Collisions (two people sharing a
    last name) are skipped — ambiguous aliases must not resolve to anyone."""
    alias = alias.strip()
    if not alias:
        return
    existing = session.scalar(
        select(EntityAlias).where(func.lower(EntityAlias.alias) == alias.lower())
    )
    if existing is None:
        session.add(EntityAlias(entity_id=entity.id, alias=alias))
        session.flush()
    elif existing.entity_id != entity.id:
        log.warning("alias %r already points to entity %s; not adding for %s",
                    alias, existing.entity_id, entity.canonical_slug)


def resolve_entity(
    session: Session,
    entity_type: str,
    name: str,
    create: bool = True,
    first_seen_meeting_id: int | None = None,
) -> Entity | None:
    """Resolve a name to an Entity: slug match -> alias match ->
    normalized-base match (non-persons) -> create."""
    from councilhound.dedupe import find_normalized_base, normalize_slug

    slug = slugify(name)
    if slug and entity_type != "person":
        # "X Project" / acronym twins canonicalize to the base slug
        slug = normalize_slug(slug)
    if not slug:
        return None
    entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
    if entity:
        return entity
    for candidate in (name, display_name(name)):
        alias = session.scalar(
            select(EntityAlias).where(func.lower(EntityAlias.alias) == candidate.strip().lower())
        )
        if alias:
            return session.get(Entity, alias.entity_id)
    if entity_type != "person":
        base = find_normalized_base(session, entity_type, slug)
        if base is not None:
            add_alias(session, base, name)
            return base
    if not create:
        return None
    entity = Entity(
        entity_type=entity_type,
        name=display_name(name),
        canonical_slug=slug,
        first_seen_meeting_id=first_seen_meeting_id,
    )
    session.add(entity)
    session.flush()
    add_alias(session, entity, name)
    add_alias(session, entity, display_name(name))
    return entity
