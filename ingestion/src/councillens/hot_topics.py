"""
Hot-topic scoring: rank entities by how much meeting time they consumed
recently.

Transcript chunks carry start/end timestamps, so "discussion time" for an
entity = sum of durations of chunks (from the N most recent transcribed
meetings) whose text mentions the entity by name or alias. Deterministic,
no LLM, computed live — the score shifts as soon as a new transcript lands.

Honest limits: only transcribed meetings count, and pronoun references
("the project") don't match — this measures *named* discussion time, a
lower bound that is consistent across topics.
"""
import logging
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councillens.db.models import Entity, EntityAlias, Meeting, TranscriptChunk

log = logging.getLogger(__name__)

MIN_VARIANT_LEN = 5  # skip short aliases ('Read') that match unrelated speech


def recent_transcribed_meetings(session: Session, n: int = 3) -> list[Meeting]:
    sub = select(TranscriptChunk.meeting_id).distinct().subquery()
    return list(session.scalars(
        select(Meeting).join(sub, Meeting.id == sub.c.meeting_id)
        .order_by(Meeting.meeting_date.desc()).limit(n)
    ))


def hot_topics(session: Session, n_meetings: int = 3, top: int = 30) -> dict:
    meetings = recent_transcribed_meetings(session, n_meetings)
    if not meetings:
        return {"meetings": [], "topics": []}
    meeting_ids = [m.id for m in meetings]

    chunks = session.execute(
        select(TranscriptChunk.meeting_id, TranscriptChunk.text,
               TranscriptChunk.start_seconds, TranscriptChunk.end_seconds)
        .where(TranscriptChunk.meeting_id.in_(meeting_ids))
    ).all()

    entities = session.scalars(select(Entity).where(Entity.entity_type != "person")).all()
    aliases = defaultdict(list)
    for alias in session.execute(select(EntityAlias.entity_id, EntityAlias.alias)).all():
        aliases[alias.entity_id].append(alias.alias)

    variants: list[tuple[int, list[str]]] = []
    for e in entities:
        names = {v.lower() for v in [e.name, *aliases.get(e.id, [])]
                 if v and len(v) >= MIN_VARIANT_LEN}
        if names:
            variants.append((e.id, list(names)))

    seconds: dict[int, float] = defaultdict(float)
    mentions: dict[int, int] = defaultdict(int)
    per_meeting: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for meeting_id, text, start, end in chunks:
        text_l = text.lower()
        duration = float(end - start) if (start is not None and end is not None) else 0.0
        for entity_id, names in variants:
            if any(n in text_l for n in names):
                seconds[entity_id] += duration
                mentions[entity_id] += 1
                per_meeting[entity_id][meeting_id] += duration

    by_id = {e.id: e for e in entities}
    ranked = sorted(seconds.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return {
        "meetings": [
            {"id": m.id, "title": m.title, "date": m.meeting_date.isoformat()}
            for m in meetings
        ],
        "topics": [
            {
                "slug": by_id[eid].canonical_slug,
                "name": by_id[eid].name,
                "entity_type": by_id[eid].entity_type,
                "current_status": by_id[eid].current_status,
                "seconds": round(secs),
                "chunk_mentions": mentions[eid],
                "per_meeting": {str(mid): round(s) for mid, s in per_meeting[eid].items()},
            }
            for eid, secs in ranked if secs > 0
        ],
    }
