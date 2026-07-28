"""OKF v0.1 conformance + house rules for the knowledge bundle.

Spec conformance: every non-reserved .md parses YAML frontmatter with a
non-empty `type`; reserved index.md/log.md carry no frontmatter. House
rules: root-absolute links resolve inside the bundle, {{metric:...}} markers
are well-formed, and (when a DB session is supplied) metric keys resolve
against the project's synthesized evaluation and every link out to the
public site points at a page that actually exists."""
import os

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import (
    CityProject,
    Entity,
    EntityAlias,
    ProjectEvaluation,
)
from councilhound.okf.bundle import (
    RESERVED,
    bundle_links,
    markers,
    parse_page,
    site_links,
    slugify,
    walk_pages,
)
from councilhound.config import SITE_BASE_URL

# Site paths that are real routes rather than a slug lookup.
STATIC_SITE_PATHS = {("development", "methods")}


def _metric_keys(session: Session, project_slug: str) -> set[str] | None:
    """Marker vocabulary for one project; None when it has no synthesized
    evaluation (any metric marker is then an error)."""
    evaluation = session.scalar(
        select(ProjectEvaluation)
        .join(CityProject, ProjectEvaluation.city_project_id == CityProject.id)
        .join(Entity, CityProject.entity_id == Entity.id)
        .where(Entity.canonical_slug == project_slug,
               ProjectEvaluation.status == "synthesized"))
    if evaluation is None:
        return None
    return {slugify(m["name"])
            for mr in evaluation.module_results or []
            for m in mr.get("metrics", [])}


def _site_slugs(session: Session) -> dict[str, set[str]]:
    """Valid slugs per public route.

    Each route resolves differently, and the linter has to mirror the ROUTE
    rather than the data model — otherwise it reports the wrong thing in both
    directions. /members matches canonical_slug on a person only
    (api/app/routers/members.py:135, no alias fallback), so an alias that
    resolves fine through /entities still 404s in a browser. /topics goes
    through the alias-following _resolve_entity, so aliases are legitimate
    there. /development keys on CityProject.external_slug, a different
    namespace from entity slugs entirely."""
    people = set(session.scalars(
        select(Entity.canonical_slug).where(Entity.entity_type == "person")))
    entities = set(session.scalars(select(Entity.canonical_slug)))
    aliases = set(session.scalars(select(func.lower(EntityAlias.alias))))
    projects = set(session.scalars(select(CityProject.external_slug)))
    return {"members": people, "topics": entities | aliases,
            "development": projects}


def lint_bundle(bundle_dir: str, session: Session | None = None) -> list[str]:
    """Returns human-readable problems; empty list means conformant."""
    problems: list[str] = []
    if not os.path.isdir(bundle_dir):
        return [f"bundle dir does not exist: {bundle_dir}"]
    pages = walk_pages(bundle_dir)
    known_paths = {"/" + rel for rel, _ in pages}
    metric_cache: dict[str, set[str] | None] = {}
    site_slugs = _site_slugs(session) if session is not None else None

    for rel, path in pages:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        name = os.path.basename(rel)
        try:
            frontmatter, body = parse_page(text)
        except yaml.YAMLError as exc:
            problems.append(f"{rel}: frontmatter is not valid YAML ({exc})")
            continue

        if name in RESERVED:
            if frontmatter is not None:
                problems.append(f"{rel}: reserved file must not carry frontmatter")
        else:
            if frontmatter is None:
                problems.append(f"{rel}: missing YAML frontmatter")
            elif not str(frontmatter.get("type") or "").strip():
                problems.append(f"{rel}: frontmatter `type` is missing or empty")

        for link in bundle_links(body):
            if link not in known_paths:
                problems.append(f"{rel}: bundle link {link} does not resolve")

        if site_slugs is not None:
            # the `resource` URI is as user-facing as any body link
            resource = str((frontmatter or {}).get("resource") or "")
            for section, slug in site_links(f"{body}\n{resource}", SITE_BASE_URL):
                if (section, slug) in STATIC_SITE_PATHS:
                    continue
                if slug not in site_slugs[section]:
                    problems.append(
                        f"{rel}: /{section}/{slug} is not a valid "
                        f"{section} page")

        page_markers = markers(body)
        if page_markers and session is not None and rel.startswith("projects/"):
            slug = rel.split("/")[1]
            if slug not in metric_cache:
                metric_cache[slug] = _metric_keys(session, slug)
            keys = metric_cache[slug]
            for kind, key in page_markers:
                if kind != "metric":
                    continue
                if keys is None:
                    problems.append(
                        f"{rel}: metric marker '{key}' but no synthesized "
                        "evaluation exists for this project")
                elif key not in keys:
                    problems.append(f"{rel}: metric marker '{key}' does not "
                                    "match any evaluation metric")
    return problems
