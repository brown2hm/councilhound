"""
Phase 2: transcript acquisition.

Two paths, in priority order:
  1. Parse an existing caption/VTT track if fetch_captions_or_video obtained one.
  2. Transcribe downloaded audio/video with faster-whisper as a fallback.

Output shape either way: list of {start_seconds, end_seconds, text} dicts,
ready to load into transcript_chunks.
"""


def parse_vtt(path: str) -> list[dict]:
    """Parse a WebVTT caption file into timestamped chunks."""
    raise NotImplementedError("Phase 2 task")


def transcribe_with_whisper(audio_path: str, model_size: str = "medium") -> list[dict]:
    """Transcribe audio/video with faster-whisper, chunked with timestamps."""
    raise NotImplementedError("Phase 2 task - only needed if captions unavailable")
