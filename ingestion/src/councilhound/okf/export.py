"""Render the OKF bundle from the DB.

seed_bundle creates a project's wiki directory once — curator-owned pages
(overview/positions/impact) are drafted from the existing profile, official
record, and synthesized evaluation, then never touched again by this module.
refresh_bundle is the deterministic nightly pass: it regenerates only
pipeline-owned artifacts (history.md, index.md files, status frontmatter, the
curator:off "In this wiki" nav section on overview.md, and impact.md's
curator:off analysis-link paragraphs) so re-running it against unchanged data
is a no-op."""
import logging
import os
import re
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.config import GRANICUS_BASE_URL, JURISDICTION, LOCAL_TZ, SITE_BASE_URL
from councilhound.db.models import (
    AgendaItem,
    CityProject,
    Entity,
    EntityAlias,
    EntityProfile,
    EntityUpdate,
    Meeting,
    ProjectEvaluation,
    UpcomingMeeting,
    Vote,
)
from councilhound.hot_topics import MIN_VARIANT_LEN
from councilhound.okf.bundle import (
    CURATOR_OFF_CLOSE,
    CURATOR_OFF_OPEN,
    CURATOR_OFF_RE,
    LIFECYCLE_STATUSES,
    PAGE_ORDER,
    PIPELINE_ACTOR,
    append_log,
    curator_actor,
    generated,
    generated_at,
    is_actor,
    iso_datetime,
    read_page,
    render_index,
    slugify,
    verified_events,
    write_page,
    write_text,
)

# UpcomingMeeting.starts_at is city-local and naive (scraper/granicus.py)
CITY_TZ = LOCAL_TZ  # the jurisdiction's zone; name kept for importers
_ID = JURISDICTION.identity
# the curator-owned prose a person can sign off on (v0.2 `verified`)
VERIFIABLE_PAGES = ("overview", "positions", "impact")

log = logging.getLogger(__name__)

PIPELINE_NOTE = ("<!-- Pipeline-owned page: regenerated from the meeting "
                 "record. Edits here will be overwritten. -->")
CURATED_NOTE = ("<!-- Curator-owned page: updated incrementally as new "
                "meetings land. Human edits are preserved. -->")

# overview.md frontmatter keys the deterministic refresh may rewrite; body
# and every other key belong to the curator/humans. `resource` is in here
# because it is derived from whether the entity still has a CityProject: the
# city dropped George Snyder Trail from its directory, the daily project sync
# removed the row, and the wiki went on pointing at a 404 because nothing
# recomputed the URI.
REFRESHED_KEYS = {"project_status", "tags", "evaluation_status", "resource",
                  "stale_after"}
# refreshed keys that are removed when the data behind them is gone: a
# `stale_after` left standing past its instant would flag the page forever
CLEARED_KEYS = {"stale_after"}


def _sync_keys(fm: dict, fresh: dict, keys: set[str]) -> None:
    for key in keys:
        if key in fresh:
            if fm.get(key) != fresh[key]:
                fm[key] = fresh[key]
        elif key in CLEARED_KEYS and key in fm:
            del fm[key]


def _write_tracked(bundle_dir: str, rel: str, fm: dict, body: str) -> bool:
    """Write the page, but report a change only when something other than
    `stale_after` moved. The staleness horizon advances every time a meeting
    passes; that alone earns neither a log line per project nor a place in
    the refresh count, though the file is still written for the commit."""
    existing = read_page(os.path.join(bundle_dir, rel))
    wrote = write_page(bundle_dir, rel, fm, body)
    if not wrote or existing is None or existing[0] is None:
        return wrote

    def material(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "stale_after"}
    return (existing[1].strip() != body.strip()
            or material(existing[0]) != material(fm))
# the curator's log line, from which a page written before `generated`
# existed recovers who last produced it
_CURATOR_LOG_RE = re.compile(r"\(curator: ([^,)]+),")


def _stamp_fields(by: str, at) -> dict:
    """`generated` (v0.2 §5.2) plus the v0.1 `timestamp` it superseded. The
    legacy key stays for one release so an API still reading it keeps its
    dates while the bundle rolls forward; readers prefer `generated.at`."""
    if at in (None, ""):
        return {}
    gen = generated(by, at)
    return {"generated": gen, "timestamp": gen["at"][:10]}


def _legacy_actor(bundle_dir: str, slug: str) -> str:
    """Who produced a curator-owned page that predates `generated`: the
    curator, if the project log records one of its edits (it always edits
    overview and positions together), else the pipeline that seeded it."""
    path = os.path.join(bundle_dir, "projects", slug, "log.md")
    if not os.path.exists(path):
        return PIPELINE_ACTOR
    with open(path, encoding="utf-8") as f:
        models = _CURATOR_LOG_RE.findall(f.read())
    return curator_actor(models[-1].strip()) if models else PIPELINE_ACTOR


def _migrate_frontmatter(fm: dict, legacy_by: str) -> bool:
    """Bring a page written under v0.1 up to v0.2 in place: `timestamp`
    gains a `generated` sibling, and a city project status squatting on the
    reserved lifecycle `status` key moves to `project_status`. Idempotent;
    returns whether anything changed."""
    changed = False
    if "generated" not in fm and generated_at(fm):
        fm["generated"] = generated(legacy_by, generated_at(fm))
        changed = True
    status = fm.get("status")
    if status is not None and status not in LIFECYCLE_STATUSES:
        fm.setdefault("project_status", status)
        del fm["status"]
        changed = True
    return changed


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


def _stale_after(session: Session, entity: Entity, timeline: list) -> str | None:
    """OKF v0.2 §5.5: the instant after which a meeting-driven page may be
    out of date — the next scheduled meeting of a body that has taken the
    project up, or any upcoming meeting whose posted agenda names it. Until
    the pipeline runs again after that meeting the page cannot vouch for
    itself, and a consumer decides by comparing the instant with now. None
    when nothing relevant is scheduled; the key is then cleared rather than
    left to expire into a permanent warning."""
    now_local = datetime.now(CITY_TZ).replace(tzinfo=None)
    bodies = {meeting.body for _update, meeting, _item in timeline}
    aliases = session.scalars(
        select(EntityAlias.alias).where(EntityAlias.entity_id == entity.id))
    variants = {v.lower() for v in [entity.name, *aliases]
                if v and len(v) >= MIN_VARIANT_LEN}
    upcoming = session.scalars(
        select(UpcomingMeeting)
        .where(UpcomingMeeting.starts_at.isnot(None),
               UpcomingMeeting.starts_at > now_local)
        .order_by(UpcomingMeeting.starts_at, UpcomingMeeting.id))
    for event in upcoming:
        named = bool(event.agenda_text) and any(
            v in event.agenda_text.lower() for v in variants)
        if named or (event.body and event.body in bodies):
            return iso_datetime(event.starts_at.replace(tzinfo=CITY_TZ))
    return None


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
            "timeline": timeline,
            "stale_after": _stale_after(session, entity, timeline)}


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
        or f"{entity.name}, tracked from {_ID.short_name} public meetings.",
        "resource": _resource_url(entity, city),
        "tags": _tags(entity, city),
        **_stamp_fields(PIPELINE_ACTOR, stamp),
        "stale_after": ctx.get("stale_after"),
        "project_status": entity.current_status or (city.official_status if city else None),
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


NAV_HEADING = "In this wiki"
# the nav section before markers were introduced: heading through the next h2
_UNMARKED_NAV_RE = re.compile(rf"^## {NAV_HEADING}\s*$.*?(?=^## |\Z)",
                              re.MULTILINE | re.DOTALL)


def _replace_marked_block(body: str, key: str, block: str,
                          unmarked: re.Pattern) -> str | None:
    """Swap in a freshly built curator:off block, matching either the marked
    region carrying `key` or, on pages written before the markers existed, the
    unmarked prose that block replaces. Returns None when the page has
    neither — the caller decides whether a missing block means "append it" or
    "leave this page alone".

    The sibling of _replace_marked_section, for blocks that are bare
    paragraphs rather than headed sections: it keys on an arbitrary marker
    comment and takes the unmarked pattern explicitly, because there is no
    heading to derive either from.

    The trailing newlines of whatever was matched are kept, so a block in the
    middle of a page stays separated from what follows it."""
    for match in CURATOR_OFF_RE.finditer(body):
        if key in match.group(0):
            return body[:match.start()] + block + body[match.end():]
    match = unmarked.search(body)
    if match is None:
        return None
    matched = match.group(0)
    trailing = matched[len(matched.rstrip("\n")):]
    return body[:match.start()] + block + trailing + body[match.end():]


def _nav_block(slug: str, pages: set[str]) -> str:
    """The "In this wiki" section.

    Derived from which pages exist, so it is pipeline-owned even though it
    lives on a curator-owned page — and wrapped in curator:off, because the
    curator has silently deleted it. Marking it is what turns that from a
    quiet content loss into a rejected edit: _protected_regions compares the
    marked regions before and after, so removing one fails the whole edit."""
    lines = [CURATOR_OFF_OPEN, "", f"## {NAV_HEADING}", ""]
    if "history" in pages:
        lines.append(f"- [Meeting history](/projects/{slug}/history.md) — every action, "
                     "vote, and update, with links to the moment in the meeting video")
    lines.append(f"- [Positions & open questions](/projects/{slug}/positions.md)")
    if "impact" in pages:
        lines.append(f"- [Impact analysis](/projects/{slug}/impact.md) — screening "
                     "estimates with assumptions and ranges")
    if "documents" in pages:
        lines.append(f"- [Documents](/projects/{slug}/documents.md) — the city's "
                     "published record for this project")
    lines += ["", CURATOR_OFF_CLOSE]
    return "\n".join(lines)


def _replace_marked_section(body: str, heading: str, block: str,
                            before: str | None = None) -> str:
    """Swap a pipeline-owned section into a curator-owned page, whether it is
    already marked, still unmarked (seeded before markers existed), or absent
    (never written, or the curator dropped it).

    `before` places a first insertion above that heading; without it the
    section lands at the end. Either way it only matters once — after the
    first write the marked region is found and replaced in place."""
    for match in CURATOR_OFF_RE.finditer(body):
        if f"## {heading}" in match.group(0):
            return body[:match.start()] + block + body[match.end():]
    unmarked = re.compile(rf"^## {re.escape(heading)}\s*$.*?(?=^## |\Z)",
                          re.MULTILINE | re.DOTALL).search(body)
    if unmarked:
        return body[:unmarked.start()] + block + "\n" + body[unmarked.end():]
    if before:
        anchor = re.search(rf"^## {re.escape(before)}\s*$", body, re.MULTILINE)
        if anchor is None:
            # the nav is always last; land above it rather than after
            anchor = next((m for m in CURATOR_OFF_RE.finditer(body)
                           if f"## {NAV_HEADING}" in m.group(0)), None)
        if anchor is not None:
            return body[:anchor.start()] + block + "\n\n" + body[anchor.start():]
    return body.rstrip("\n") + "\n\n" + block + "\n"


def _replace_nav(body: str, block: str) -> str:
    return _replace_marked_section(body, NAV_HEADING, block)


FACTS_HEADING = "Proposal at a glance"
MAX_QUOTE = 200


def _num(value) -> str:
    n = float(value)
    return f"{int(n):,}" if n == int(n) else f"{n:,.2f}"


def _sqft(value) -> str:
    return f"{_num(value)} sq ft"


def _acres(value) -> str:
    return f"{_num(value)} acres"


def _text(value) -> str:
    return str(value).strip()


# label, key under `existing`, key under `proposed`, formatter
_FACT_ROWS = [
    ("Use", "use", None, _text),
    ("Floor area", "sqft", None, _sqft),
    ("Dwelling units", "units", "units", _num),
    ("Affordable units", None, "affordable_units", _num),
    ("Retail", None, "retail_sqft", _sqft),
    ("Office", None, "office_sqft", _sqft),
    ("Stories", None, "stories", _num),
    ("Parking spaces", None, "parking_spaces", _num),
    ("Site area", None, "acres", _acres),
    ("Corridor", None, "corridor", _text),
]


def _facts_block(ctx: dict) -> str | None:
    """Existing vs proposed program, extracted from the city's documents.

    The wiki otherwise describes a project only in prose lifted from the city
    blurb, while the structured figures the impact model actually runs on sit
    unread in ProjectEvaluation.spec.

    Only populated fields get a row. That is what makes the confidence column
    honest rather than noise: across prod every populated field grades high or
    medium, and all 110 `low` grades sit on fields with no value — a `low`
    means "could not find it", not "found it and doubt it"."""
    evaluation = ctx["evaluation"]
    spec = (evaluation.spec if evaluation else None) or {}
    existing = spec.get("existing") or {}
    proposed = spec.get("proposed") or {}
    confidence = spec.get("extraction_confidence") or {}
    quotes = spec.get("extraction_quotes") or {}

    def cell(section: dict, key: str | None, fmt, path_prefix: str) -> str:
        if key is None:
            return "—"
        value = section.get(key)
        if value in (None, "", []):
            return "—"
        rendered = fmt(value)
        grade = confidence.get(f"{path_prefix}.{key}")
        # high is the norm, so flag only what is weaker
        return f"{rendered} _({grade} confidence)_" if grade in {"medium", "low"} \
            else rendered

    rows, cited = [], []
    for label, ex_key, pr_key, fmt in _FACT_ROWS:
        left = cell(existing, ex_key, fmt, "existing")
        right = cell(proposed, pr_key, fmt, "proposed")
        if left == "—" and right == "—":
            continue
        rows.append(f"| {label} | {left} | {right} |")
        for prefix, key in (("existing", ex_key), ("proposed", pr_key)):
            quote = quotes.get(f"{prefix}.{key}") if key else None
            if quote:
                text = " ".join(str(quote).split())[:MAX_QUOTE]
                # name the side: rows like "Dwelling units" carry a quote on
                # each, and unlabelled they read as contradicting each other
                cited.append(f'- **{label}** ({prefix}) — "{text}"')
    if not rows:
        return None

    parts = [CURATOR_OFF_OPEN, "", f"## {FACTS_HEADING}", "",
             "| | Existing | Proposed |", "|---|---|---|", *rows, ""]
    # parcel ids arrive with runs of internal whitespace: "48 3 08    002 B"
    parcels = [" ".join(str(p).split()) for p in (spec.get("parcels") or [])
               if str(p).strip()]
    if parcels:
        parts += [f"Tax map parcel(s): {', '.join(parcels)}", ""]
    if cited:
        parts += ["Extracted from the city's submitted documents; each figure "
                  "traces to the text it came from.", ""]
        parts += cited + [""]
    parts.append(CURATOR_OFF_CLOSE)
    return "\n".join(parts)


def _overview_body(entity: Entity, ctx: dict) -> str:
    city, profile = ctx["city"], ctx["profile"]
    parts = [CURATED_NOTE, ""]
    if profile and profile.summary:
        parts += [profile.summary.strip(), ""]
    facts = _facts_block(ctx)
    if facts:
        parts += [facts, ""]
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
    # seed builds the page set from ctx because the files do not exist yet;
    # refresh rebuilds it from disk, which is authoritative thereafter
    pages = {"positions"}
    if ctx["timeline"]:
        pages.add("history")
    if ctx["evaluation"]:
        pages.add("impact")
    if ctx["city"] is not None and ctx["city"].documents:
        pages.add("documents")
    parts += [_nav_block(entity.canonical_slug, pages)]
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
        **_stamp_fields(PIPELINE_ACTOR, latest),
    }
    if ctx.get("stale_after"):
        fm["stale_after"] = ctx["stale_after"]
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


# impact.md's two link paragraphs, keyed so refresh can find them again. The
# key rides inside the curator:off region; the frontend strips every HTML
# comment before rendering (frontend/lib/wiki.ts), so readers never see it.
IMPACT_INTRO_KEY = "<!-- block:impact-intro -->"
IMPACT_NOTE_KEY = "<!-- block:impact-method-note -->"
# ...and the same paragraphs on pages seeded before the markers existed. Each
# is a single line identified by the link it carries.
_UNMARKED_INTRO_RE = re.compile(r"^.*\[full analysis\]\(.*$", re.MULTILINE)
_UNMARKED_NOTE_RE = re.compile(r"^.*\[analysis page\]\(.*$", re.MULTILINE)


def _marked_block(key: str, lines: list[str]) -> str:
    return "\n".join([CURATOR_OFF_OPEN, key, "", *lines, "", CURATOR_OFF_CLOSE])


def _analysis_url(city: CityProject) -> str:
    return f"{SITE_BASE_URL}/development/{city.external_slug}"


def _impact_intro(entity: Entity, city: CityProject) -> str:
    """The opening paragraph, pipeline-owned for the same reason the nav
    section is: it is derived, not written. The analysis URL moves when the
    city renames a project in its directory and 404s when the city drops one —
    and a URL baked into prose at seed time outlives whatever it pointed at.
    okf-lint flags the dead link, so the failure was already loud — owning the
    paragraph is what makes it repairable."""
    return _marked_block(IMPACT_INTRO_KEY, [
        f"Screening-level estimates of the economic and fiscal effects of "
        f"{entity.name}. Figures are decision-support context with named "
        f"assumptions and sensitivity ranges — not predictions. The "
        f"[full analysis]({_analysis_url(city)}) has the interactive "
        f"assumptions panel and maps; "
        f"[methods]({SITE_BASE_URL}/development/methods) "
        "documents every formula."])


def _impact_note(city: CityProject) -> str:
    # method notes carry literal figures from the deterministic run, so they
    # stay on the analysis page (always current) rather than in wiki prose
    return _marked_block(IMPACT_NOTE_KEY, [
        f"Method notes, caveats, and non-headline metrics live on the "
        f"[analysis page]({_analysis_url(city)})."])


def _impact_body(entity: Entity, ctx: dict) -> str | None:
    evaluation, city = ctx["evaluation"], ctx["city"]
    if not evaluation or not city:
        return None
    parts = [
        CURATED_NOTE, "",
        _impact_intro(entity, city), "",
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
    parts += ["", _impact_note(city)]
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
        "documents": "the city's published document record",
    }
    entries = [(f"/projects/{slug}/{p}.md", p.capitalize(), described.get(p, ""))
               for p in PAGE_ORDER if f"{p}.md" in existing_pages]
    return render_index(entity.name, entries)


def _documents_body(ctx: dict) -> str | None:
    """The city's own document list for the project — staff reports, plan
    sets, traffic studies, FAQs. Nothing else in the product indexes these."""
    city = ctx["city"]
    docs = (city.documents if city else None) or []
    entries = [(str(d.get("label") or "").strip(), str(d.get("url") or "").strip())
               for d in docs]
    entries = [(label, url) for label, url in entries if url]
    if not entries:
        return None
    parts = [PIPELINE_NOTE, "",
             "Documents published in the city's project record, in the order "
             "the city lists them. Labels are the city's own and usually carry "
             "the document date, format, and size.", ""]
    for label, url in entries:
        # labels are free text and do contain brackets; escaping keeps a
        # stray one from swallowing the link
        safe = (label or url).replace("[", "\\[").replace("]", "\\]")
        parts.append(f"- [{safe}]({url})")
    return "\n".join(parts)


def _write_documents(bundle_dir: str, entity: Entity, ctx: dict) -> bool:
    """Pipeline-owned, so regenerated rather than seeded once.

    The timestamp is only bumped when the list actually changes. Deriving it
    from CityProject.synced_at instead would re-date the page on every sync
    and make refresh permanently dirty, which costs the loop its no-op."""
    body = _documents_body(ctx)
    if body is None:
        return False
    rel = f"projects/{entity.canonical_slug}/documents.md"
    existing = read_page(os.path.join(bundle_dir, rel))
    if existing is not None and existing[1].strip() == body.strip():
        # same list, so the stamp stands — but a page written under v0.1
        # still gets its `generated` (dated by that stamp, not today)
        fm = dict(existing[0] or {})
        if _migrate_frontmatter(fm, PIPELINE_ACTOR):
            return write_page(bundle_dir, rel, fm, existing[1])
        return False
    n = len(ctx["city"].documents or [])
    return write_page(bundle_dir, rel, {
        "type": "project-documents",
        "title": f"{entity.name} — documents",
        "description": f"{n} document(s) published in the {_ID.short_name} "
                       f"project record for {entity.name}.",
        "resource": _resource_url(entity, ctx["city"]),
        **_stamp_fields(PIPELINE_ACTOR, date.today()),
    }, body)


def _write_impact(bundle_dir: str, entity: Entity, ctx: dict, stamp: str,
                  only_if_missing: bool = False) -> bool:
    """Draft impact.md from the synthesized evaluation.

    refresh passes only_if_missing. The page is curator-owned, so an existing
    one is never overwritten — but without this a project whose evaluation
    synthesized *after* its wiki was seeded would never get an impact page at
    all: seed skips any directory that already has an overview.md, and
    refresh used to regenerate only history and frontmatter. That stranded
    five of twenty synthesized evaluations."""
    body = _impact_body(entity, ctx)
    if body is None:
        return False
    rel = f"projects/{entity.canonical_slug}/impact.md"
    if only_if_missing and os.path.exists(os.path.join(bundle_dir, rel)):
        return False
    evaluation = ctx["evaluation"]
    return write_page(bundle_dir, rel, {
        "type": "project-impact",
        "title": f"{entity.name} — impact analysis",
        "description": f"Screening-level economic and fiscal estimates "
                       f"for {entity.name}.",
        "resource": _resource_url(entity, ctx["city"]),
        **_stamp_fields(PIPELINE_ACTOR, evaluation.synthesized_at or stamp),
    }, body)


def _migrate_stranded_pages(bundle_dir: str, entity: Entity) -> bool:
    """Pipeline-owned pages whose source has since emptied — a history.md
    for a timeline that was detached, a documents.md for a record the city
    withdrew — are no longer regenerated, so the regular writers never reach
    their frontmatter. Bring them to v0.2 in place; whether such a page
    should still exist is a separate question this pass does not answer."""
    changed = False
    for page in ("history", "documents"):
        rel = f"projects/{entity.canonical_slug}/{page}.md"
        parsed = read_page(os.path.join(bundle_dir, rel))
        if parsed is None or parsed[0] is None:
            continue
        fm, body = parsed
        if _migrate_frontmatter(fm, PIPELINE_ACTOR):
            changed = write_page(bundle_dir, rel, fm, body) or changed
    return changed


def _write_history(session: Session, bundle_dir: str, entity: Entity,
                   ctx: dict) -> bool:
    page = _history_page(entity, ctx, _history_votes(session, ctx))
    if page is None:
        return False
    fm, body = page
    return _write_tracked(bundle_dir, f"projects/{entity.canonical_slug}/history.md",
                          fm, body)


def verify_pages(bundle_dir: str, slug: str, by: str,
                 pages: list[str] | None = None,
                 at: datetime | None = None) -> list[str]:
    """Record a verification event (v0.2 §5.2) on a project's curator-owned
    pages: someone confirmed the prose against the record. Events are
    appended, never replaced — independent checks accumulate, and the
    consumer reads the latest. A person signing off must use the `human:`
    actor prefix; that prefix is what lifts the page to human-reviewed
    (§5.3). Returns the pages marked."""
    if not is_actor(by):
        raise ValueError(f"{by!r} is not an OKF actor (human:<id>, "
                         "process:<id>, or <producer>/<version>)")
    stamp = iso_datetime(at or datetime.now(timezone.utc))
    marked = []
    for page in pages or VERIFIABLE_PAGES:
        rel = f"projects/{slug}/{page}.md"
        parsed = read_page(os.path.join(bundle_dir, rel))
        if parsed is None or parsed[0] is None:
            if pages:
                raise FileNotFoundError(f"{rel} is not a concept page")
            continue
        fm, body = parsed
        fm["verified"] = verified_events(fm) + [{"by": by, "at": stamp}]
        write_page(bundle_dir, rel, fm, body)
        marked.append(page)
    if marked:
        append_log(bundle_dir, f"projects/{slug}",
                   [f"Verified {', '.join(marked)} ({by})."])
    return marked


def _refresh_overview(bundle_dir: str, entity: Entity, ctx: dict) -> bool:
    """Rewrite the pipeline-owned parts of overview.md — the frontmatter keys
    in REFRESHED_KEYS and the "In this wiki" nav section — preserving the
    curator/human-owned prose and every other frontmatter key.

    Regenerating the nav from what is on disk keeps it honest as pages come
    and go (an impact.md backfilled later shows up here), and re-marks it if
    the curator stripped the markers."""
    slug = entity.canonical_slug
    rel = f"projects/{slug}/overview.md"
    page = read_page(os.path.join(bundle_dir, rel))
    if page is None or page[0] is None:
        return False
    fm, body = page
    _migrate_frontmatter(fm, _legacy_actor(bundle_dir, slug))
    fresh = _overview_frontmatter(entity, ctx, stamp=generated_at(fm) or "")
    _sync_keys(fm, fresh, REFRESHED_KEYS)

    present = {f.removesuffix(".md")
               for f in os.listdir(os.path.join(bundle_dir, "projects", slug))
               if f.endswith(".md")}
    facts = _facts_block(ctx)
    if facts:
        body = _replace_marked_section(body, FACTS_HEADING, facts,
                                       before="Official record")
    body = _replace_nav(body, _nav_block(slug, present))
    return _write_tracked(bundle_dir, rel, fm, body)


def _canonical_member_slugs(session: Session) -> dict[str, str]:
    """Alias -> canonical slug for people, lowercased.

    Merging a duplicate leaves its old slug behind as an alias, which keeps
    /entities working but not /members: that route matches canonical_slug
    exactly, so every wiki link to the merged-away slug becomes a 404 the
    moment the merge lands."""
    canonical = {e.id: e.canonical_slug for e in session.scalars(
        select(Entity).where(Entity.entity_type == "person"))}
    mapping = {}
    for eid, alias in session.execute(
            select(EntityAlias.entity_id, func.lower(EntityAlias.alias))):
        if eid in canonical and alias != canonical[eid]:
            mapping[alias] = canonical[eid]
    return mapping


def _refresh_member_links(bundle_dir: str, entity: Entity,
                          aliases: dict[str, str]) -> bool:
    """Repoint member links left dangling by an entity merge.

    Only the slug inside a /members/ URL is touched — never prose. A member
    reference is as derived as the `resource` key, so leaving it stale on a
    curator-owned page would mean a merge permanently blocks the lint gate
    until a human edits by hand."""
    slug = entity.canonical_slug
    changed = False
    for page in ("overview", "positions", "impact", "documents", "history"):
        rel = f"projects/{slug}/{page}.md"
        parsed = read_page(os.path.join(bundle_dir, rel))
        if parsed is None:
            continue
        fm, body = parsed
        fixed = body
        for stale, canon in aliases.items():
            fixed = fixed.replace(f"{SITE_BASE_URL}/members/{stale})",
                                  f"{SITE_BASE_URL}/members/{canon})")
        if fixed != body:
            changed = write_page(bundle_dir, rel, fm or {}, fixed) or changed
    return changed


def _refresh_sibling_resources(bundle_dir: str, entity: Entity,
                               ctx: dict) -> bool:
    """positions.md and impact.md carry the same derived `resource` URI as
    overview.md. Their bodies are the curator's, but that key is not — leave
    it alone and it outlives the record it was derived from. positions.md
    is meeting-driven like overview.md, so it carries the same `stale_after`
    horizon; impact.md follows the evaluation, not the calendar. The same
    pass brings a v0.1 page's frontmatter up to v0.2 (impact.md is never
    touched by the LLM curator, so its legacy producer is always the
    pipeline)."""
    slug = entity.canonical_slug
    fresh = {"resource": _resource_url(entity, ctx["city"])}
    if ctx.get("stale_after"):
        fresh["stale_after"] = ctx["stale_after"]
    changed = False
    for page, legacy_by, keys in (
            ("positions", _legacy_actor(bundle_dir, slug), {"resource", "stale_after"}),
            ("impact", PIPELINE_ACTOR, {"resource"})):
        rel = f"projects/{slug}/{page}.md"
        parsed = read_page(os.path.join(bundle_dir, rel))
        if parsed is None or parsed[0] is None:
            continue
        fm, body = parsed
        before = dict(fm)
        _migrate_frontmatter(fm, legacy_by)
        _sync_keys(fm, fresh, keys)
        if fm != before:
            changed = _write_tracked(bundle_dir, rel, fm, body) or changed
    return changed


def _refresh_impact_links(bundle_dir: str, entity: Entity, ctx: dict) -> bool:
    """Rebuild impact.md's analysis-link paragraphs from the current record.

    The rest of the page is the curator's, and stays untouched: only the two
    curator:off blocks are replaced, and only where the page still has them.
    A human who deleted the closing pointer meant to delete it — unlike the
    nav section, which the curator dropped silently, so nothing is appended
    back.

    Does nothing once the project has no CityProject: there is no analysis
    page left to point at, and the evaluation cascaded away with it, so the
    metric markers are orphaned too. Rewriting the links there would repair
    half a page and quiet the lint that says a human should look at it."""
    city = ctx["city"]
    if city is None:
        return False
    rel = f"projects/{entity.canonical_slug}/impact.md"
    parsed = read_page(os.path.join(bundle_dir, rel))
    if parsed is None or parsed[0] is None:
        return False
    fm, body = parsed
    for key, block, unmarked in (
            (IMPACT_INTRO_KEY, _impact_intro(entity, city), _UNMARKED_INTRO_RE),
            (IMPACT_NOTE_KEY, _impact_note(city), _UNMARKED_NOTE_RE)):
        replaced = _replace_marked_block(body, key, block, unmarked)
        if replaced is not None:
            body = replaced
    return write_page(bundle_dir, rel, fm, body)


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
        f"CouncilHound knowledge bundle — {_ID.short_name}, {_ID.state_abbr}",
        [("/projects/index.md", "Projects",
          "development projects tracked from council meetings and official records")],
        root=True))


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
            **_stamp_fields(PIPELINE_ACTOR, stamp),
            **({"stale_after": ctx["stale_after"]} if ctx.get("stale_after") else {}),
        }, _positions_body(ctx))
        _write_impact(bundle_dir, entity, ctx, stamp)
        _write_documents(bundle_dir, entity, ctx)
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
    history.md, refresh the pipeline-owned frontmatter keys and marked blocks
    on the curator-owned pages, rebuild indexes. No-op (and no log entries)
    when nothing changed."""
    projects_root = os.path.join(bundle_dir, "projects")
    if not os.path.isdir(projects_root):
        return {"refreshed": 0, "unchanged": 0, "orphaned": 0}
    refreshed = unchanged = orphaned = 0
    member_aliases = _canonical_member_slugs(session)
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
        history_changed = _write_history(session, bundle_dir, entity, ctx)
        changed = history_changed
        # before _refresh_overview, which rebuilds the nav from what is on
        # disk — write the page first and it links itself
        seeded_impact = _write_impact(bundle_dir, entity, ctx,
                                      _narrative_stamp(ctx), only_if_missing=True)
        changed = seeded_impact or changed
        changed = _write_documents(bundle_dir, entity, ctx) or changed
        changed = _migrate_stranded_pages(bundle_dir, entity) or changed
        changed = _refresh_overview(bundle_dir, entity, ctx) or changed
        changed = _refresh_sibling_resources(bundle_dir, entity, ctx) or changed
        changed = _refresh_member_links(bundle_dir, entity,
                                       member_aliases) or changed
        changed = _refresh_impact_links(bundle_dir, entity, ctx) or changed
        if changed:
            latest = (ctx["timeline"][-1][1].meeting_date.isoformat()
                      if ctx["timeline"] else None)
            notes = []
            if seeded_impact:
                notes.append("Added impact analysis from the synthesized "
                             "evaluation.")
            notes.append(f"Meeting history updated through {latest}."
                         if history_changed and latest else "Pipeline refresh.")
            append_log(bundle_dir, f"projects/{slug}", notes)
            refreshed += 1
        else:
            unchanged += 1
    _write_indexes(bundle_dir, session)
    return {"refreshed": refreshed, "unchanged": unchanged, "orphaned": orphaned}
