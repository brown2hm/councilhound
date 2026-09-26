"""
Phase 3: LLM structuring pass.

One structured-output (tool-use) call per meeting: agenda + minutes +
actions report go in (max observed ~44KB — comfortably one call; the
transcript deliberately stays out, it's for citations/Q&A, not facts).
Claude returns agenda items, votes, and entity updates; we then:

  1. store the raw output in `extractions` keyed by (meeting_id,
     PROMPT_VERSION) — re-apply or diff prompts without new LLM calls;
  2. resolve every entity name via councilhound.entities (slug -> alias ->
     create) — the model never controls canonical identity;
  3. rebuild the meeting's agenda_items / votes / entity_updates /
     entity_mentions rows from scratch (delete + recreate), so a re-run
     converges to the same rows instead of duplicating.

current_status on each touched entity is rolled up from its latest
entity_update with a status_after.
"""
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.db.models import (
    AgendaItem,
    Document,
    Entity,
    EntityMention,
    EntityUpdate,
    Extraction,
    Meeting,
    Vote,
)
from councilhound.bodies import REGISTRY, is_self_reference, label as body_label
from councilhound.config import JURISDICTION
from councilhound.jurisdiction import JurisdictionConfig
from councilhound.entities import resolve_entity

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
# defensive truncation (the City's largest observed doc is ~44KB; the County's
# annotated agendas run longer, so the ceiling is per jurisdiction)
MAX_DOC_CHARS = JURISDICTION.extraction.max_doc_chars
MAX_OUTPUT_TOKENS = JURISDICTION.extraction.max_output_tokens

ENTITY_TYPES = ["person", "project", "ordinance", "resolution", "case_number", "location", "topic"]
STATUSES = ["proposed", "in_progress", "approved", "denied", "deferred", "completed", "withdrawn"]
# Unitemized parts of a meeting a remark can come from. Each becomes the
# one-word marker on its update text ("[comments] ..."), the way an item's
# label does ("[7a] ..."); the frontend strips \[\w+\] markers.
PERIODS = ["comments", "reports", "public", "announcements", "other"]
PERIOD_LABELS = {"comments": "member comments", "reports": "staff and committee reports",
                 "public": "public comment", "announcements": "announcements", "other": "other business"}

ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "entity_type": {"type": "string", "enum": ENTITY_TYPES},
        "name": {
            "type": "string",
            "description": "Proper name as the documents use it, e.g. 'Main Street Trail', 'Ordinance 2026-04'.",
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
}

def _quoted(items: list[str]) -> str:
    return ", ".join(f"'{i}'" for i in items)


EXTRACTION_TOOL = {
    "name": "record_meeting_extraction",
    "description": "Record the structured facts extracted from one public-body meeting.",
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
                                        "description": "Member last name -> yes|no|abstain|absent. Copy a recorded roll call as is. When the minutes say the motion passed (or failed) unanimously and record who was present, list every member recorded present as yes (no if it failed unanimously) and every member recorded absent as absent; a unanimous result plus recorded attendance is a complete breakdown. Empty only when neither a roll call nor attendance is recorded.",
                                        "additionalProperties": {"type": "string", "enum": ["yes", "no", "abstain", "absent"]},
                                    },
                                },
                                "required": ["description", "motion_result"],
                            },
                        },
                        "entities": {
                            "type": "array",
                            "description": "Projects, ordinances, locations, people (other than routine member attendance), and topics THIS ITEM ITSELF concerned. Remarks made during a comments period, a staff report or public comment go in other_discussion (or under the agenda's own comments item), never under the nearest numbered item.",
                            "items": ENTITY_SCHEMA,
                        },
                    },
                    "required": ["label", "title", "outcome"],
                },
            },
            "other_discussion": {
                "type": "array",
                "description": "Matters raised OUTSIDE any numbered agenda item, when the agenda has no item for that period: member/council/commission comments, committee reports, staff or manager reports, public comment, announcements. Each carries the period it came up in. If the agenda does list such a period as an item ("
                               + _quoted(JURISDICTION.extraction.comment_period_items or ["Council Comments and Committee reports out", "Commission Comments"])
                               + "), file the remark under that item instead and leave this empty.",
                "items": {
                    "type": "object",
                    "properties": {
                        **ENTITY_SCHEMA["properties"],
                        "period": {"type": "string", "enum": PERIODS,
                                   "description": "Which unitemized part of the meeting the remark came from."},
                    },
                    "required": ["entity_type", "name", "update_text", "period"],
                },
            },
        },
        "required": ["summary", "agenda_items"],
    },
}

def build_system_prompt(cfg: JurisdictionConfig) -> str:
    """The extraction system prompt with the jurisdiction's vocabulary: its
    noun, the bodies it tracks, the agenda items that are comment periods,
    and any note about how its bodies record votes."""
    bodies = [b.label for b in cfg.bodies]
    if bodies:
        body_list = ", ".join(bodies[:3]) + ", advisory boards and committees"
    else:
        body_list = "council, commissions, advisory boards and committees"
    examples = _quoted(cfg.extraction.comment_period_items
                       or ["Council Comments and Committee reports out", "Commission Comments"])
    vote_notes = " ".join(cfg.extraction.vote_notes)
    vote_line = (" " + vote_notes) if vote_notes else ""
    noun = cfg.identity.noun
    return (
        "You extract structured facts from municipal meeting records (agenda, minutes, "
        "and an official actions report when available). Rules:\n"
        "- The minutes and actions report are the source of truth for outcomes and "
        "votes; the agenda alone only tells you what was scheduled.\n"
        "- Record only what the documents state. Never invent vote breakdowns, "
        "outcomes, or statuses that are not written down. If a meeting has no minutes "
        "or actions report yet, outcomes should say the item was scheduled/discussed "
        "per the agenda, and there are no votes.\n"
        "- One derivation is allowed because it follows from the record: when the "
        "minutes say a motion passed or failed \"unanimously\" and elsewhere record who "
        "was present (roll call, attendance, \"Members present\"), fill vote_breakdown "
        "with every present member (yes for passed, no for failed) and mark members "
        "recorded absent as absent. Use the attendance as of that item if the minutes "
        f"note someone arriving or leaving.{vote_line}\n"
        "- Entity names: use the documents' own naming. Ordinances/resolutions keep "
        "their numbers ('Ordinance 2026-04'). Projects keep their proper names. Do "
        "not create entities for routine procedure (roll call, adoption of agenda, "
        "approval of prior minutes) or for members merely being present.\n"
        "- status_after is for trackable matters (projects, ordinances, resolutions, "
        "zoning cases): what state is it in after this meeting?\n"
        f"- The {noun} itself and its own bodies ({body_list}) are the actors, never "
        "entities. A \"Planning Commission update\" or \"liaison report\" item gets "
        "entities for what was reported on, not for the body.\n"
        "- An agenda item's entities are only what that item itself concerned. A "
        "matter raised during member comments, committee or staff reports, public "
        "comment or announcements is NOT part of the item the minutes happen to "
        "print it after. If the agenda lists that period as its own item "
        f"({examples}), file the remark under that item; if it does not, put it in "
        "other_discussion with its period. Never file such a remark under the last "
        "numbered item of the night."
    )


SYSTEM_PROMPT = build_system_prompt(JURISDICTION)


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
    # streamed so a large output budget cannot trip the HTTP timeout; the
    # final message is what a plain create() would have returned
    with client.messages.stream(
        model=DEFAULT_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_meeting_extraction"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "max_tokens":
        # a truncated tool call parses to a hollow dict (summary only); storing
        # it would mark the meeting extracted with no items. Fail loudly instead.
        raise ValueError(
            f"extraction output truncated at {MAX_OUTPUT_TOKENS} tokens — raise "
            "extraction.max_output_tokens for this jurisdiction")
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


def _known_entities(session: Session, texts: dict[str, str], top: int = 60) -> list[str]:
    """Canonical names of already-tracked non-person entities that this
    meeting's documents mention — handed to the model so recurring threads
    keep one name instead of drifting ('Courthouse Plaza Redevelopment' when
    'Courthouse Plaza' already exists). Matching mirrors hot_topics."""
    from councilhound.db.models import Entity, EntityAlias
    from councilhound.hot_topics import MIN_VARIANT_LEN

    blob = " ".join(texts.values()).lower()
    if not blob.strip():
        return []
    alias_rows = session.execute(select(EntityAlias.entity_id, EntityAlias.alias)).all()
    aliases: dict[int, list[str]] = {}
    for entity_id, alias in alias_rows:
        aliases.setdefault(entity_id, []).append(alias)

    known = []
    for e in session.scalars(select(Entity).where(Entity.entity_type != "person")):
        variants = {v.lower() for v in [e.name, *aliases.get(e.id, [])]
                    if v and len(v) >= MIN_VARIANT_LEN}
        if any(v in blob for v in variants):
            known.append(e.name)
        if len(known) >= top:
            break
    return known


def _build_prompt(meeting: Meeting, texts: dict[str, str],
                  known_entities: list[str] | None = None) -> str:
    parts = [
        f"Meeting: {meeting.title}",
        f"Body: {body_label(meeting.body)}",
        f"Date: {meeting.meeting_date}",
    ]
    body_cfg = REGISTRY.bodies.get(meeting.body)
    if body_cfg and body_cfg.agenda_has_outcomes and "agenda" in texts:
        parts += [
            "",
            "Note: this body publishes an annotated agenda — each item carries its "
            "official outcome ('Approved', 'Deferred', 'Done', 'Held', ...). Treat "
            "those outcomes as the record of what happened; a roll call is rarely "
            "printed, so record outcomes and leave vote breakdowns empty unless "
            "members' votes are listed by name.",
        ]
    if known_entities:
        parts += [
            "",
            "=== ALREADY-TRACKED ENTITIES ===",
            "These entities exist in the tracker and appear in this meeting's "
            "documents. When an agenda item concerns one of them, use EXACTLY "
            "this name for the entity (do not append words like 'Project', "
            "'Redevelopment', or an acronym):",
            *(f"- {name}" for name in known_entities),
        ]
    parts += [
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
        data = _call_claude(_build_prompt(meeting, texts, _known_entities(session, texts)))
        if extraction is None:
            extraction = Extraction(meeting_id=meeting.id, prompt_version=PROMPT_VERSION)
            session.add(extraction)
        extraction.model = DEFAULT_MODEL
        extraction.raw_json = data
        # a re-extraction is a NEW extraction of newer inputs: refresh the
        # timestamp so the late-document trigger sees the meeting as current
        # again instead of re-firing every night
        extraction.created_at = datetime.now(timezone.utc)
        session.flush()

    apply_extraction(session, meeting, data)
    meeting.status = "extracted"
    session.commit()
    return extraction


_COMMENTS_ITEM = re.compile(r"\b(comments?|reports? out|announcements)\b", re.I)
_COMMENT_PERIOD = re.compile(
    r"\b(during|in|under|at|as part of) (the )?"
    r"(council(member| member)?|commission(er)?|member|board( member)?|mayor'?s?|closing|final|general)s? "
    r"(comments?|remarks|reports?)\b", re.I)


_COMMENT_ITEM_NAMES = tuple(n.lower() for n in JURISDICTION.extraction.comment_period_items)


def _is_comments_item(title: str | None) -> bool:
    """Is this agenda item itself the comments/reports period?"""
    if not title:
        return False
    return bool(_COMMENTS_ITEM.search(title)) or title.strip().lower() in _COMMENT_ITEM_NAMES


def _from_comment_period(update_text: str | None) -> bool:
    """Does the extractor's own sentence say the remark came from a comments
    or reports period ("During council comments, ...")?"""
    return bool(update_text) and bool(_COMMENT_PERIOD.search(update_text))


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
    # Votes exist only in the record of what happened. Given just an agenda
    # (and packet), the model has filed the packet's sample motions and the
    # routine procedure as passed votes; the prompt forbids it and this makes
    # the rule hold whatever the model does.
    body_cfg = REGISTRY.bodies.get(meeting.body)
    has_record = bool(cite_docs.get("minutes") or cite_docs.get("actions_report")) \
        or bool(body_cfg and body_cfg.agenda_has_outcomes and cite_docs.get("agenda"))
    dropped_votes = skipped_self = 0

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
            if not has_record:
                dropped_votes += 1
                continue
            session.add(Vote(
                meeting_id=meeting.id,
                agenda_item_id=row.id,
                description=vote.get("description"),
                motion_result=vote.get("motion_result"),
                vote_breakdown=vote.get("vote_breakdown") or {},
            ))

        comments_item = _is_comments_item(item.get("title"))
        for ent in item.get("entities", []):
            if is_self_reference(ent.get("name")):
                skipped_self += 1
                continue
            entity = resolve_entity(session, ent.get("entity_type", "topic"), ent.get("name", ""),
                                    first_seen_meeting_id=meeting.id)
            if entity is None:
                continue
            # extractions made before the other_discussion bucket existed
            # filed comment-period remarks under whatever item came last;
            # unfile those on re-apply so they stop joining that item's votes
            stray = not comments_item and _from_comment_period(ent.get("update_text"))
            item_id = None if stray else row.id
            marker = "comments" if stray else label
            session.add(EntityMention(
                entity_id=entity.id,
                meeting_id=meeting.id,
                agenda_item_id=item_id,
                document_id=cite_doc_id,
                context_text=ent.get("update_text"),
                role=ent.get("role"),
            ))
            u = updates.setdefault(entity.id, {"texts": [], "status": None, "item_id": item_id})
            if ent.get("update_text"):
                u["texts"].append(f"[{marker}] {ent['update_text']}")
            if ent.get("status_after"):
                u["status"] = ent["status_after"]

    # remarks from a period the agenda had no item for: on the meeting, no item
    for ent in data.get("other_discussion", []) or []:
        period = ent.get("period") if ent.get("period") in PERIODS else "other"
        if is_self_reference(ent.get("name")):
            skipped_self += 1
            continue
        entity = resolve_entity(session, ent.get("entity_type", "topic"), ent.get("name", ""),
                                first_seen_meeting_id=meeting.id)
        if entity is None:
            continue
        session.add(EntityMention(
            entity_id=entity.id,
            meeting_id=meeting.id,
            agenda_item_id=None,
            document_id=cite_doc_id,
            context_text=ent.get("update_text"),
            role=ent.get("role") or PERIOD_LABELS[period],
        ))
        u = updates.setdefault(entity.id, {"texts": [], "status": None, "item_id": None})
        if ent.get("update_text"):
            u["texts"].append(f"[{period}] {ent['update_text']}")
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
    if dropped_votes or skipped_self:
        log.info("meeting %s: dropped %d vote(s) recorded without minutes or an actions "
                 "report, skipped %d self-reference entit%s",
                 meeting.id, dropped_votes, skipped_self, "y" if skipped_self == 1 else "ies")

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


def late_document_meetings(session: Session) -> list[Meeting]:
    """Meetings whose minutes or actions report arrived AFTER their extraction.

    Minutes post weeks after a meeting (they are approved at the next one) and
    the official actions report typically posts a day or two later, so the
    nightly job routinely extracts a fresh meeting from its agenda alone —
    recording scheduled items with no votes or outcomes, as instructed. Nothing
    then revisited the meeting when the decision documents landed: the
    extraction row existed, so structure_pending skipped it forever and the
    homepage never saw the meeting's votes. Comparing Document.fetched_at
    against Extraction.created_at (which a re-extraction refreshes) makes the
    trigger fire exactly once per late arrival.
    """
    q = (
        select(Meeting)
        .join(Extraction, (Extraction.meeting_id == Meeting.id)
              & (Extraction.prompt_version == PROMPT_VERSION))
        .join(Document, Document.meeting_id == Meeting.id)
        .where(Document.doc_type.in_(("minutes", "actions_report")),
               Document.raw_text.isnot(None),
               Document.fetched_at.isnot(None),
               Document.fetched_at > Extraction.created_at)
        .order_by(Meeting.meeting_date.asc())
        .distinct()
    )
    return list(session.scalars(q).all())


def structure_pending(session: Session, limit: int | None = None) -> dict:
    """Run the structuring pass over every fetched meeting without an
    extraction yet (oldest first, so entity timelines build in order), then
    re-run it for meetings whose minutes/actions report arrived late."""
    sub = select(Extraction.meeting_id).where(Extraction.prompt_version == PROMPT_VERSION)
    # Structuring needs agenda text. A meeting with no agenda document at all
    # (a swearing-in that is recording-only) or whose agenda has no text yet
    # (a scanned PDF, or a file on another machine) would fail identically on
    # every hourly run, so it is not a candidate until text exists.
    has_agenda_text = select(Document.meeting_id).where(
        Document.doc_type == "agenda", Document.raw_text.isnot(None))
    q = (
        select(Meeting)
        .where(Meeting.status.in_(["fetched", "extracted"]), Meeting.id.not_in(sub),
               Meeting.id.in_(has_agenda_text),
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

    stale = late_document_meetings(session)
    restructured = 0
    for meeting in stale:
        try:
            log.info("re-extracting meeting %s (%s): minutes/actions report "
                     "arrived after the stored extraction",
                     meeting.id, meeting.meeting_date)
            structure_meeting(session, meeting, force=True)
            restructured += 1
        except Exception:
            session.rollback()
            log.exception("re-extraction failed for meeting %s (clip %s)",
                          meeting.id, meeting.granicus_clip_id)
            failed += 1
    return {"structured": done, "restructured": restructured, "failed": failed,
            "candidates": len(meetings) + len(stale)}
