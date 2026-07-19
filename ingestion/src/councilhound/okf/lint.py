"""OKF v0.1 conformance + house rules for the knowledge bundle.

Spec conformance: every non-reserved .md parses YAML frontmatter with a
non-empty `type`; reserved index.md/log.md carry no frontmatter. House
rules: root-absolute links resolve inside the bundle, {{metric:...}} markers
are well-formed, and (when a DB session is supplied) metric keys resolve
against the project's synthesized evaluation."""
import os

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import CityProject, Entity, ProjectEvaluation
from councilhound.okf.bundle import (
    RESERVED,
    bundle_links,
    markers,
    parse_page,
    slugify,
    walk_pages,
)


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


def lint_bundle(bundle_dir: str, session: Session | None = None) -> list[str]:
    """Returns human-readable problems; empty list means conformant."""
    problems: list[str] = []
    if not os.path.isdir(bundle_dir):
        return [f"bundle dir does not exist: {bundle_dir}"]
    pages = walk_pages(bundle_dir)
    known_paths = {"/" + rel for rel, _ in pages}
    metric_cache: dict[str, set[str] | None] = {}

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
