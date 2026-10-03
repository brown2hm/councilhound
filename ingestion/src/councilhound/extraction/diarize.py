"""
Speaker diarization: who spoke when, as anonymous per-meeting labels.

Runs pyannote's community-1 pipeline (Apple Silicon GPU via MPS when
available, CPU otherwise) and returns non-overlapping turns. transcript.py
assigns each whisper word to the turn it overlaps most, so chunks break at
speaker changes and carry speaker_label ('SPEAKER_05'). Labels are only
consistent within one meeting; putting names to them is a separate step.

On by default. Set DIARIZE=0 to skip. The model is gated on Hugging Face:
the machine needs a token (`hf auth login`) from an account that has
accepted the terms at huggingface.co/pyannote/speaker-diarization-community-1.
pyannote is a local-run dependency (requirements-diarize.txt), never in the
Fly images; when it or the token is missing, diarize() logs a warning and
returns [], and transcription carries on without labels.

Tested 2026-09-26 on the Sep 22 2026 Council meeting (4 h): 33 speakers,
~11 min on an M-series GPU. Each public commenter got their own label;
one-word roll-call answers ("aye") still fold into the roll-caller's turn.
"""
import logging
import os

log = logging.getLogger(__name__)

DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
SAMPLE_RATE = 16000

_pipeline = None


def enabled() -> bool:
    return os.environ.get("DIARIZE", "1").strip().lower() not in ("0", "false", "no", "off")


def _load_pipeline():
    global _pipeline
    if _pipeline is None:
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(os.environ.get("DIARIZATION_MODEL", DIARIZATION_MODEL))
        if pipeline is None:  # older pyannote returns None when the repo is gated
            raise RuntimeError(f"could not load {DIARIZATION_MODEL} (gated; check the HF token)")
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        pipeline.to(torch.device(device))
        log.info("diarization pipeline loaded on %s", device)
        _pipeline = pipeline
    return _pipeline


def diarize(audio_path: str) -> list[dict]:
    """[{'start', 'end', 'speaker'}] sorted by start, non-overlapping, with
    speaker labels like 'SPEAKER_05'. [] when disabled or unavailable."""
    if not enabled():
        return []
    try:
        pipeline = _load_pipeline()
    except Exception as exc:  # ImportError, gated repo, no token, ...
        log.warning("diarization unavailable, transcribing without speaker labels: %s", exc)
        return []

    import torch
    # same decoder transcript.py uses (no ffmpeg binary needed)
    from faster_whisper.audio import decode_audio

    audio = decode_audio(audio_path, sampling_rate=SAMPLE_RATE)
    output = pipeline({"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SAMPLE_RATE})
    # pyannote 4 returns both views; the exclusive one has no overlapping
    # speech, which is what word assignment wants
    annotation = getattr(output, "exclusive_speaker_diarization", output)
    turns = [
        {"start": float(seg.start), "end": float(seg.end), "speaker": str(label)}
        for seg, _track, label in annotation.itertracks(yield_label=True)
    ]
    turns.sort(key=lambda t: t["start"])
    log.info("diarized %s: %d turns, %d speakers", audio_path, len(turns),
             len({t["speaker"] for t in turns}))
    return turns
