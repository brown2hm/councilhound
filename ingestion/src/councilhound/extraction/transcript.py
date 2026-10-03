"""
Phase 2: transcription of meeting audio into transcript_chunks.

No captions exist on any Fairfax Granicus clip (verified 2026-07-11), so the
MP3 downloaded by fetch_media is transcribed locally. Two backends, chosen
automatically:

  1. mlx-whisper  — Apple Silicon GPU (Metal); ~5-10x faster than CPU.
  2. faster-whisper — CPU (ctranslate2); works everywhere incl. the Docker
     image, and is the fallback when mlx isn't importable.

Whisper emits ~2-10s segments with word timestamps. diarize.py works out
who spoke when; each word goes to the speaker turn it overlaps most, and the
words are merged into ~TARGET_CHUNK_CHARS chunks (keeping start/end
timestamps) that also break at every speaker change, so a chunk is one
speaker's words and carries their speaker_label. Without diarization
(DIARIZE=0, or pyannote unavailable) chunks are unlabelled, as before.

Word timestamps also enable whisper's hallucination_silence_threshold, and
condition_on_previous_text is off: together they stop the looping "She She
She..." / "Thank you. Thank you..." output over music and silence.

Resumable by construction: a meeting is only marked transcribed after all its
chunks are committed in one transaction, and meetings with existing chunks
are skipped.
"""
import bisect
import logging
import os
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import Meeting, TranscriptChunk
from councilhound.extraction.diarize import diarize

log = logging.getLogger(__name__)

# whisper large-v3-turbo: near-large accuracy at ~4x large speed; both
# backends have it. Override with WHISPER_MODEL env var.
DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
DEFAULT_FW_MODEL = "large-v3-turbo"
TARGET_CHUNK_CHARS = 700
# skip-ahead window for silence that whisper would otherwise fill with
# invented text; needs word timestamps
HALLUCINATION_SILENCE_SECONDS = 2.0


def _pick_backend() -> str:
    if os.environ.get("TRANSCRIBE_BACKEND"):
        return os.environ["TRANSCRIBE_BACKEND"]
    try:
        import mlx_whisper  # noqa: F401
        return "mlx"
    except ImportError:
        return "faster-whisper"


def _transcribe_mlx(audio_path: str) -> list[dict]:
    import mlx_whisper
    # mlx-whisper shells out to an ffmpeg binary for file input, which this
    # machine doesn't have — decode via PyAV (bundled with faster-whisper)
    # and hand mlx a 16 kHz float32 array instead.
    from faster_whisper.audio import decode_audio

    audio = decode_audio(audio_path, sampling_rate=16000)
    model = os.environ.get("WHISPER_MODEL", DEFAULT_MLX_MODEL)
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=model, language="en", word_timestamps=True,
        condition_on_previous_text=False,
        hallucination_silence_threshold=HALLUCINATION_SILENCE_SECONDS,
    )
    return [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip(),
         "words": [{"start": w["start"], "end": w["end"], "word": w["word"]}
                   for w in s.get("words", [])]}
        for s in result["segments"]
        if s["text"].strip()
    ]


def _transcribe_faster_whisper(audio_path: str) -> list[dict]:
    from faster_whisper import WhisperModel

    model_name = os.environ.get("WHISPER_MODEL", DEFAULT_FW_MODEL)
    model = WhisperModel(model_name, compute_type="int8")
    segments, _info = model.transcribe(
        audio_path, language="en", vad_filter=True, word_timestamps=True,
        condition_on_previous_text=False,
        hallucination_silence_threshold=HALLUCINATION_SILENCE_SECONDS,
    )
    return [
        {"start": s.start, "end": s.end, "text": s.text.strip(),
         "words": [{"start": w.start, "end": w.end, "word": w.word} for w in (s.words or [])]}
        for s in segments
        if s.text.strip()
    ]


def transcribe_audio(audio_path: str) -> list[dict]:
    """Run whisper on an audio file -> [{'start','end','text','words'}, ...]."""
    backend = _pick_backend()
    log.info("transcribing %s with backend=%s", audio_path, backend)
    if backend == "mlx":
        return _transcribe_mlx(audio_path)
    return _transcribe_faster_whisper(audio_path)


def _speaker_at(turns: list[dict], starts: list[float], start: float, end: float) -> str | None:
    """The turn overlapping [start, end] the most; for a word in a gap
    between turns, the nearest turn."""
    i = max(0, bisect.bisect_right(starts, start) - 1)
    best, best_overlap = None, 0.0
    while i < len(turns) and turns[i]["start"] < end:
        overlap = min(end, turns[i]["end"]) - max(start, turns[i]["start"])
        if overlap > best_overlap:
            best, best_overlap = turns[i]["speaker"], overlap
        i += 1
    if best is not None:
        return best
    i = bisect.bisect_right(starts, start)
    nearby = [turns[j] for j in (i - 1, i) if 0 <= j < len(turns)]
    if not nearby:
        return None
    return min(nearby, key=lambda t: min(abs(t["start"] - start), abs(t["end"] - start)))["speaker"]


def assign_speakers(segments: list[dict], turns: list[dict]) -> list[dict]:
    """Split whisper segments into same-speaker pieces using diarization
    turns: each word goes to the turn it overlaps most. Segments without
    word timestamps are assigned whole. With no turns the segments come
    back unchanged (speaker None)."""
    if not turns:
        return [{**seg, "speaker": None} for seg in segments]
    starts = [t["start"] for t in turns]
    pieces: list[dict] = []
    for seg in segments:
        words = seg.get("words") or [{"start": seg["start"], "end": seg["end"], "word": seg["text"]}]
        current: dict | None = None
        for w in words:
            speaker = _speaker_at(turns, starts, w["start"], w["end"])
            if current and current["speaker"] == speaker:
                current["end"] = w["end"]
                current["text"] += w["word"]
            else:
                if current:
                    pieces.append(current)
                current = {"start": w["start"], "end": w["end"], "text": w["word"], "speaker": speaker}
        if current:
            pieces.append(current)
    for p in pieces:
        p["text"] = " ".join(p["text"].split())
    return [p for p in pieces if p["text"]]


def merge_segments(segments: list[dict], target_chars: int = TARGET_CHUNK_CHARS) -> list[dict]:
    """Merge whisper's small segments into retrieval-sized chunks, keeping
    the covered time span. A change of speaker always starts a new chunk."""
    chunks: list[dict] = []
    current: dict | None = None
    for seg in segments:
        speaker = seg.get("speaker")
        if current is not None and current["speaker"] != speaker:
            chunks.append(current)
            current = None
        if current is None:
            current = {"start": seg["start"], "end": seg["end"], "text": seg["text"],
                       "speaker": speaker}
        else:
            current["text"] += " " + seg["text"]
            current["end"] = seg["end"]
        if len(current["text"]) >= target_chars:
            chunks.append(current)
            current = None
    if current:
        chunks.append(current)
    return chunks


def transcribe_meeting(session: Session, meeting: Meeting, force: bool = False) -> int:
    """Transcribe one meeting's audio into transcript_chunks. Skips meetings
    that already have chunks unless force=True. Returns chunk count."""
    existing = session.scalar(
        select(func.count(TranscriptChunk.id)).where(TranscriptChunk.meeting_id == meeting.id)
    )
    if existing and not force:
        log.info("meeting %s already has %d chunks, skipping", meeting.id, existing)
        return existing
    if not meeting.audio_local_path or not os.path.exists(meeting.audio_local_path):
        raise FileNotFoundError(
            f"meeting {meeting.id} (clip {meeting.granicus_clip_id}) has no local audio - "
            "run `ingest` without --skip-media first"
        )

    started = time.monotonic()
    segments = transcribe_audio(meeting.audio_local_path)
    turns = diarize(meeting.audio_local_path)
    chunks = merge_segments(assign_speakers(segments, turns))

    if force and existing:
        for row in session.scalars(
            select(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting.id)
        ):
            session.delete(row)
    for c in chunks:
        session.add(
            TranscriptChunk(
                meeting_id=meeting.id,
                start_seconds=c["start"],
                end_seconds=c["end"],
                text=c["text"],
                speaker_label=c["speaker"],
            )
        )
    session.commit()
    elapsed = time.monotonic() - started
    log.info(
        "meeting %s (clip %s): %d chunks from %d segments, %d speakers in %.0fs (%.1fx realtime)",
        meeting.id, meeting.granicus_clip_id, len(chunks), len(segments),
        len({t["speaker"] for t in turns}), elapsed,
        (meeting.duration_seconds or 0) / elapsed if elapsed else 0,
    )
    return len(chunks)


def transcribe_pending(session: Session, limit: int | None = None) -> dict:
    """Transcribe every meeting that has audio on disk but no chunks yet,
    shortest first (fast feedback, cheap failures)."""
    sub = select(TranscriptChunk.meeting_id).distinct()
    q = (
        select(Meeting)
        .where(
            Meeting.audio_local_path.isnot(None),
            Meeting.id.not_in(sub),
            # canceled meetings have placeholder clips (title card + music)
            # that whisper hallucinates on
            ~Meeting.title.ilike("%cancel%"),
        )
        .order_by(Meeting.duration_seconds.asc().nulls_last())
    )
    if limit:
        q = q.limit(limit)
    meetings = session.scalars(q).all()

    done = failed = missing = 0
    for meeting in meetings:
        # audio may live on another machine (e.g. backfill done locally,
        # daily job in the cloud) — skip quietly rather than erroring
        if not os.path.exists(meeting.audio_local_path):
            missing += 1
            continue
        try:
            transcribe_meeting(session, meeting)
            done += 1
        except Exception:
            session.rollback()
            log.exception("transcription failed for meeting %s", meeting.id)
            failed += 1
    return {"transcribed": done, "failed": failed, "audio_elsewhere": missing,
            "candidates": len(meetings)}
