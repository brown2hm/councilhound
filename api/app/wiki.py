"""Serialize a project's OKF wiki from wiki_pages (mirrored from the
knowledge bundle by okf-push). Both the development router (official slug)
and the entities router (canonical slug) serve the same payload."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, WikiPage

# reading order for concept pages; anything unknown sorts after, alphabetically
_PAGE_ORDER = {name: i for i, name in enumerate(
    ["overview", "history", "positions", "impact", "documents"])}


def generated_at(frontmatter: dict | None) -> str | None:
    """When the page last meaningfully changed: OKF v0.2 `generated.at`, or
    the v0.1 `timestamp` on a page pushed before the bundle migrated (§13.1
    lets a consumer fall back). Kept local rather than imported from
    councilhound.okf.bundle, which needs PyYAML the API image doesn't ship."""
    fm = frontmatter or {}
    gen = fm.get("generated")
    at = gen.get("at") if isinstance(gen, dict) else None
    return at or fm.get("timestamp") or None


def entity_has_wiki(session: Session, entity_id: int | None) -> bool:
    """Concept pages only — matches wiki_payload's 404 condition, so the flag
    never advertises a wiki the wiki routes would 404 on (an entity whose only
    rows are the reserved index/log files has no servable wiki)."""
    if entity_id is None:
        return False
    return session.scalar(
        select(WikiPage.id)
        .where(WikiPage.entity_id == entity_id, WikiPage.kind == "concept")
        .limit(1)) is not None


def wiki_payload(session: Session, entity: Entity) -> dict | None:
    rows = session.scalars(
        select(WikiPage).where(WikiPage.entity_id == entity.id)).all()
    concepts = [r for r in rows if r.kind == "concept"]
    if not concepts:
        return None
    concepts.sort(key=lambda r: (_PAGE_ORDER.get(r.page, len(_PAGE_ORDER)), r.page))
    log_row = next((r for r in rows if r.kind == "log"), None)
    pushed = [r.pushed_at for r in rows if r.pushed_at is not None]
    return {
        "entity_slug": entity.canonical_slug,
        "name": entity.name,
        "pages": [
            {
                "page": r.page,
                "path": r.path,
                "title": (r.frontmatter or {}).get("title") or r.page.capitalize(),
                "type": (r.frontmatter or {}).get("type"),
                "description": (r.frontmatter or {}).get("description"),
                # OKF v0.2 `generated.at`, falling back to the v0.1
                # `timestamp` for pages pushed before the migration (§13.1)
                "timestamp": generated_at(r.frontmatter),
                "generated": (r.frontmatter or {}).get("generated"),
                "frontmatter": r.frontmatter or {},
                "body": r.body,
            }
            for r in concepts
        ],
        "log": log_row.body if log_row else None,
        "pushed_at": max(pushed).isoformat() if pushed else None,
    }
