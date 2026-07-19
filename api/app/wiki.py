"""Serialize a project's OKF wiki from wiki_pages (mirrored from the
knowledge bundle by okf-push). Both the development router (official slug)
and the entities router (canonical slug) serve the same payload."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, WikiPage

# reading order for concept pages; anything unknown sorts after, alphabetically
_PAGE_ORDER = {name: i for i, name in enumerate(
    ["overview", "history", "positions", "impact"])}


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
                "timestamp": (r.frontmatter or {}).get("timestamp"),
                "frontmatter": r.frontmatter or {},
                "body": r.body,
            }
            for r in concepts
        ],
        "log": log_row.body if log_row else None,
        "pushed_at": max(pushed).isoformat() if pushed else None,
    }
