"""Mirror the OKF bundle into wiki_pages so the cloud API can serve it —
the okf sibling of impact-push. Upserts by path on content-hash change,
deletes rows whose file left the bundle, and skips project directories whose
entity no longer exists (merged/renamed slugs surface in the summary rather
than failing the push).

A directory name is resolved the same way the API resolves a URL slug:
canonical_slug first, then EntityAlias — dedupe leaves the old slug behind as
an alias when it renames an entity, so a bundle seeded before a rename still
lands. A directory that resolves to nothing is skipped, and its presence
suppresses the delete pass entirely for that run: if we can't identify pages
that are in the bundle, we can't tell a renamed project from a removed one,
and dropping a live wiki out from under the API is the worse error."""
import datetime
import logging
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, EntityAlias, WikiPage
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


def _entity_ids_by_slug(session: Session) -> dict[str, int]:
    """Canonical slugs plus old slugs left behind as aliases (dedupe adds the
    previous slug as an alias on rename). Canonical always wins."""
    by_slug = {alias.lower(): eid for eid, alias in session.execute(
        select(EntityAlias.entity_id, func.lower(EntityAlias.alias)))}
    by_slug.update({slug: eid for eid, slug in session.execute(
        select(Entity.id, Entity.canonical_slug))})
    return by_slug


def push_bundle(session: Session, bundle_dir: str) -> dict:
    rows = {p.path: p for p in session.scalars(select(WikiPage))}
    entities = _entity_ids_by_slug(session)

    created = updated = unchanged = orphaned = 0
    seen: set[str] = set()
    orphan_dirs: set[str] = set()
    for rel, path in walk_pages(bundle_dir):
        with open(path, encoding="utf-8") as f:
            text = f.read()

        entity_id = None
        parts = rel.split("/")
        if parts[0] == "projects" and len(parts) == 3:
            entity_id = entities.get(parts[1]) or entities.get(parts[1].lower())
            if entity_id is None:
                orphaned += 1
                orphan_dirs.add(parts[1])
                log.warning("skipping %s: no entity with slug or alias %s",
                            rel, parts[1])
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

    # A row is deleted only because its file left the bundle. An orphan
    # directory means we could not identify pages that ARE in the bundle, so
    # "left the bundle" is no longer a safe inference for anything — a renamed
    # entity looks exactly like a deleted one from here. Skip the whole delete
    # pass and let the next clean push reclaim the strays: a stale row serves
    # content that the next push corrects, a wrong delete 404s a live wiki.
    deleted = retained = 0
    stale = [row for path, row in rows.items() if path not in seen]
    if orphan_dirs:
        retained = len(stale)
        log.warning("skipping %d deletion(s): %d unresolvable directory/ies "
                    "(%s) make bundle membership unreliable this run",
                    retained, len(orphan_dirs), ", ".join(sorted(orphan_dirs)))
    else:
        for row in stale:
            session.delete(row)
            deleted += 1

    session.commit()
    return {"created": created, "updated": updated, "unchanged": unchanged,
            "deleted": deleted, "orphaned": orphaned, "retained": retained}
