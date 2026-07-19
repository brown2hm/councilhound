"""Render the OKF bundle from the DB.

seed_bundle creates a project's wiki directory once — curator-owned pages
(overview/positions/impact) are drafted from the existing profile, official
record, and synthesized evaluation, then never touched again by this module.
refresh_bundle is the deterministic nightly pass: it regenerates only
pipeline-owned artifacts (history.md, index.md files, status frontmatter on
overview.md) so re-running it against unchanged data is a no-op."""
import logging
import os
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.config import GRANICUS_BASE_URL, SITE_BASE_URL
from councilhound.db.models import (
    AgendaItem,
    CityProject,
    Entity,
    EntityProfile,
    EntityUpdate,
    Meeting,
    ProjectEvaluation,
    Vote,
)
from councilhound.okf.bundle import (
    PAGE_ORDER,
    append_log,
    read_page,
    render_index,
    slugify,
    write_page,
    write_text,
)

log = logging.getLogger(__name__)

PIPELINE_NOTE = ("<!-- Pipeline-owned page: regenerated from the meeting "
                 "record. Edits here will be overwritten. -->")
CURATED_NOTE = ("<!-- Curator-owned page: updated incrementally as new "
                "meetings land. Human edits are preserved. -->")

# overview.md frontmatter keys the deterministic refresh may rewrite; body
# and every other key belong to the curator/humans
REFRESHED_KEYS = {"status", "tags", "evaluation_status"}


def _clip_link(view_id: str, clip_id: str | None,
               start_seconds: float | int | None = None) -> str | None:
    # same params as api/app/links.py — the city's own player, both player
    # generations' seek params
    if not clip_id:
        return None
    url = f"{GRANICUS_BASE_URL}/MediaPlayer.php?view_id={view_id}&clip_id={clip_id}"
    if start_seconds is not None:
        url += f"&starttime={int(start_seconds)}&entrytime={int(start_seconds)}"
    return url


def wiki_candidates(session: Session, slugs: list[str] | None = None) -> list[Entity]:
    """Project entities that merit a wiki: linked to an official record, or
    meeting-derived with enough of a timeline to have a profile."""
    n_updates = (
        select(EntityUpdate.entity_id, func.count().label("n"))
        .group_by(EntityUpdate.entity_id).subquery()
    )
    q = (
        select(Entity)
        .outerjoin(CityProject, CityProject.entity_id == Entity.id)
        .outerjoin(n_updates, n_updates.c.entity_id == Entity.id)
        .where(Entity.entity_type == "project")
        .where((CityProject.id.isnot(None)) | (n_updates.c.n >= 2))
        .order_by(Entity.canonical_slug)
    )
    if slugs:
        q = q.where(Entity.canonical_slug.in_(slugs))
    return list(session.scalars(q).unique())


def _project_context(session: Session, entity: Entity) -> dict:
    city = session.scalar(select(CityProject).where(CityProject.entity_id == entity.id))
    evaluation = None
    if city:
        evaluation = session.scalar(
            select(ProjectEvaluation)
            .where(ProjectEvaluation.city_project_id == city.id,
                   ProjectEvaluation.status == "synthesized"))
    profile = session.scalar(
        select(EntityProfile).where(EntityProfile.entity_id == entity.id))
    timeline = session.execute(
        select(EntityUpdate, Meeting, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id == entity.id)
        .order_by(Meeting.meeting_date, Meeting.id)
    ).all()
    return {"city": city, "evaluation": evaluation, "profile": profile,
            "timeline": timeline}


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    head = text.strip().split(". ")[0].strip()
    return head if head.endswith(".") else head + "."


def _resource_url(entity: Entity, city: CityProject | None) -> str:
    if city:
        return f"{SITE_BASE_URL}/development/{city.external_slug}"
    return f"{SITE_BASE_URL}/topics/{entity.canonical_slug}"


def _tags(entity: Entity, city: CityProject | None) -> list[str]:
    raw = [city.project_type if city else None,
           city.division if city else None,
           entity.current_status or (city.official_status if city else None)]
    return [slugify(t) for t in raw if t]


def _overview_frontmatter(entity: Entity, ctx: dict, stamp: str) -> dict:
    city = ctx["city"]
    fm: dict = {
        "type": "development-project",
        "title": entity.name,
        "description": _first_sentence(
            ctx["profile"].summary if ctx["profile"] else None)
        or _first_sentence(city.description if city else None)
        or f"{entity.name}, tracked from City of Fairfax public meetings.",
        "resource": _resource_url(entity, city),
        "tags": _tags(entity, city),
        "timestamp": stamp,
        "status": entity.current_status or (city.official_status if city else None),
        "source": "official" if city else "meetings",
    }
    if city:
        fm.update({
            "address": city.address,
            "applicant": city.applicant,
            "city_detail_url": city.detail_url,
            "evaluation_status": ctx["evaluation"].status if ctx["evaluation"] else None,
        })
        if city.lat is not None and city.lng is not None:
            fm.update({"lat": float(city.lat), "lng": float(city.lng)})
    return {k: v for k, v in fm.items() if v not in (None, "", [])}


def _overview_body(entity: Entity, ctx: dict) -> str:
    city, profile = ctx["city"], ctx["profile"]
    parts = [CURATED_NOTE, ""]
    if profile and profile.summary:
        parts += [profile.summary.strip(), ""]
    if city:
        parts += ["## Official record", ""]
        if city.description:
            parts += [city.description.strip(), ""]
        facts = [f"- **Requests:** {city.requests.strip()}" if city.requests else None,
                 f"- **Address:** {city.address}" if city.address else None,
                 f"- **Applicant:** {city.applicant}" if city.applicant else None,
                 f"- **Division:** {city.division}" if city.division else None,
                 f"- [City record]({city.detail_url})"]
        parts += [f for f in facts if f] + [""]
    slug = entity.canonical_slug
    parts += ["## In this wiki", ""]
    if ctx["timeline"]:
        parts += [f"- [Meeting history](/projects/{slug}/history.md) — every action, "
                  "vote, and update, with links to the moment in the meeting video"]
    parts += [f"- [Positions & open questions](/projects/{slug}/positions.md)"]
    if ctx["evaluation"]:
        parts += [f"- [Impact analysis](/projects/{slug}/impact.md) — screening "
                  "estimates with assumptions and ranges"]
    return "\n".join(parts)


def _history_page(entity: Entity, ctx: dict,
                  votes: dict[int, list[Vote]]) -> tuple[dict, str] | None:
    timeline = ctx["timeline"]
    if not timeline:
        return None
    latest = timeline[-1][1].meeting_date.isoformat()
    fm = {
        "type": "project-history",
        "title": f"{entity.name} — meeting history",
        "description": f"Dated record of every meeting action on {entity.name}, "
                       f"through {latest}.",
        "resource": _resource_url(entity, ctx["city"]),
        "timestamp": latest,
    }
    parts = [PIPELINE_NOTE, ""]
    # one update per meeting (unique constraint), oldest first
    for update, meeting, item in timeline:
        parts.append(f"## {meeting.meeting_date.isoformat()} — {meeting.title}")
        parts.append("")
        if item:
            line = f"**Agenda item {item.label}**"
            if item.title:
                line += f": {item.title}"
            watch = (_clip_link(meeting.granicus_view_id, meeting.granicus_clip_id,
                                item.start_seconds)
                     if item.start_seconds is not None else None)
            if watch:
                line += f" ([watch the moment]({watch}))"
            parts.append(line)
            if item.outcome:
                parts.append(f"- Outcome: {item.outcome}")
            for v in votes.get(item.id, []):
                breakdown = ", ".join(
                    f"{who}: {how}" for who, how in (v.vote_breakdown or {}).items())
                parts.append(f"- Vote ({v.motion_result}): {v.description}"
                             + (f" — {breakdown}" if breakdown else ""))
        parts.append(f"- {update.update_text}")
        if update.status_after:
            parts.append(f"- Status after: **{update.status_after}**")
        parts.append("")
    return fm, "\n".join(parts)


def _history_votes(session: Session, ctx: dict) -> dict[int, list[Vote]]:
    item_ids = [item.id for _, _, item in ctx["timeline"] if item is not None]
    votes: dict[int, list[Vote]] = {}
    if item_ids:
        for v in session.scalars(select(Vote).where(Vote.agenda_item_id.in_(item_ids))
                                 .order_by(Vote.id)):
            votes.setdefault(v.agenda_item_id, []).append(v)
    return votes


def _positions_body(ctx: dict) -> str:
    profile = ctx["profile"]
    parts = [CURATED_NOTE, ""]
    open_questions = (profile.open_questions or []) if profile else []
    commentary = (profile.member_commentary or []) if profile else []
    parts += ["## Open questions", ""]
    parts += [f"- {q}" for q in open_questions] or \
        ["_No unresolved questions recorded._"]
    parts += ["", "## Member commentary", ""]
    if commentary:
        for entry in commentary:
            name = entry.get("member", "")
            member_slug = entry.get("slug")
            label = f"[{name}]({SITE_BASE_URL}/members/{member_slug})" \
                if member_slug else f"**{name}**"
            parts.append(f"- {label} — {entry.get('summary', '')}")
    else:
        parts.append("_No recorded member positions yet._")
    return "\n".join(parts)


def _impact_body(entity: Entity, ctx: dict) -> str | None:
    evaluation, city = ctx["evaluation"], ctx["city"]
    if not evaluation or not city:
        return None
    analysis_url = f"{SITE_BASE_URL}/development/{city.external_slug}"
    parts = [
        CURATED_NOTE, "",
        f"Screening-level estimates of the economic and fiscal effects of "
        f"{entity.name}. Figures are decision-support context with named "
        f"assumptions and sensitivity ranges — not predictions. The "
        f"[full analysis]({analysis_url}) has the interactive assumptions "
        f"panel and maps; [methods]({SITE_BASE_URL}/development/methods) "
        "documents every formula.", "",
        "## Headline estimates", "",
    ]
    seen = set()
    for module_result in evaluation.module_results or []:
        for m in module_result.get("metrics", []):
            if not m.get("headline"):
                continue
            key = slugify(m["name"])
            if key in seen:
                continue
            seen.add(key)
            line = f"- {{{{metric:{key}}}}}"
            if m.get("method"):
                line += f" — {m['method']}"
            parts.append(line)
    # method notes carry literal figures from the deterministic run, so they
    # stay on the analysis page (always current) rather than in wiki prose
    parts += ["", f"Method notes, caveats, and non-headline metrics live on the "
                  f"[analysis page]({analysis_url})."]
    return "\n".join(parts)


def _narrative_stamp(ctx: dict) -> str:
    """Last meaningful change for seeded narrative pages: the latest meeting
    on the timeline (falls back to today for record-only projects)."""
    if ctx["timeline"]:
        return ctx["timeline"][-1][1].meeting_date.isoformat()
    return date.today().isoformat()


def _project_index(entity: Entity, existing_pages: list[str]) -> str:
    slug = entity.canonical_slug
    described = {
        "overview": "what this project is and where it stands",
        "history": "the dated meeting record",
        "positions": "member positions and open questions",
        "impact": "screening-level impact estimates",
    }
    entries = [(f"/projects/{slug}/{p}.md", p.capitalize(), described.get(p, ""))
               for p in PAGE_ORDER if f"{p}.md" in existing_pages]
    return render_index(entity.name, entries)


def _write_history(session: Session, bundle_dir: str, entity: Entity,
                   ctx: dict) -> bool:
    page = _history_page(entity, ctx, _history_votes(session, ctx))
    if page is None:
        return False
    fm, body = page
    return write_page(bundle_dir, f"projects/{entity.canonical_slug}/history.md",
                      fm, body)


def _refresh_overview_frontmatter(bundle_dir: str, entity: Entity, ctx: dict) -> bool:
    """Rewrite only the pipeline-owned keys of overview.md, preserving the
    curator/human-owned body and any other frontmatter."""
    rel = f"projects/{entity.canonical_slug}/overview.md"
    page = read_page(os.path.join(bundle_dir, rel))
    if page is None or page[0] is None:
        return False
    fm, body = page
    fresh = _overview_frontmatter(entity, ctx, stamp=str(fm.get("timestamp", "")))
    changed = False
    for key in REFRESHED_KEYS:
        if key in fresh and fm.get(key) != fresh[key]:
            fm[key] = fresh[key]
            changed = True
    return write_page(bundle_dir, rel, fm, body) if changed else False


def _write_indexes(bundle_dir: str, session: Session) -> None:
    project_dirs = []
    projects_root = os.path.join(bundle_dir, "projects")
    if os.path.isdir(projects_root):
        project_dirs = sorted(
            d for d in os.listdir(projects_root)
            if os.path.isdir(os.path.join(projects_root, d)))
    entries = []
    for slug in project_dirs:
        overview = read_page(os.path.join(projects_root, slug, "overview.md"))
        title, desc = slug, ""
        if overview and overview[0]:
            title = overview[0].get("title", slug)
            desc = overview[0].get("description", "")
        entries.append((f"/projects/{slug}/index.md", title, desc))
        entity = session.scalar(
            select(Entity).where(Entity.canonical_slug == slug))
        if entity:
            pages = [f for f in os.listdir(os.path.join(projects_root, slug))
                     if f.endswith(".md")]
            write_text(bundle_dir, f"projects/{slug}/index.md",
                       _project_index(entity, pages))
    write_text(bundle_dir, "projects/index.md",
               render_index("Projects", entries))
    write_text(bundle_dir, "index.md", render_index(
        "CouncilHound knowledge bundle — City of Fairfax, VA",
        [("/projects/index.md", "Projects",
          "development projects tracked from council meetings and official records")]))


def seed_bundle(session: Session, bundle_dir: str,
                slugs: list[str] | None = None,
                limit: int | None = None, force: bool = False) -> dict:
    """Create wiki directories for candidate projects. Existing directories
    are skipped (idempotent) unless force re-drafts the curator pages."""
    candidates = wiki_candidates(session, slugs=slugs)
    if limit:
        candidates = candidates[:limit]
    seeded = skipped = 0
    for entity in candidates:
        slug = entity.canonical_slug
        rel_dir = f"projects/{slug}"
        if os.path.exists(os.path.join(bundle_dir, rel_dir, "overview.md")) and not force:
            skipped += 1
            continue
        ctx = _project_context(session, entity)
        stamp = _narrative_stamp(ctx)
        write_page(bundle_dir, f"{rel_dir}/overview.md",
                   _overview_frontmatter(entity, ctx, stamp),
                   _overview_body(entity, ctx))
        write_page(bundle_dir, f"{rel_dir}/positions.md", {
            "type": "project-positions",
            "title": f"{entity.name} — positions & open questions",
            "description": f"Recorded member positions and unresolved questions "
                           f"on {entity.name}.",
            "resource": _resource_url(entity, ctx["city"]),
            "timestamp": stamp,
        }, _positions_body(ctx))
        impact = _impact_body(entity, ctx)
        if impact:
            evaluation = ctx["evaluation"]
            write_page(bundle_dir, f"{rel_dir}/impact.md", {
                "type": "project-impact",
                "title": f"{entity.name} — impact analysis",
                "description": f"Screening-level economic and fiscal estimates "
                               f"for {entity.name}.",
                "resource": _resource_url(entity, ctx["city"]),
                "timestamp": (evaluation.synthesized_at.date().isoformat()
                              if evaluation.synthesized_at else stamp),
            }, impact)
        _write_history(session, bundle_dir, entity, ctx)
        append_log(bundle_dir, rel_dir,
                   ["Seeded from the tracker profile and official records."])
        seeded += 1
        log.info("seeded wiki for %s", slug)
    _write_indexes(bundle_dir, session)
    if seeded:
        append_log(bundle_dir, "", [f"Seeded {seeded} project wiki(s)."])
    return {"seeded": seeded, "skipped_existing": skipped,
            "candidates": len(candidates)}


def refresh_bundle(session: Session, bundle_dir: str) -> dict:
    """Deterministic nightly pass over existing wiki directories: regenerate
    history.md, refresh pipeline-owned overview frontmatter, rebuild
    indexes. No-op (and no log entries) when nothing changed."""
    projects_root = os.path.join(bundle_dir, "projects")
    if not os.path.isdir(projects_root):
        return {"refreshed": 0, "unchanged": 0, "orphaned": 0}
    refreshed = unchanged = orphaned = 0
    for slug in sorted(os.listdir(projects_root)):
        if not os.path.isdir(os.path.join(projects_root, slug)):
            continue
        entity = session.scalar(
            select(Entity).where(Entity.canonical_slug == slug))
        if entity is None:
            orphaned += 1
            log.warning("wiki dir %s has no matching entity (merged/renamed?)", slug)
            continue
        ctx = _project_context(session, entity)
        changed = _write_history(session, bundle_dir, entity, ctx)
        changed = _refresh_overview_frontmatter(bundle_dir, entity, ctx) or changed
        if changed:
            latest = (ctx["timeline"][-1][1].meeting_date.isoformat()
                      if ctx["timeline"] else None)
            note = (f"Meeting history updated through {latest}." if latest
                    else "Pipeline refresh.")
            append_log(bundle_dir, f"projects/{slug}", [note])
            refreshed += 1
        else:
            unchanged += 1
    _write_indexes(bundle_dir, session)
    return {"refreshed": refreshed, "unchanged": unchanged, "orphaned": orphaned}
