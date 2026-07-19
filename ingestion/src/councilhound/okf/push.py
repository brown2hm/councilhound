"""Mirror the OKF bundle into wiki_pages so the cloud API can serve it —
the okf sibling of impact-push. Upserts by path on content-hash change,
deletes rows whose file left the bundle, and skips project directories whose
entity no longer exists (merged/renamed slugs surface in the summary rather
than failing the push)."""
import datetime
import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, WikiPage
from councilhound.okf.bundle import content_hash, parse_page, walk_pages

log = logging.getLogger(__name__)


def _classify(rel: str) -> tuple[str, str]:
    name = os.path.basename(rel)
    page = name.removesuffix(".md")
    kind = {"index.md": "index", "log.md": "log"}.get(name, "concept")
    return kind, page


def _jsonable(value):
    """YAML happily parses unquoted dates in hand-edited frontmatter into
    date objects the JSON column can't store — normalize to ISO strings."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def push_bundle(session: Session, bundle_dir: str) -> dict:
    rows = {p.path: p for p in session.scalars(select(WikiPage))}
    entities = {slug: eid for eid, slug in session.execute(
        select(Entity.id, Entity.canonical_slug))}

    created = updated = unchanged = orphaned = 0
    seen: set[str] = set()
    for rel, path in walk_pages(bundle_dir):
        with open(path, encoding="utf-8") as f:
            text = f.read()

        entity_id = None
        parts = rel.split("/")
        if parts[0] == "projects" and len(parts) == 3:
            entity_id = entities.get(parts[1])
            if entity_id is None:
                orphaned += 1
                log.warning("skipping %s: no entity with slug %s", rel, parts[1])
                continue

        seen.add(rel)
        digest = content_hash(text)
        row = rows.get(rel)
        if row is not None and row.content_hash == digest:
            unchanged += 1
            continue

        frontmatter, body = parse_page(text)
        kind, page = _classify(rel)
        if row is None:
            row = WikiPage(path=rel)
            session.add(row)
            created += 1
        else:
            updated += 1
        row.entity_id = entity_id
        row.kind = kind
        row.page = page
        row.frontmatter = _jsonable(frontmatter)
        row.body = body
        row.content_hash = digest

    deleted = 0
    for path, row in rows.items():
        if path not in seen:
            session.delete(row)
            deleted += 1

    session.commit()
    return {"created": created, "updated": updated, "unchanged": unchanged,
            "deleted": deleted, "orphaned": orphaned}
