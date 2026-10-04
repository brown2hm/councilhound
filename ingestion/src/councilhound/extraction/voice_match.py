"""
Voice matching: name speakers the transcript didn't, from their voice.

A person's voiceprint is the speech-weighted mean of the fingerprints
(voices.py) of every label already named publicly by the transcript or by
hand — never by an earlier voice match, so a mistake can't feed itself. A
label the transcript left unnamed, medium or low is named when its
fingerprint matches one voiceprint closely and no other comes near.

The rule comes from the Oct 2026 pilot on 20 City Council meetings (514
labels, leave-one-meeting-out): at similarity >= 0.55 no held-out member or
staff label was matched to the wrong person (149/179 recovered) and none of
223 publicly named non-roster speakers matched someone else. The shipped
thresholds are stricter than that, plus a speech floor that rules out the
short labels where every miss happened:
  similarity >= MIN_SCORE, ahead of the next voiceprint by >= MIN_MARGIN,
  >= MIN_SPEECH seconds of fingerprinted speech, voiceprint from
  >= MIN_PRINT_MEETINGS other meetings.

Re-checked on all stored production fingerprints (Oct 4 2026, 129 meetings):
the only genuine false matches were an outside engineer scoring 0.75
against a Planning Commissioner and a mixed staff/commissioner label at
0.76, so MIN_SCORE was raised from 0.65 to 0.80; correct matches cluster at
0.85-0.97. Other apparent errors were duplicate person entities (merged).
All three recorded bodies are enabled; add a body only after
re-running that evaluation on it. Voice never
overrides a transcript-public name, a hand correction, a student or a mixed
label. Where a transcript-public member and a strong voice match disagree,
`disagreements()` reports it for review and changes nothing.
"""
import logging
from collections import Counter, defaultdict

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, Meeting, MeetingSpeaker, SpeakerVoice
from councilhound.extraction.speaker_names import is_public, link_chunks

log = logging.getLogger(__name__)

MIN_SCORE = 0.80
MIN_MARGIN = 0.25
MIN_SPEECH = 20.0
MIN_PRINT_MEETINGS = 2
DISAGREE_SCORE = 0.75
VOICE_BODIES = {"city_council", "school_board", "planning_commission"}


class Voiceprints:
    """Every public, entity-linked, non-voice label's fingerprint, loaded
    once; prints() leaves out one meeting so a label is never matched against
    its own voice."""

    def __init__(self, session: Session, body: str):
        import numpy as np

        self.np = np
        q = (select(SpeakerVoice, MeetingSpeaker)
             .join(MeetingSpeaker, and_(MeetingSpeaker.meeting_id == SpeakerVoice.meeting_id,
                                        MeetingSpeaker.speaker_label == SpeakerVoice.speaker_label))
             .join(Meeting, Meeting.id == SpeakerVoice.meeting_id)
             .where(Meeting.body == body, MeetingSpeaker.entity_id.isnot(None),
                    MeetingSpeaker.source.in_(("model", "manual"))))
        self.samples = []  # (entity_id, meeting_id, vector, seconds)
        roles: dict[int, Counter] = defaultdict(Counter)
        for voice, row in session.execute(q):
            if is_public(row):
                self.samples.append((row.entity_id, voice.meeting_id,
                                     np.asarray(voice.embedding, dtype=float), float(voice.speech_seconds)))
                roles[row.entity_id][row.role] += 1
        self.role = {e: c.most_common(1)[0][0] for e, c in roles.items()}

    def prints(self, exclude_meeting: int) -> dict[int, tuple]:
        np = self.np
        acc: dict[int, list] = defaultdict(list)
        for entity_id, meeting_id, vec, sec in self.samples:
            if meeting_id != exclude_meeting:
                acc[entity_id].append((meeting_id, vec, sec))
        out = {}
        for entity_id, items in acc.items():
            meetings = {m for m, _, _ in items}
            if len(meetings) < MIN_PRINT_MEETINGS:
                continue
            mean = sum(v * s for _, v, s in items) / sum(s for _, _, s in items)
            out[entity_id] = (mean / np.linalg.norm(mean), len(meetings))
        return out

    def best(self, vec, prints: dict) -> tuple:
        """(entity_id, score, second_score, print_meetings) or (None, ...)."""
        if not prints:
            return None, 0.0, 0.0, 0
        v = self.np.asarray(vec, dtype=float)
        scored = sorted(((float(v @ p), e, n) for e, (p, n) in prints.items()), reverse=True)
        second = scored[1][0] if len(scored) > 1 else -1.0
        return scored[0][1], scored[0][0], second, scored[0][2]


def _eligible(row: MeetingSpeaker | None) -> bool:
    """Labels voice may name: unnamed by the transcript or not public, never
    a hand correction, a student or a mixed label."""
    if row is None:
        return True
    if row.source == "manual" or row.mixed or row.role == "student":
        return False
    return row.source == "voice" or not is_public(row)


def match_meeting(session: Session, meeting: Meeting, prints_cache: dict | None = None) -> dict:
    """Voice-name this meeting's eligible labels. Re-runnable: earlier voice
    names are recomputed and withdrawn if they no longer clear the rule."""
    result = {"meeting_id": meeting.id, "named": 0, "withdrawn": 0, "candidates": 0}
    if meeting.body not in VOICE_BODIES:
        result["status"] = "body_not_enabled"
        return result
    cache = prints_cache if prints_cache is not None else {}
    vp = cache.get(meeting.body) or cache.setdefault(meeting.body, Voiceprints(session, meeting.body))
    prints = vp.prints(meeting.id)
    rows = {r.speaker_label: r for r in session.scalars(
        select(MeetingSpeaker).where(MeetingSpeaker.meeting_id == meeting.id))}
    for voice in session.scalars(select(SpeakerVoice).where(SpeakerVoice.meeting_id == meeting.id)):
        row = rows.get(voice.speaker_label)
        if not _eligible(row):
            continue
        result["candidates"] += 1
        entity_id, score, second, n = vp.best(voice.embedding, prints)
        ok = (entity_id is not None and score >= MIN_SCORE and score - second >= MIN_MARGIN
              and float(voice.speech_seconds) >= MIN_SPEECH)
        if ok:
            entity = session.get(Entity, entity_id)
            if row is None:
                row = MeetingSpeaker(meeting_id=meeting.id, speaker_label=voice.speaker_label)
                session.add(row)
            row.name, row.entity_id = entity.name, entity_id
            row.role = vp.role.get(entity_id, "other")
            row.confidence, row.mixed, row.source, row.model = "high", False, "voice", None
            row.evidence = [{"time": "", "quote": f"voice match {score:.2f} (next {second:.2f}), "
                                                  f"voiceprint from {n} meetings"}]
            result["named"] += 1
        elif row is not None and row.source == "voice":
            row.name, row.entity_id, row.confidence, row.role = None, None, "low", "unknown"
            row.evidence = [{"time": "", "quote": f"voice match withdrawn ({score:.2f})"}]
            result["withdrawn"] += 1
    session.flush()
    link_chunks(session, meeting.id)
    session.commit()
    result["status"] = "matched"
    return result


def match_pending(session: Session, bodies=(), since=None) -> dict:
    """Voice-match every fingerprinted meeting in the enabled bodies (or those
    since `since`). Deterministic and cheap: no model calls."""
    q = select(Meeting).where(Meeting.body.in_(bodies or VOICE_BODIES),
                              Meeting.id.in_(select(SpeakerVoice.meeting_id)))
    if since:
        q = q.where(Meeting.meeting_date >= since)
    cache: dict = {}
    named = withdrawn = failed = 0
    meetings = list(session.scalars(q.order_by(Meeting.meeting_date.desc())))
    for meeting in meetings:
        try:
            r = match_meeting(session, meeting, cache)
        except Exception:
            session.rollback()
            log.exception("voice matching failed for meeting %s", meeting.id)
            failed += 1
            continue
        named += r["named"]
        withdrawn += r["withdrawn"]
    return {"meetings": len(meetings), "voice_named": named, "withdrawn": withdrawn, "failed": failed}


def disagreements(session: Session, body: str = "city_council") -> list[dict]:
    """Transcript-public members whose voice strongly says someone else."""
    vp = Voiceprints(session, body)
    out = []
    q = (select(SpeakerVoice, MeetingSpeaker, Meeting)
         .join(MeetingSpeaker, and_(MeetingSpeaker.meeting_id == SpeakerVoice.meeting_id,
                                    MeetingSpeaker.speaker_label == SpeakerVoice.speaker_label))
         .join(Meeting, Meeting.id == SpeakerVoice.meeting_id)
         .where(Meeting.body == body, MeetingSpeaker.entity_id.isnot(None),
                MeetingSpeaker.source == "model"))
    by_meeting: dict[int, dict] = {}
    for voice, row, meeting in session.execute(q):
        if not is_public(row) or float(voice.speech_seconds) < MIN_SPEECH:
            continue
        prints = by_meeting.get(meeting.id) or by_meeting.setdefault(meeting.id, vp.prints(meeting.id))
        entity_id, score, second, _ = vp.best(voice.embedding, prints)
        if (entity_id is not None and entity_id != row.entity_id and score >= DISAGREE_SCORE
                and score - second >= MIN_MARGIN):
            out.append({"clip": meeting.granicus_clip_id, "date": meeting.meeting_date.isoformat(),
                        "label": row.speaker_label, "transcript_says": row.name,
                        "voice_says": session.get(Entity, entity_id).name, "score": round(score, 2)})
    return out



def _same_person(a: str | None, b: str | None) -> bool:
    """Loose surname match, for telling spelling variants (Napty / Nabti,
    Ito / Eto) apart from genuinely different people in evaluate()."""
    import difflib
    import re

    wa = re.findall(r"[a-z]+", (a or "").lower())
    wb = re.findall(r"[a-z]+", (b or "").lower())
    if not wa or not wb:
        return False
    if len(wa) == 1 and wa[0] == wb[0]:  # "Melanie" for Melanie Zipp
        return True
    return difflib.SequenceMatcher(None, wa[-1], wb[-1]).ratio() >= 0.5


def evaluate(session: Session, body: str, min_score: float = MIN_SCORE) -> dict:
    """Leave-one-meeting-out check of the rule on stored fingerprints, for
    any body (enabled or not). Run it before changing thresholds or adding a
    body: this is how the 0.65 -> 0.80 change and the duplicate entities were
    found. Read-only.

    - known: publicly named, entity-linked labels; would the rule, ignoring
      their own meeting, give each the right person?
    - outsiders: publicly named people with no entity (commenters, most
      applicants) have no voiceprint, so any rule-passing match is the error
      voice naming could make on an unnamed outsider. Matches whose names look
      like spelling variants of the same person are counted apart.
    - would_name: labels the rule names (already voice-named, or new on the
      next run)."""
    vp = Voiceprints(session, body)
    rows = session.execute(
        select(SpeakerVoice, MeetingSpeaker, Meeting)
        .join(MeetingSpeaker, and_(MeetingSpeaker.meeting_id == SpeakerVoice.meeting_id,
                                   MeetingSpeaker.speaker_label == SpeakerVoice.speaker_label))
        .join(Meeting, Meeting.id == SpeakerVoice.meeting_id)
        .where(Meeting.body == body)).all()
    prints: dict[int, dict] = {}
    names: dict[int, str] = {}
    out = {"body": body, "min_score": min_score, "meetings": len({m.id for _, _, m in rows}),
           "known": 0, "matched": 0, "correct": 0, "wrong": [],
           "outsiders": 0, "outsider_same_person": 0, "outsider_different": [], "would_name": 0}
    for voice, row, meeting in rows:
        if meeting.id not in prints:
            prints[meeting.id] = vp.prints(meeting.id)
        entity_id, score, second, _ = vp.best(voice.embedding, prints[meeting.id])
        passes = (entity_id is not None and score >= min_score and score - second >= MIN_MARGIN
                  and float(voice.speech_seconds) >= MIN_SPEECH)
        if passes and entity_id not in names:
            names[entity_id] = session.get(Entity, entity_id).name
        where = {"clip": meeting.granicus_clip_id, "date": meeting.meeting_date.isoformat(),
                 "label": row.speaker_label, "score": round(score, 2)}
        if is_public(row) and row.entity_id and row.source in ("model", "manual"):
            out["known"] += 1
            if passes:
                out["matched"] += 1
                if entity_id == row.entity_id:
                    out["correct"] += 1
                else:
                    out["wrong"].append({**where, "name": row.name, "voice": names[entity_id]})
        elif is_public(row) and not row.entity_id:
            out["outsiders"] += 1
            if passes:
                if _same_person(row.name, names[entity_id]):
                    out["outsider_same_person"] += 1
                else:
                    out["outsider_different"].append({**where, "name": row.name, "role": row.role,
                                                      "voice": names[entity_id]})
        elif passes and _eligible(row):
            out["would_name"] += 1
    return out
