"""Pure text-processing helpers: transcript chunk merging and PDF text
sanitization (the NUL-byte crash class that hit production extraction once)."""
from councilhound.extraction.pdf_text import _sanitize
from councilhound.extraction.transcript import merge_segments


def test_merge_segments_respects_target_and_timestamps():
    segments = [
        {"start": 0, "end": 10, "text": "a" * 400},
        {"start": 10, "end": 20, "text": "b" * 400},  # crosses 700 -> chunk closes
        {"start": 20, "end": 30, "text": "tail"},
    ]
    chunks = merge_segments(segments, target_chars=700)
    assert len(chunks) == 2
    assert chunks[0]["start"] == 0 and chunks[0]["end"] == 20
    assert chunks[1]["text"] == "tail" and chunks[1]["start"] == 20


def test_merge_segments_empty():
    assert merge_segments([]) == []


def test_sanitize_strips_nul_and_control_chars():
    assert "\x00" not in _sanitize("hello\x00world")
    assert _sanitize("line\x01noise\x1f here") == "linenoise here"
    assert _sanitize("keep\nnewlines\tand tabs") == "keep\nnewlines\tand tabs"


def test_sanitize_rejects_encoding_garbage():
    # mostly control characters -> scanned/broken PDF -> empty (OCR bucket)
    garbage = "\x01\x02\x03\x04" * 200 + "ok"
    assert _sanitize(garbage) == ""
    assert _sanitize("") == ""
