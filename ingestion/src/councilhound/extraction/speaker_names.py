"""
Speaker naming: who each anonymous diarization label is, per meeting.

Diarization (diarize.py) splits a meeting into SPEAKER_00, SPEAKER_01, ...
Meetings name their speakers out loud: the chair calls on members by name,
staff are introduced, public commenters state their names. One Claude call
per meeting reads the labelled transcript with a roster and maps each label
to a person, citing the cue it relied on.

Publication rule (decided 2026-10-04): a name is shown only when confidence
is 'high' — at least one direct cue (self-identification, or called on by
name and then speaking) — and the label is not mixed. One such cue anywhere
in the meeting names the label for the whole meeting. Medium/low rows are
stored for review but stay "Speaker N" everywhere. Public commenters are
named as they introduced themselves.

Every evidence quote is checked against the transcript: it must appear
within EVIDENCE_WINDOW seconds of its timestamp, next to one of the label's
own turns. A 'high' left with no verified evidence is downgraded to
'medium'. Roster slugs are only accepted for people on this meeting's
roster; anyone else keeps a name and no entity link.

Rows written by hand (source='manual') are never replaced by a re-run.
"""
import json
import logging
import re
from datetime import timedelta

from sqlalchemy import and_, delete, exists, select, update
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.db.models import (
    AgendaItem,
    Entity,
    EntityAlias,
    EntityMention,
    Meeting,
    MeetingSpeaker,
    TranscriptChunk,
    Vote,
)

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
PROMPT_VERSION = "speakers-v1"
EVIDENCE_WINDOW = 90  # seconds either side of a quoted timestamp
ROSTER_DAYS = 90  # members who voted in the same body this close to the meeting
ROLES = ["presiding officer", "member", "staff", "applicant", "public commenter",
         "clerk", "other", "unknown"]
_TITLE = re.compile(r"^(mayor|council ?(member|woman|man)|commissioner|chair|vice[- ]chair|"
                    r"school board|board member|trustee|superintendent)\b", re.I)
# titles that mark someone as a member of a given body — the roster for a
# meeting with no recorded votes yet (a Planning Commission meeting before
# its minutes) comes from these
BODY_TITLES = {
    "city_council": re.compile(r"^(mayor|council ?(member|woman|man))\b", re.I),
    "planning_commission": re.compile(r"^commissioner\b", re.I),
    "school_board": re.compile(r"^school board (member|chair|vice[- ]chair)\b", re.I),
}
_HONORIFIC = {"mr", "mrs", "ms", "miss", "dr", "chief", "mayor", "chair", "councilmember",
              "commissioner", "madam", "sir", "jr", "sr", "ii", "iii"}

SYSTEM = """You identify who is speaking in a public meeting transcript. The transcript was split \
into anonymous speaker labels (SPEAKER_00, ...) by an automatic voice-separation model; labels are \
consistent within this meeting only.

Assign a name to a label ONLY from evidence in the transcript itself:
- self-identification ("My name is ...", "I'm ... with ...")
- being called on immediately before speaking ("Councilmember Hall?" / "Ms. Ritter, please come up" \
followed by that label's turn)
- being addressed by name in a reply immediately after speaking ("Thank you, Mr. Peterson")
- the presiding officer's own conduct of the meeting combined with a name given elsewhere
Never infer a name from opinions, topics or speaking style alone. Votes are recorded elsewhere; do not \
use them as evidence. The transcript is machine-generated, so names may be misspelled \
("Maquillen" for McQuillen); match them to the roster when the cue is otherwise clear.

Known caveats of the voice separation: one person may be split across several labels; a label may \
absorb a few words from another speaker at turn boundaries (e.g. a roll-call "aye"). Judge a label by \
its substantial turns, and set mixed=true only when it holds substantial speech from different people.

Confidence: "high" = at least one direct, unambiguous cue (self-identification, or called on by name \
and responds); "medium" = consistent indirect cues only; "low" = a guess. If there is no cue, set \
name to null. Use roster slugs only for people on the roster; for anyone else (public commenters, \
staff, applicants) give the name as spoken and slug null. Give 1-3 evidence items per named label, \
each with the timestamp shown in the transcript and a short verbatim quote of the cue."""

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["speakers"],
    "properties": {"speakers": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["label", "name", "slug", "role", "confidence", "mixed", "evidence"],
        "properties": {
            "label": {"type": "string"},
            "name": {"type": ["string", "null"]},
            "slug": {"type": ["string", "null"]},
            "role": {"type": "string", "enum": ROLES},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "mixed": {"type": "boolean"},
            "evidence": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["time", "quote"],
                "properties": {"time": {"type": "string"}, "quote": {"type": "string"}}}},
        }}}},
}


def is_public(row: MeetingSpeaker) -> bool:
    """The publication rule: shown on the site, in the API and to /ask."""
    return bool(row.name) and row.confidence == "high" and not row.mixed


def public_speaker_join():
    """is_public() as a join condition from TranscriptChunk to MeetingSpeaker,
    for queries that attach speaker names to chunks (API, /ask)."""
    return and_(MeetingSpeaker.meeting_id == TranscriptChunk.meeting_id,
                MeetingSpeaker.speaker_label == TranscriptChunk.speaker_label,
                MeetingSpeaker.confidence == "high",
                MeetingSpeaker.mixed.is_(False),
                MeetingSpeaker.name.isnot(None))


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _seconds(hms: str) -> float | None:
    parts = hms.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def _last(name: str) -> str:
    return name.replace("-", " ").split()[-1].lower() if name.strip() else ""


def roster(session: Session, meeting: Meeting) -> dict[str, dict]:
    """slug -> {name, entity_id, note} for the people this meeting can link:
    members who voted in this body within ROSTER_DAYS (keyed by surname in
    vote breakdowns), anyone holding this body's title (BODY_TITLES), and
    people the structured record names for this meeting."""
    lo, hi = meeting.meeting_date - timedelta(days=ROSTER_DAYS), meeting.meeting_date + timedelta(days=ROSTER_DAYS)
    breakdowns = session.scalars(
        select(Vote.vote_breakdown).join(AgendaItem, Vote.agenda_item_id == AgendaItem.id)
        .join(Meeting, AgendaItem.meeting_id == Meeting.id)
        .where(Meeting.body == meeting.body, Meeting.meeting_date.between(lo, hi)))
    surnames = {_last(k) for bd in breakdowns for k in (bd or {})}

    titles: dict[int, list[str]] = {}
    for eid, alias in session.execute(
            select(EntityAlias.entity_id, EntityAlias.alias)
            .join(Entity, Entity.id == EntityAlias.entity_id)
            .where(Entity.entity_type == "person")):
        if _TITLE.match(alias):
            titles.setdefault(eid, []).append(alias)

    people = session.scalars(select(Entity).where(Entity.entity_type == "person")).all()
    out: dict[str, dict] = {}
    by_surname: dict[str, list[Entity]] = {}
    for p in people:
        by_surname.setdefault(_last(p.name), []).append(p)
    for s in surnames:
        matches = by_surname.get(s, [])
        if len(matches) > 1:  # unmerged spelling variants: prefer the titled one
            matches = [p for p in matches if p.id in titles] or matches
        for p in matches:
            out[p.canonical_slug] = {"name": p.name, "entity_id": p.id,
                                     "note": "member; titles: " + ", ".join(sorted(titles.get(p.id, []))[:3])}
    body_title = BODY_TITLES.get(meeting.body)
    if body_title:  # titled members of this body, current or former (the mayor rarely votes)
        for p in people:
            held = [a for a in titles.get(p.id, []) if body_title.match(a)]
            if held and p.canonical_slug not in out:
                out[p.canonical_slug] = {"name": p.name, "entity_id": p.id,
                                         "note": "titled: " + ", ".join(sorted(held)[:3])}
    for p, role in session.execute(
            select(Entity, EntityMention.role).join(EntityMention, EntityMention.entity_id == Entity.id)
            .where(EntityMention.meeting_id == meeting.id, Entity.entity_type == "person")):
        out.setdefault(p.canonical_slug, {"name": p.name, "entity_id": p.id, "note": role or "named in record"})
    return out


def _prompt(meeting: Meeting, people: dict[str, dict], items: list[AgendaItem],
            chunks: list[TranscriptChunk], labels: list[str]) -> str:
    lines = [f"Meeting: {meeting.title}, {meeting.meeting_date} ({meeting.body})", "",
             "=== ROSTER (slug: name — note) ==="]
    lines += [f"{slug}: {p['name']} — {p['note']}" for slug, p in sorted(people.items())] or ["(none)"]
    lines += ["", "=== AGENDA ==="] + [f"{it.label} {it.title or ''}" for it in items]
    lines += ["", "=== SPEAKER LABELS TO IDENTIFY ===", ", ".join(labels), "", "=== TRANSCRIPT ==="]
    lines += [f"[{_hms(float(c.start_seconds or 0))}] {c.speaker_label}: {c.text}" for c in chunks]
    return "\n".join(lines)


def _needs_retry(exc: BaseException) -> bool:
    import anthropic
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (429, 500, 502, 503, 529)
    return False


@retry(retry=retry_if_exception(_needs_retry), stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=5, max=120), reraise=True)
def _call_claude(prompt: str) -> tuple[list[dict], str]:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        # server-side fallback: a policy decline is retried on another model
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"speaker naming declined: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("speaker naming hit max_tokens")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["speakers"], response.model


def verify_evidence(label: str, evidence: list[dict], chunks: list[TranscriptChunk]) -> list[dict]:
    """Keep the evidence items whose quote is in the transcript within
    EVIDENCE_WINDOW of its timestamp, in a stretch where this label speaks."""
    kept = []
    for e in evidence or []:
        t = _seconds(e.get("time", ""))
        quote = _norm(e.get("quote", ""))
        if t is None or len(quote) < 3:
            continue
        near = [c for c in chunks
                if abs(float(c.start_seconds or 0) - t) <= EVIDENCE_WINDOW]
        if not any(c.speaker_label == label for c in near):
            continue
        # match on the first 8 words: long quotes are often lightly paraphrased
        head = " ".join(quote.split()[:8])
        if head in _norm(" ".join(c.text for c in near)):
            kept.append({"time": e["time"], "quote": e["quote"]})
    return kept


def name_attested(name: str, transcript_words: set[str]) -> bool:
    """Every word of a name (honorifics aside) is in the transcript, allowing
    small spelling drift. Stops the model writing a name it knows from
    elsewhere ("Brian Lubkin") over the one that was spoken ("Lovegerman")."""
    import difflib

    words = [w for w in re.findall(r"[a-z]+", name.lower()) if w not in _HONORIFIC and len(w) >= 3]
    if not words:
        return False
    return all(w in transcript_words or difflib.get_close_matches(w, transcript_words, n=1, cutoff=0.8)
               for w in words)


def link_chunks(session: Session, meeting_id: int) -> int:
    """Point each chunk at its speaker's entity when the speaker is public and
    on the roster; clear the link otherwise. Returns chunks linked."""
    session.execute(update(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting_id)
                    .values(speaker_entity_id=None))
    linked = 0
    for row in session.scalars(select(MeetingSpeaker).where(MeetingSpeaker.meeting_id == meeting_id)):
        if is_public(row) and row.entity_id:
            linked += session.execute(
                update(TranscriptChunk)
                .where(TranscriptChunk.meeting_id == meeting_id,
                       TranscriptChunk.speaker_label == row.speaker_label)
                .values(speaker_entity_id=row.entity_id)).rowcount
    return linked


def name_meeting(session: Session, meeting: Meeting) -> dict:
    """Name one meeting's speakers; replaces its model rows, keeps manual ones."""
    chunks = session.scalars(
        select(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting.id)
        .order_by(TranscriptChunk.start_seconds, TranscriptChunk.id)).all()
    labels = sorted({c.speaker_label for c in chunks if c.speaker_label})
    if not labels:
        return {"meeting_id": meeting.id, "status": "no_labels"}
    people = roster(session, meeting)
    items = session.scalars(select(AgendaItem).where(AgendaItem.meeting_id == meeting.id)
                            .order_by(AgendaItem.id)).all()
    speakers, model = _call_claude(_prompt(meeting, people, items, chunks, labels))

    manual = set(session.scalars(select(MeetingSpeaker.speaker_label).where(
        MeetingSpeaker.meeting_id == meeting.id, MeetingSpeaker.source == "manual")))
    session.execute(delete(MeetingSpeaker).where(MeetingSpeaker.meeting_id == meeting.id,
                                                 MeetingSpeaker.source == "model"))
    counts = {"high": 0, "medium": 0, "low": 0, "public": 0, "downgraded": 0, "unattested": 0}
    transcript_words = set(re.findall(r"[a-z]+", " ".join(c.text for c in chunks).lower()))
    seen = set()
    for s in speakers:
        label = s["label"]
        if label not in labels or label in manual or label in seen:
            continue
        seen.add(label)
        evidence = verify_evidence(label, s["evidence"], chunks) if s["name"] else []
        confidence = s["confidence"]
        if confidence == "high" and not evidence:
            confidence = "medium"
            counts["downgraded"] += 1
        person = people.get(s["slug"] or "")
        # roster names are trusted spellings; anyone else must be named as spoken
        if confidence == "high" and not person and not name_attested(s["name"] or "", transcript_words):
            confidence = "medium"
            counts["unattested"] += 1
        row = MeetingSpeaker(
            meeting_id=meeting.id, speaker_label=label, name=s["name"],
            entity_id=person["entity_id"] if person else None,
            role=s["role"], confidence=confidence, mixed=s["mixed"], evidence=evidence,
            source="model", model=f"{model}/{PROMPT_VERSION}")
        session.add(row)
        counts[confidence] += 1
        counts["public"] += is_public(row)
    for label in set(labels) - seen - manual:  # the model skipped it: record as unknown
        session.add(MeetingSpeaker(meeting_id=meeting.id, speaker_label=label, confidence="low",
                                   role="unknown", mixed=False, evidence=[], source="model",
                                   model=f"{model}/{PROMPT_VERSION}"))
        counts["low"] += 1
    session.flush()
    counts["linked_chunks"] = link_chunks(session, meeting.id)
    session.commit()
    result = {"meeting_id": meeting.id, "status": "named", "labels": len(labels), **counts}
    log.info("name_speakers %s", result)
    return result


def pending(session: Session, bodies=(), since=None, limit: int | None = None) -> list[Meeting]:
    """Meetings with labelled chunks and no speaker rows yet, newest first.
    The pipeline passes `since` (its look-back window) so a deploy never
    sets off an unreviewed backfill; the backfill is run by hand."""
    labelled = exists().where(TranscriptChunk.meeting_id == Meeting.id,
                              TranscriptChunk.speaker_label.isnot(None))
    named = exists().where(MeetingSpeaker.meeting_id == Meeting.id)
    q = select(Meeting).where(labelled, ~named)
    if bodies:
        q = q.where(Meeting.body.in_(bodies))
    if since:
        q = q.where(Meeting.meeting_date >= since)
    q = q.order_by(Meeting.meeting_date.desc(), Meeting.id.desc())
    if limit:
        q = q.limit(limit)
    return list(session.scalars(q))


def name_pending(session: Session, bodies=(), since=None, limit: int | None = None) -> dict:
    done = failed = public = 0
    for meeting in pending(session, bodies=bodies, since=since, limit=limit):
        try:
            public += name_meeting(session, meeting).get("public", 0)
            done += 1
        except Exception:
            session.rollback()
            log.exception("speaker naming failed for meeting %s", meeting.id)
            failed += 1
    return {"named": done, "failed": failed, "public_speakers": public}


def set_speaker(session: Session, meeting: Meeting, label: str, name: str | None,
                slug: str | None = None, role: str = "other") -> MeetingSpeaker:
    """A hand correction: public at once (confidence high), never replaced by
    a re-run. name=None marks the label as deliberately unnamed."""
    entity_id = None
    if slug:
        entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
        if entity is None:
            raise ValueError(f"no entity with slug {slug!r}")
        entity_id, name = entity.id, name or entity.name
    row = session.scalar(select(MeetingSpeaker).where(
        MeetingSpeaker.meeting_id == meeting.id, MeetingSpeaker.speaker_label == label))
    if row is None:
        row = MeetingSpeaker(meeting_id=meeting.id, speaker_label=label)
        session.add(row)
    row.name, row.entity_id, row.role = name, entity_id, role
    row.confidence, row.mixed, row.source, row.model = "high", False, "manual", None
    row.evidence = [{"time": "", "quote": "set by hand"}]
    session.flush()
    link_chunks(session, meeting.id)
    session.commit()
    return row

