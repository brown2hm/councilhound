"""
Entity profile synthesis: the rollup behind the topic detail page.

For one entity, gather its full record — dated updates, agenda item
outcomes, votes, and transcript excerpts that mention it by name — and ask
Claude for: an overall summary, current state, open questions / options
still on the table, and commentary binned per council member. Member
positions come from what the minutes record by name ("Bates expressed
support for...", "Hall requested more information"), so this works without
speaker diarization.

Profiles are a cache: through_meeting_id marks the latest meeting included;
`profile --stale-only` regenerates entities whose timelines have advanced.
"""
import logging
import os

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.db.models import (
    AgendaItem,
    Entity,
    EntityAlias,
    EntityProfile,
    EntityUpdate,
    Meeting,
    TranscriptChunk,
    Vote,
)
from councilhound.entities import resolve_entity

log = logging.getLogger(__name__)

PROFILE_PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TRANSCRIPT_EXCERPTS = 12

PROFILE_TOOL = {
    "name": "record_entity_profile",
    "description": "Record the synthesized profile of one tracked topic/project.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "3-6 sentence plain-language history and current state: what this is, why it matters, what has happened.",
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Decisions not yet made, options under consideration, or explicit next steps awaited. Empty if the matter is fully resolved.",
            },
            "member_commentary": {
                "type": "array",
                "description": "One entry per council/commission member whose position or comments are recorded in the material. Omit members who only voted without recorded comment.",
                "items": {
                    "type": "object",
                    "properties": {
                        "member": {"type": "string", "description": "Member name as recorded."},
                        "summary": {
                            "type": "string",
                            "description": "1-3 sentences summarizing this member's recorded comments/positions on this topic, with dates where relevant.",
                        },
                    },
                    "required": ["member", "summary"],
                },
            },
        },
        "required": ["summary", "open_questions", "member_commentary"],
    },
}

PROFILE_SYSTEM = """\
You synthesize the record of one tracked municipal topic (project, ordinance, \
zoning case, ...) from dated meeting updates, vote records, and transcript \
excerpts. Rules:
- Only state what the material supports; attribute member positions only when \
the material records that member saying/doing it. Never infer a position from \
a vote alone.
- Be specific about dates and sequence. Newer material supersedes older.
- open_questions: only genuinely unresolved decisions or explicitly mentioned \
upcoming steps — not rhetorical questions."""


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
        max_tokens=4096,
        system=PROFILE_SYSTEM,
        tools=[PROFILE_TOOL],
        tool_choice={"type": "tool", "name": "record_entity_profile"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("no tool_use block in response")


def _entity_name_variants(session: Session, entity: Entity) -> list[str]:
    aliases = session.scalars(
        select(EntityAlias.alias).where(EntityAlias.entity_id == entity.id)
    ).all()
    return list({entity.name, *aliases})


def _gather_material(session: Session, entity: Entity) -> tuple[str, int | None]:
    """Build the synthesis prompt material. Returns (text, latest_meeting_id)."""
    rows = session.execute(
        select(EntityUpdate, Meeting, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id == entity.id)
        .order_by(Meeting.meeting_date)
    ).all()

    parts = [f"TOPIC: {entity.name} (type: {entity.entity_type}, "
             f"current status: {entity.current_status or 'unknown'})", "", "=== DATED RECORD ==="]
    latest_meeting_id = None
    for update, meeting, item in rows:
        latest_meeting_id = meeting.id
        parts.append(f"\n[{meeting.meeting_date}] {meeting.title}")
        if item:
            parts.append(f"  Agenda item {item.label}: {item.title or ''}")
            if item.outcome:
                parts.append(f"  Outcome: {item.outcome}")
        parts.append(f"  Update: {update.update_text}")
        if item:
            for vote in session.scalars(select(Vote).where(Vote.agenda_item_id == item.id)):
                parts.append(f"  Vote ({vote.motion_result}): {vote.description} "
                             f"| breakdown: {vote.vote_breakdown}")

    variants = [v.lower() for v in _entity_name_variants(session, entity) if len(v) > 4]
    if variants:
        clauses = [func.lower(TranscriptChunk.text).contains(v) for v in variants]
        chunks = session.execute(
            select(TranscriptChunk, Meeting)
            .join(Meeting, TranscriptChunk.meeting_id == Meeting.id)
            .where(or_(*clauses))
            .order_by(Meeting.meeting_date.desc())
            .limit(MAX_TRANSCRIPT_EXCERPTS)
        ).all()
        if chunks:
            parts += ["", "=== TRANSCRIPT EXCERPTS (verbatim, unattributed speech) ==="]
            for chunk, meeting in reversed(chunks):
                parts.append(f"\n[{meeting.meeting_date}] {chunk.text[:1200]}")

    return "\n".join(parts), latest_meeting_id


def synthesize_profile(session: Session, entity: Entity) -> EntityProfile:
    material, latest_meeting_id = _gather_material(session, entity)
    data = _call_claude(material)

    # link member names to seeded person entities where they resolve
    commentary = []
    for entry in data.get("member_commentary", []):
        person = resolve_entity(session, "person", entry.get("member", ""), create=False)
        commentary.append({
            "member": entry.get("member"),
            "slug": person.canonical_slug if person else None,
            "summary": entry.get("summary"),
        })

    profile = session.scalar(select(EntityProfile).where(EntityProfile.entity_id == entity.id))
    if profile is None:
        profile = EntityProfile(entity_id=entity.id)
        session.add(profile)
    profile.summary = data.get("summary")
    profile.open_questions = data.get("open_questions") or []
    profile.member_commentary = commentary
    profile.through_meeting_id = latest_meeting_id
    profile.model = DEFAULT_MODEL
    profile.prompt_version = PROFILE_PROMPT_VERSION
    session.commit()
    return profile


def profile_pending(session: Session, limit: int | None = None, min_updates: int = 2,
                    stale_only: bool = True) -> dict:
    """Synthesize profiles for entities with >= min_updates timeline entries.
    stale_only skips entities whose profile already covers their latest
    meeting. Ordered by most-recently-active first."""
    latest = (
        select(EntityUpdate.entity_id,
               func.count().label("n"),
               func.max(EntityUpdate.meeting_id).label("latest_mid"),
               func.max(Meeting.meeting_date).label("latest_date"))
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .group_by(EntityUpdate.entity_id)
        .having(func.count() >= min_updates)
        .subquery()
    )
    q = (
        select(Entity, latest.c.latest_mid)
        .join(latest, Entity.id == latest.c.entity_id)
        .outerjoin(EntityProfile, EntityProfile.entity_id == Entity.id)
        .where(Entity.entity_type != "person")
        .order_by(latest.c.latest_date.desc())
    )
    if stale_only:
        q = q.where(or_(EntityProfile.id.is_(None),
                        EntityProfile.through_meeting_id.is_(None),
                        EntityProfile.through_meeting_id != latest.c.latest_mid,
                        EntityProfile.prompt_version != PROFILE_PROMPT_VERSION))
    if limit:
        q = q.limit(limit)

    rows = session.execute(q).all()
    done = failed = 0
    for entity, _mid in rows:
        try:
            synthesize_profile(session, entity)
            done += 1
        except Exception:
            session.rollback()
            log.exception("profile synthesis failed for %s", entity.canonical_slug)
            failed += 1
    return {"profiled": done, "failed": failed, "candidates": len(rows)}
