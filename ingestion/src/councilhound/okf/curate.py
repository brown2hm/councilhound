"""The wiki curator: incremental LLM edits to curator-owned pages.

Where profile synthesis regenerated a summary wholesale, the curator edits
durable pages in place — it receives the CURRENT overview.md/positions.md
bodies plus only the meeting record that landed since the page's timestamp,
and returns updated full bodies under hard rules (minimal edits, citations,
no literal impact figures, `<!-- curator:off -->` regions untouchable).
Violating the curator:off contract rejects the whole edit; the page stays as
it was and the failure is logged, never papered over.
"""
import logging
import os
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.db.models import (
    AgendaItem,
    Entity,
    EntityAlias,
    EntityUpdate,
    Meeting,
    TranscriptChunk,
    Vote,
)
from councilhound.okf.bundle import CURATOR_OFF_RE, append_log, read_page, write_page

log = logging.getLogger(__name__)

CURATOR_PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TRANSCRIPT_EXCERPTS = 8

CURATE_TOOL = {
    "name": "record_wiki_edits",
    "description": "Record the minimally-edited wiki pages for one project.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overview_body": {
                "type": "string",
                "description": "Full updated markdown body of overview.md. "
                               "Unchanged text must be reproduced verbatim.",
            },
            "positions_body": {
                "type": "string",
                "description": "Full updated markdown body of positions.md. "
                               "Unchanged text must be reproduced verbatim.",
            },
            "edit_summary": {
                "type": "string",
                "description": "One sentence describing what changed and why "
                               "(for the page history log).",
            },
        },
        "required": ["overview_body", "positions_body", "edit_summary"],
    },
}

CURATE_SYSTEM = """\
You maintain the wiki of one tracked municipal development project. You are \
given the current overview and positions pages and ONLY the new meeting \
record since they were last updated. Update the pages to reflect the new \
material. Hard rules:
- Minimal edits: reproduce unchanged prose verbatim. Do not rewrite, \
reorder, or restyle text the new material doesn't touch — human edits live \
in these pages and must survive you.
- Never remove or alter anything between <!-- curator:off --> and \
<!-- /curator:off --> markers, and keep every HTML comment where it is.
- Only state what the material supports; attribute member positions only \
when the material records that member saying/doing it — never infer from a \
vote alone. Newer material supersedes older.
- Cite: when adding a claim from a meeting, reference its date, e.g. \
"(2026-06-09 City Council)". Keep existing links intact.
- Never write literal dollar amounts or impact figures — impact estimates \
are referenced with {{metric:...}} markers only, and only on the impact page.
- Keep the "Open questions" section honest: resolve questions the record \
answers, add ones it raises."""


def _needs_retry(exc: BaseException) -> bool:
    import anthropic
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (429, 500, 502, 503, 529)
    return False


@retry(retry=retry_if_exception(_needs_retry), stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=5, max=120), reraise=True)
def _call_claude(prompt: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=8192,
        system=CURATE_SYSTEM,
        tools=[CURATE_TOOL],
        tool_choice={"type": "tool", "name": "record_wiki_edits"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("no tool_use block in response")


def _page_stamp(frontmatter: dict | None) -> date | None:
    raw = (frontmatter or {}).get("timestamp")
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def _new_material(session: Session, entity: Entity, since: date | None) -> tuple[str, date | None]:
    """The dated record newer than `since`, formatted like the profile
    material. Returns (text, latest_meeting_date); empty text = up to date."""
    q = (
        select(EntityUpdate, Meeting, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id == entity.id)
        .order_by(Meeting.meeting_date)
    )
    if since:
        q = q.where(Meeting.meeting_date > since)
    rows = session.execute(q).all()
    if not rows:
        return "", None

    parts = ["=== NEW DATED RECORD ==="]
    latest = None
    for update, meeting, item in rows:
        latest = meeting.meeting_date
        parts.append(f"\n[{meeting.meeting_date}] {meeting.title}")
        if item:
            parts.append(f"  Agenda item {item.label}: {item.title or ''}")
            if item.outcome:
                parts.append(f"  Outcome: {item.outcome}")
            for vote in session.scalars(select(Vote).where(Vote.agenda_item_id == item.id)):
                parts.append(f"  Vote ({vote.motion_result}): {vote.description} "
                             f"| breakdown: {vote.vote_breakdown}")
        parts.append(f"  Update: {update.update_text}")

    aliases = session.scalars(
        select(EntityAlias.alias).where(EntityAlias.entity_id == entity.id)).all()
    variants = [v.lower() for v in {entity.name, *aliases} if len(v) > 4]
    meeting_ids = {meeting.id for _, meeting, _ in rows}
    if variants and meeting_ids:
        clauses = [func.lower(TranscriptChunk.text).contains(v) for v in variants]
        chunks = session.execute(
            select(TranscriptChunk, Meeting)
            .join(Meeting, TranscriptChunk.meeting_id == Meeting.id)
            .where(TranscriptChunk.meeting_id.in_(meeting_ids), or_(*clauses))
            .order_by(Meeting.meeting_date)
            .limit(MAX_TRANSCRIPT_EXCERPTS)
        ).all()
        if chunks:
            parts += ["", "=== TRANSCRIPT EXCERPTS (verbatim, unattributed speech) ==="]
            for chunk, meeting in chunks:
                parts.append(f"\n[{meeting.meeting_date}] {chunk.text[:1200]}")
    return "\n".join(parts), latest


def _protected_regions(body: str) -> list[str]:
    return CURATOR_OFF_RE.findall(body)


def curate_project(session: Session, bundle_dir: str, entity: Entity) -> str:
    """Returns 'updated', 'fresh', or 'rejected'."""
    slug = entity.canonical_slug
    rel_dir = f"projects/{slug}"
    overview = read_page(os.path.join(bundle_dir, rel_dir, "overview.md"))
    positions = read_page(os.path.join(bundle_dir, rel_dir, "positions.md"))
    if overview is None or positions is None:
        raise FileNotFoundError(f"{rel_dir} has no seeded wiki pages")
    overview_fm, overview_body = overview
    positions_fm, positions_body = positions

    since = min(filter(None, [_page_stamp(overview_fm), _page_stamp(positions_fm)]),
                default=None)
    material, latest = _new_material(session, entity, since)
    if not material:
        return "fresh"

    prompt = (f"PROJECT: {entity.name} (current status: "
              f"{entity.current_status or 'unknown'})\n"
              f"Pages last updated: {since or 'never'}\n\n"
              f"=== CURRENT overview.md ===\n{overview_body}\n\n"
              f"=== CURRENT positions.md ===\n{positions_body}\n\n"
              f"{material}")
    data = _call_claude(prompt)

    for name, old_body, new_body in [("overview.md", overview_body, data["overview_body"]),
                                     ("positions.md", positions_body, data["positions_body"])]:
        if _protected_regions(old_body) != _protected_regions(new_body):
            log.warning("curator edit for %s/%s altered a curator:off region — rejected",
                        slug, name)
            return "rejected"

    stamp = latest.isoformat() if latest else date.today().isoformat()
    changed = False
    for rel, fm, new_body in [(f"{rel_dir}/overview.md", overview_fm, data["overview_body"]),
                              (f"{rel_dir}/positions.md", positions_fm, data["positions_body"])]:
        fm = dict(fm or {})
        fm["timestamp"] = stamp
        changed = write_page(bundle_dir, rel, fm, new_body) or changed
    if changed:
        summary = (data.get("edit_summary") or "Curator update.").strip()
        append_log(bundle_dir, rel_dir,
                   [f"{summary} (curator: {DEFAULT_MODEL}, through {stamp})"])
    return "updated" if changed else "fresh"


def curate_pending(session: Session, bundle_dir: str,
                   limit: int | None = None) -> dict:
    """Curate every seeded project whose timeline advanced past its pages."""
    projects_root = os.path.join(bundle_dir, "projects")
    if not os.path.isdir(projects_root):
        return {"updated": 0, "fresh": 0, "rejected": 0, "failed": 0}
    slugs = sorted(d for d in os.listdir(projects_root)
                   if os.path.isdir(os.path.join(projects_root, d)))
    counts = {"updated": 0, "fresh": 0, "rejected": 0, "failed": 0}
    for slug in slugs:
        if limit and counts["updated"] >= limit:
            break
        entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
        if entity is None:
            continue
        try:
            counts[curate_project(session, bundle_dir, entity)] += 1
        except Exception:
            log.exception("curator failed for %s", slug)
            counts["failed"] += 1
    return counts
