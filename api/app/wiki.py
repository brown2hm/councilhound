"""Serialize a project's OKF wiki from wiki_pages (mirrored from the
knowledge bundle by okf-push). Both the development router (official slug)
and the entities router (canonical slug) serve the same payload."""
from datetime import datetime, timezone

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


def _instant(value) -> datetime | None:
    """An ISO 8601 string (or a date-only legacy stamp) as an aware UTC
    datetime; None when it will not parse."""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def trust_block(frontmatter: dict | None, now: datetime | None = None) -> dict:
    """The consumer-side reading of the OKF v0.2 trust and lifecycle
    families (§5.2–5.5), derived here once so both wiki routes and the
    frontend agree on it:

    - producer_kind from `generated.by` under the actor convention (§7):
      `process:` is the deterministic pipeline, `human:` a person, anything
      else (`<producer>/<version>`) the LLM curator;
    - tier from `verified` (§5.3): unverified, machine-confirmed, or
      human-reviewed — a bare mapping counts as a one-element list;
    - edited_since_review when the content changed after the latest
      confirmation (§5.2 keeps the two independent);
    - stale when now >= `stale_after` (§5.5)."""
    fm = frontmatter or {}
    now = now or datetime.now(timezone.utc)
    gen = fm.get("generated")
    producer = gen.get("by") if isinstance(gen, dict) else None
    if not producer:
        kind = None
    elif str(producer).startswith("process:"):
        kind = "pipeline"
    elif str(producer).startswith("human:"):
        kind = "human"
    else:
        kind = "curator"

    raw = fm.get("verified")
    events = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    events = [e for e in events if isinstance(e, dict) and _instant(e.get("at"))]
    latest = max(events, key=lambda e: _instant(e["at"])) if events else None
    if any(str(e.get("by", "")).startswith("human:") for e in events):
        tier = "human-reviewed"
    else:
        tier = "machine-confirmed" if events else "unverified"

    changed_at = _instant(generated_at(fm))
    verified_at = _instant(latest["at"]) if latest else None
    stale_after = _instant(fm.get("stale_after"))
    return {
        "producer": producer,
        "producer_kind": kind,
        "tier": tier,
        "verified_by": latest.get("by") if latest else None,
        "verified_at": latest["at"] if latest else None,
        "edited_since_review": bool(
            verified_at and changed_at and changed_at > verified_at),
        "stale_after": fm.get("stale_after"),
        "stale": bool(stale_after and now >= stale_after),
    }


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
                "trust": trust_block(r.frontmatter),
                "frontmatter": r.frontmatter or {},
                "body": r.body,
            }
            for r in concepts
        ],
        "log": log_row.body if log_row else None,
        "pushed_at": max(pushed).isoformat() if pushed else None,
    }
