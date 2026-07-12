"""
Phase 3: LLM structuring pass.

One structured-output (tool-use) call per meeting: agenda + minutes +
actions report go in (max observed ~44KB — comfortably one call; the
transcript deliberately stays out, it's for citations/Q&A, not facts).
Claude returns agenda items, votes, and entity updates; we then:

  1. store the raw output in `extractions` keyed by (meeting_id,
     PROMPT_VERSION) — re-apply or diff prompts without new LLM calls;
  2. resolve every entity name via councillens.entities (slug -> alias ->
     create) — the model never controls canonical identity;
  3. rebuild the meeting's agenda_items / votes / entity_updates /
     entity_mentions rows from scratch (delete + recreate), so a re-run
     converges to the same rows instead of duplicating.

current_status on each touched entity is rolled up from its latest
entity_update with a status_after.
"""
import logging
import os

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councillens.config import ANTHROPIC_API_KEY
from councillens.db.models import (
    AgendaItem,
    Document,
    Entity,
    EntityMention,
    EntityUpdate,
    Extraction,
    Meeting,
    Vote,
)
from councillens.entities import resolve_entity

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_DOC_CHARS = 60_000  # defensive truncation; largest observed doc is ~44KB

ENTITY_TYPES = ["person", "project", "ordinance", "resolution", "case_number", "location", "topic"]
STATUSES = ["proposed", "in_progress", "approved", "denied", "deferred", "completed", "withdrawn"]

EXTRACTION_TOOL = {
    "name": "record_meeting_extraction",
    "description": "Record the structured facts extracted from one council/commission meeting.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Plain-language summary of the meeting, a few sentences.",
            },
            "agenda_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Item label as printed, e.g. '7a' or '4'."},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "outcome": {
                            "type": "string",
                            "description": "What happened to this item at this meeting, per the minutes/actions.",
                        },
                        "votes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string", "description": "The motion voted on."},
                                    "motion_result": {"type": "string", "enum": ["passed", "failed", "deferred"]},
                                    "vote_breakdown": {
                                        "type": "object",
                                        "description": "Member last name -> yes|no|abstain|absent. Empty if unanimous voice vote with no breakdown recorded.",
                                        "additionalProperties": {"type": "string", "enum": ["yes", "no", "abstain", "absent"]},
                                    },
                                },
                                "required": ["description", "motion_result"],
                            },
                        },
                        "entities": {
                            "type": "array",
                            "description": "Projects, ordinances, locations, people (other than routine member attendance), and topics this item concerns.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "entity_type": {"type": "string", "enum": ENTITY_TYPES},
                                    "name": {
                                        "type": "string",
                                        "description": "Proper name as the documents use it, e.g. 'George Snyder Trail', 'Ordinance 2026-04'.",
                                    },
                                    "role": {"type": "string", "description": "e.g. 'subject', 'applicant', 'sponsor', 'location'."},
                                    "update_text": {
                                        "type": "string",
                                        "description": "One or two sentences: what happened to THIS entity at THIS meeting.",
                                    },
                                    "status_after": {
                                        "type": "string",
                                        "enum": STATUSES,
                                        "description": "Only for project/ordinance/resolution/case entities where the meeting changed or confirmed a status. Omit otherwise.",
                                    },
                                },
                                "required": ["entity_type", "name", "update_text"],
                            },
                        },
                    },
                    "required": ["label", "title", "outcome"],
                },
            },
        },
        "required": ["summary", "agenda_items"],
    },
}

SYSTEM_PROMPT = """\
You extract structured facts from municipal meeting records (agenda, minutes, \
and an official actions report when available). Rules:
- The minutes and actions report are the source of truth for outcomes and \
votes; the agenda alone only tells you what was scheduled.
- Record only what the documents state. Never infer vote breakdowns, \
outcomes, or statuses that are not written down. If a meeting has no minutes \
or actions report yet, outcomes should say the item was scheduled/discussed \
per the agenda, and there are no votes.
- Entity names: use the documents' own naming. Ordinances/resolutions keep \
their numbers ('Ordinance 2026-04'). Projects keep their proper names. Do \
not create entities for routine procedure (roll call, adoption of agenda, \
approval of prior minutes) or for council members merely being present.
- status_after is for trackable matters (projects, ordinances, resolutions, \
zoning cases): what state is it in after this meeting?"""


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
        system=SYSTEM_PROMPT,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_meeting_extraction"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("no tool_use block in response")


def _gather_texts(session: Session, meeting: Meeting) -> dict[str, str]:
    docs = session.scalars(
        select(Document).where(
            Document.meeting_id == meeting.id,
            Document.doc_type.in_(["agenda", "minutes", "actions_report"]),
            Document.raw_text.isnot(None),
        )
    ).all()
    texts: dict[str, str] = {}
    for doc in docs:
        # a meeting can have two minutes docs (amended); keep the longest
        if doc.doc_type not in texts or len(doc.raw_text) > len(texts[doc.doc_type]):
            texts[doc.doc_type] = doc.raw_text[:MAX_DOC_CHARS]
    return texts


def _build_prompt(meeting: Meeting, texts: dict[str, str]) -> str:
    parts = [
        f"Meeting: {meeting.title}",
        f"Body: {meeting.body}",
        f"Date: {meeting.meeting_date}",
        "",
        "=== AGENDA ===",
        texts.get("agenda", "(no agenda text available)"),
    ]
    if "minutes" in texts:
        parts += ["", "=== MINUTES ===", texts["minutes"]]
    if "actions_report" in texts:
        parts += ["", "=== OFFICIAL ACTIONS REPORT ===", texts["actions_report"]]
    if "minutes" not in texts and "actions_report" not in texts:
        parts += ["", "(No minutes or actions report exist yet for this meeting — "
                      "record scheduled items only, with no votes or outcomes.)"]
    return "\n".join(parts)


def structure_meeting(session: Session, meeting: Meeting, force: bool = False,
                      reapply_only: bool = False) -> Extraction:
    """Extract (or re-apply) structured facts for one meeting."""
    extraction = session.scalar(
        select(Extraction).where(
            Extraction.meeting_id == meeting.id, Extraction.prompt_version == PROMPT_VERSION
        )
    )
    if extraction and not force and not reapply_only:
        log.info("meeting %s already extracted (%s), skipping", meeting.id, PROMPT_VERSION)
        return extraction

    if reapply_only:
        if not extraction:
            raise ValueError(f"meeting {meeting.id} has no stored extraction to re-apply")
        data = extraction.raw_json
    else:
        texts = _gather_texts(session, meeting)
        if "agenda" not in texts:
            raise ValueError(f"meeting {meeting.id} has no agenda text — run extract-text first")
        data = _call_claude(_build_prompt(meeting, texts))
        if extraction is None:
            extraction = Extraction(meeting_id=meeting.id, prompt_version=PROMPT_VERSION)
            session.add(extraction)
        extraction.model = DEFAULT_MODEL
        extraction.raw_json = data
        session.flush()

    apply_extraction(session, meeting, data)
    meeting.status = "extracted"
    session.commit()
    return extraction


def apply_extraction(session: Session, meeting: Meeting, data: dict) -> None:
    """Deterministically (re)build this meeting's structured rows from an
    extraction dict. Delete + recreate, so re-runs converge."""
    session.execute(update(Document).where(Document.meeting_id == meeting.id)
                    .values(agenda_item_id=None))
    for model in (EntityMention, Vote, EntityUpdate, AgendaItem):
        session.execute(delete(model).where(model.meeting_id == meeting.id))
    session.flush()

    cite_docs = {
        d.doc_type: d
        for d in session.scalars(
            select(Document).where(Document.meeting_id == meeting.id,
                                   Document.doc_type.in_(["minutes", "actions_report", "agenda"]),
                                   Document.raw_text.isnot(None))
        )
    }
    # citation target preference: minutes > actions_report > agenda
    cite_doc = cite_docs.get("minutes") or cite_docs.get("actions_report") or cite_docs.get("agenda")
    cite_doc_id = cite_doc.id if cite_doc else None

    # entity_id -> {"texts": [...], "status": ..., "item_id": ...}
    updates: dict[int, dict] = {}
    seen_labels: set[str] = set()

    for item in data.get("agenda_items", []):
        label = (item.get("label") or "?")[:64]
        if label in seen_labels:
            log.warning("meeting %s: duplicate agenda item label %r, skipping copy",
                        meeting.id, label)
            continue
        seen_labels.add(label)
        row = AgendaItem(
            meeting_id=meeting.id,
            label=label,
            title=item.get("title"),
            description=item.get("description"),
            outcome=item.get("outcome"),
        )
        session.add(row)
        session.flush()

        for vote in item.get("votes", []):
            session.add(Vote(
                meeting_id=meeting.id,
                agenda_item_id=row.id,
                description=vote.get("description"),
                motion_result=vote.get("motion_result"),
                vote_breakdown=vote.get("vote_breakdown") or {},
            ))

        for ent in item.get("entities", []):
            entity = resolve_entity(session, ent.get("entity_type", "topic"), ent.get("name", ""),
                                    first_seen_meeting_id=meeting.id)
            if entity is None:
                continue
            session.add(EntityMention(
                entity_id=entity.id,
                meeting_id=meeting.id,
                agenda_item_id=row.id,
                document_id=cite_doc_id,
                context_text=ent.get("update_text"),
                role=ent.get("role"),
            ))
            u = updates.setdefault(entity.id, {"texts": [], "status": None, "item_id": row.id})
            if ent.get("update_text"):
                u["texts"].append(f"[{label}] {ent['update_text']}")
            if ent.get("status_after"):
                u["status"] = ent["status_after"]

    for entity_id, u in updates.items():
        if not u["texts"]:
            continue
        session.add(EntityUpdate(
            entity_id=entity_id,
            meeting_id=meeting.id,
            agenda_item_id=u["item_id"],
            update_text=" ".join(u["texts"]),
            status_after=u["status"],
        ))
    session.flush()

    _rollup_status(session, list(updates.keys()))


def _rollup_status(session: Session, entity_ids: list[int]) -> None:
    """Set entity.current_status from its chronologically-latest update that
    carries a status_after."""
    for entity_id in entity_ids:
        latest = session.execute(
            select(EntityUpdate.status_after)
            .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
            .where(EntityUpdate.entity_id == entity_id, EntityUpdate.status_after.isnot(None))
            .order_by(Meeting.meeting_date.desc())
            .limit(1)
        ).scalar()
        if latest:
            session.get(Entity, entity_id).current_status = latest


def structure_pending(session: Session, limit: int | None = None) -> dict:
    """Run the structuring pass over every fetched meeting without an
    extraction yet, oldest first (so entity timelines build in order)."""
    sub = select(Extraction.meeting_id).where(Extraction.prompt_version == PROMPT_VERSION)
    q = (
        select(Meeting)
        .where(Meeting.status.in_(["fetched", "extracted"]), Meeting.id.not_in(sub),
               ~Meeting.title.ilike("%cancel%"))
        .order_by(Meeting.meeting_date.asc())
    )
    if limit:
        q = q.limit(limit)
    meetings = session.scalars(q).all()

    done = failed = 0
    for meeting in meetings:
        try:
            structure_meeting(session, meeting)
            done += 1
        except Exception:
            session.rollback()
            log.exception("structuring failed for meeting %s (clip %s)",
                          meeting.id, meeting.granicus_clip_id)
            failed += 1
    return {"structured": done, "failed": failed, "candidates": len(meetings)}
