"""
Voice fingerprints: one 256-d vector per diarization label, per meeting.

The same speaker-embedding model pyannote's diarization pipeline uses
(diarize._load_pipeline()._embedding) is run on up to VOICE_WINDOWS
windows of VOICE_WINDOW seconds, each centred in one of the label's longest
chunks; the L2-normalized window vectors are averaged. This is exactly the
method the Oct 2026 pilot measured (voice_match.py has the thresholds), so
changing it means re-running that evaluation.

New meetings are fingerprinted at the end of `transcribe`, while the audio
is on disk. Older meetings are backfilled by `fingerprint-voices`, which
fetches the MP3 to a scratch dir (residential IP only, like retranscribe)
and deletes it afterwards. Fingerprints are replaced whenever a meeting's
chunks are, since labels change with them.
"""
import logging
import os
import tempfile

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from councilhound import http
from councilhound.db.models import Meeting, SpeakerVoice, TranscriptChunk

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
VOICE_WINDOW = 10.0  # seconds per window
VOICE_WINDOWS = 6  # windows per label (~1 minute of speech at most)
MIN_SPAN = 2.0  # chunks shorter than this are too short to fingerprint


def _windows(audio, spans: list[tuple[float, float]]) -> list:
    """Up to VOICE_WINDOWS slices of audio, one centred in each of the
    longest spans."""
    out = []
    for a, b in sorted(spans, key=lambda s: s[1] - s[0], reverse=True):
        if b - a < MIN_SPAN:
            break
        mid = (a + b) / 2
        s0 = max(a, mid - VOICE_WINDOW / 2)
        s1 = min(b, s0 + VOICE_WINDOW)
        out.append(audio[int(s0 * SAMPLE_RATE):int(s1 * SAMPLE_RATE)])
        if len(out) >= VOICE_WINDOWS:
            break
    return out


def compute_voices(audio, spans_by_label: dict[str, list[tuple[float, float]]],
                   embed) -> dict[str, tuple[list[float], float]]:
    """label -> (normalized mean embedding, seconds of speech used).
    `embed` maps a (batch, 1, samples) float tensor to an (n, 256) array."""
    import numpy as np
    import torch

    out = {}
    for label, spans in spans_by_label.items():
        wins = _windows(audio, spans)
        if not wins:
            continue
        width = max(len(w) for w in wins)
        batch = torch.from_numpy(np.stack([np.pad(w, (0, width - len(w))) for w in wins])).unsqueeze(1).float()
        vecs = np.asarray(embed(batch))
        vecs = vecs[~np.isnan(vecs).any(axis=1)]
        if not len(vecs):
            continue
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        mean = vecs.mean(0)
        out[label] = ((mean / np.linalg.norm(mean)).tolist(), sum(len(w) for w in wins) / SAMPLE_RATE)
    return out


def _embedder():
    import torch

    from councilhound.extraction.diarize import _load_pipeline

    model = _load_pipeline()._embedding
    model.to(torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu"))
    return model


def fingerprint_meeting(session: Session, meeting: Meeting, audio_path: str) -> int:
    """Replace this meeting's fingerprints from its audio. Returns labels done."""
    from faster_whisper.audio import decode_audio

    spans: dict[str, list[tuple[float, float]]] = {}
    for a, b, label in session.execute(
            select(TranscriptChunk.start_seconds, TranscriptChunk.end_seconds, TranscriptChunk.speaker_label)
            .where(TranscriptChunk.meeting_id == meeting.id, TranscriptChunk.speaker_label.isnot(None))):
        if a is not None and b is not None:
            spans.setdefault(label, []).append((float(a), float(b)))
    if not spans:
        return 0
    audio = decode_audio(audio_path, sampling_rate=SAMPLE_RATE)
    voices = compute_voices(audio, spans, _embedder())
    session.execute(delete(SpeakerVoice).where(SpeakerVoice.meeting_id == meeting.id))
    session.add_all(SpeakerVoice(meeting_id=meeting.id, speaker_label=label, embedding=vec,
                                 speech_seconds=round(sec, 1))
                    for label, (vec, sec) in voices.items())
    session.commit()
    log.info("fingerprinted meeting %s: %d labels", meeting.id, len(voices))
    return len(voices)


def pending(session: Session, bodies=(), limit: int | None = None) -> list[Meeting]:
    """Labelled meetings without fingerprints, newest first."""
    labelled = exists().where(TranscriptChunk.meeting_id == Meeting.id,
                              TranscriptChunk.speaker_label.isnot(None))
    done = exists().where(SpeakerVoice.meeting_id == Meeting.id)
    q = select(Meeting).where(labelled, ~done, Meeting.audio_url.isnot(None))
    if bodies:
        q = q.where(Meeting.body.in_(bodies))
    q = q.order_by(Meeting.meeting_date.desc(), Meeting.id.desc())
    if limit:
        q = q.limit(limit)
    return list(session.scalars(q))


def fingerprint_pending(session: Session, bodies=(), limit: int | None = None) -> dict:
    """Backfill: fingerprint meetings that have none, using local audio when
    it's on disk and a temporary download otherwise."""
    done = failed = 0
    with tempfile.TemporaryDirectory(prefix="voices-") as workdir:
        for meeting in pending(session, bodies=bodies, limit=limit):
            local = meeting.audio_local_path if (meeting.audio_local_path
                                                 and os.path.exists(meeting.audio_local_path)) else None
            path = local or os.path.join(workdir, f"{meeting.granicus_clip_id}.mp3")
            try:
                if not local:
                    http.download(meeting.audio_url, path, timeout=600)
                fingerprint_meeting(session, meeting, path)
                done += 1
            except Exception:
                session.rollback()
                log.exception("fingerprinting failed for meeting %s", meeting.id)
                failed += 1
            finally:
                if not local:
                    for p in (path, path + ".part"):
                        if os.path.exists(p):
                            os.remove(p)
    return {"fingerprinted": done, "failed": failed}
