"""
Re-transcribe meetings that were transcribed before speaker diarization
(PR #26, Oct 2026), so their chunks carry speaker labels and lose the
looping text the old Whisper settings produced over music and silence.

Per meeting, newest first:
  1. download the MP3 to a scratch dir (residential IP only — Granicus
     blocks cloud ranges); audio_local_path is not touched
  2. Whisper + diarization via transcript.py; no speaker turns -> refuse
     (a re-run must not swap labelled-by-design chunks for unlabelled ones)
  3. coverage gate: the new transcript must keep >= min_coverage of the old
     one's words, after looping junk is removed from both; else keep the old
  4. embed the new chunks, then delete old + insert new in one commit, so
     readers, search and /ask never see the meeting half-replaced
  5. delete the audio, append a line to DATA_DIR/retranscribe-log.jsonl

Resumable: a meeting with any labelled chunk counts as done.
Nothing references chunk ids (entity_mentions.transcript_chunk_id has never
been written), so replacing rows is safe. Back up transcript_chunks first.
"""
import json
import logging
import os
import re
import time
from datetime import date, datetime

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from councilhound import http
from councilhound.config import DATA_DIR
from councilhound.db.models import Meeting, SpeakerVoice, TranscriptChunk
from councilhound.extraction.diarize import diarize
from councilhound.extraction.transcript import assign_speakers, merge_segments, transcribe_audio

log = logging.getLogger(__name__)

MIN_COVERAGE = 0.9
# a 1-4 word phrase repeated 9+ times in a row: whisper's looping output
_LOOP = re.compile(r"\b(\w+(?: \w+){0,3}[.,?!]?)(?: \1){8,}")
LOG_PATH = os.path.join(DATA_DIR, "retranscribe-log.jsonl")


def word_count(text: str) -> int:
    """Words in text once whisper's looping runs are cut out."""
    return len(_LOOP.sub(" ", text.lower()).split())


def coverage(old_texts: list[str], new_texts: list[str]) -> float:
    old = sum(word_count(t) for t in old_texts)
    return sum(word_count(t) for t in new_texts) / old if old else 1.0


def candidates(session: Session, bodies=(), since: date | None = None,
               until: date | None = None, clip_id: str | None = None,
               limit: int | None = None) -> list[Meeting]:
    """Transcribed meetings with no labelled chunk yet, newest first."""
    has_chunks = exists().where(TranscriptChunk.meeting_id == Meeting.id)
    has_label = exists().where(TranscriptChunk.meeting_id == Meeting.id,
                               TranscriptChunk.speaker_label.isnot(None))
    q = select(Meeting).where(has_chunks, ~has_label, Meeting.audio_url.isnot(None))
    if clip_id:
        q = q.where(Meeting.granicus_clip_id == clip_id)
    if bodies:
        q = q.where(Meeting.body.in_(bodies))
    if since:
        q = q.where(Meeting.meeting_date >= since)
    if until:
        q = q.where(Meeting.meeting_date <= until)
    q = q.order_by(Meeting.meeting_date.desc(), Meeting.id.desc())
    if limit:
        q = q.limit(limit)
    return list(session.scalars(q))


def _log(record: dict) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), **record}) + "\n")


def retranscribe_meeting(session: Session, meeting: Meeting, workdir: str,
                         min_coverage: float = MIN_COVERAGE, dry_run: bool = False) -> dict:
    """Re-transcribe one meeting; returns a summary dict whose 'status' is
    'replaced', 'dry_run' or 'low_coverage'. Raises when diarization is
    unavailable or the download fails (nothing is changed)."""
    from councilhound.embeddings.embed import embed_texts

    started = time.monotonic()
    old = session.scalars(
        select(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting.id)).all()
    result = {"meeting_id": meeting.id, "clip_id": meeting.granicus_clip_id,
              "date": meeting.meeting_date.isoformat(), "body": meeting.body,
              "old_chunks": len(old)}

    path = os.path.join(workdir, f"{meeting.granicus_clip_id}.mp3")
    try:
        http.download(meeting.audio_url, path, timeout=600)
        segments = transcribe_audio(path)
        turns = diarize(path)
        if not turns:
            raise RuntimeError(
                "diarization returned no speaker turns (pyannote missing, HF token "
                "expired, or DIARIZE=0); refusing to replace chunks without labels")
        chunks = merge_segments(assign_speakers(segments, turns))
    finally:
        for p in (path, path + ".part"):
            if os.path.exists(p):
                os.remove(p)

    cov = coverage([c.text for c in old], [c["text"] for c in chunks])
    result.update(new_chunks=len(chunks), speakers=len({c["speaker"] for c in chunks}),
                  coverage=round(cov, 3),
                  old_loop_chunks=sum(1 for c in old if _LOOP.search(c.text.lower())),
                  new_loop_chunks=sum(1 for c in chunks if _LOOP.search(c["text"].lower())))
    if cov < min_coverage:
        result["status"] = "low_coverage"
    elif dry_run:
        result["status"] = "dry_run"
    else:
        vectors = embed_texts([c["text"] for c in chunks])
        for row in old:
            session.delete(row)
        # labels change with the chunks: old fingerprints no longer apply
        session.execute(delete(SpeakerVoice).where(SpeakerVoice.meeting_id == meeting.id))
        session.flush()
        session.add_all(
            TranscriptChunk(meeting_id=meeting.id, start_seconds=c["start"],
                            end_seconds=c["end"], text=c["text"],
                            speaker_label=c["speaker"], embedding=vec)
            for c, vec in zip(chunks, vectors))
        session.commit()
        result["status"] = "replaced"
    result["seconds"] = round(time.monotonic() - started)
    _log(result)
    log.info("retranscribe %s", result)
    return result
