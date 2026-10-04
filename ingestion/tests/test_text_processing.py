"""Pure text-processing helpers: transcript chunk merging and PDF text
sanitization (the NUL-byte crash class that hit production extraction once)."""
from councilhound.extraction.pdf_text import _sanitize
from councilhound.extraction.transcript import assign_speakers, merge_segments


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


def _w(start, end, word):
    return {"start": start, "end": end, "word": word}


def test_assign_speakers_splits_a_segment_at_the_speaker_change():
    # "...a roll call vote. Second." spoken by two people inside one segment
    segments = [{"start": 0.0, "end": 3.0, "text": "a roll call vote second",
                 "words": [_w(0.0, 0.4, " a"), _w(0.4, 0.8, " roll"), _w(0.8, 1.2, " call"),
                           _w(1.2, 1.8, " vote"), _w(2.2, 2.9, " second")]}]
    turns = [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_05"},
             {"start": 2.1, "end": 3.0, "speaker": "SPEAKER_21"}]
    pieces = assign_speakers(segments, turns)
    assert [(p["speaker"], p["text"]) for p in pieces] == [
        ("SPEAKER_05", "a roll call vote"), ("SPEAKER_21", "second")]
    assert pieces[1]["start"] == 2.2 and pieces[1]["end"] == 2.9


def test_assign_speakers_gap_word_goes_to_nearest_turn():
    segments = [{"start": 5.0, "end": 5.3, "text": "aye", "words": [_w(5.0, 5.3, " aye")]}]
    turns = [{"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"},
             {"start": 5.5, "end": 9.0, "speaker": "SPEAKER_01"}]
    assert assign_speakers(segments, turns)[0]["speaker"] == "SPEAKER_01"


def test_assign_speakers_without_turns_keeps_segments_unlabelled():
    segments = [{"start": 0, "end": 1, "text": "hello"}]
    assert assign_speakers(segments, []) == [{"start": 0, "end": 1, "text": "hello", "speaker": None}]


def test_merge_segments_breaks_chunks_at_speaker_changes():
    pieces = [
        {"start": 0, "end": 2, "text": "is there a second", "speaker": "SPEAKER_05"},
        {"start": 2, "end": 3, "text": "second", "speaker": "SPEAKER_21"},
        {"start": 3, "end": 6, "text": "the motion has been made", "speaker": "SPEAKER_05"},
        {"start": 6, "end": 8, "text": "and seconded", "speaker": "SPEAKER_05"},
    ]
    chunks = merge_segments(pieces, target_chars=700)
    assert [(c["speaker"], c["text"]) for c in chunks] == [
        ("SPEAKER_05", "is there a second"),
        ("SPEAKER_21", "second"),
        ("SPEAKER_05", "the motion has been made and seconded"),
    ]
    assert chunks[2]["start"] == 3 and chunks[2]["end"] == 8


def test_sanitize_strips_nul_and_control_chars():
    assert "\x00" not in _sanitize("hello\x00world")
    assert _sanitize("line\x01noise\x1f here") == "linenoise here"
    assert _sanitize("keep\nnewlines\tand tabs") == "keep\nnewlines\tand tabs"


def test_sanitize_rejects_encoding_garbage():
    # mostly control characters -> scanned/broken PDF -> empty (OCR bucket)
    garbage = "\x01\x02\x03\x04" * 200 + "ok"
    assert _sanitize(garbage) == ""
    assert _sanitize("") == ""


def _write_docx(path, paragraphs):
    """Minimal .docx: the zip layout Granicus's DocumentViewer serves."""
    import zipfile
    body = "".join(
        "<w:p>" + "".join(
            f"<w:r><w:t>{run}</w:t></w:r>" if run != "\t" else "<w:r><w:tab/></w:r>"
            for run in runs) + "</w:p>"
        for runs in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)


def test_docx_to_text_joins_runs_and_keeps_paragraphs(tmp_path):
    from councilhound.extraction.pdf_text import docx_to_text
    p = tmp_path / "agenda.docx"
    _write_docx(p, [["School Board ", "Closed", " Meeting Agenda"],
                    ["1.", "\t", "Call to order"],
                    [""],
                    ["2.", "\t", "Adjourn"]])
    assert docx_to_text(str(p)) == (
        "School Board Closed Meeting Agenda\n1.\tCall to order\n2.\tAdjourn")


def test_extract_document_dispatches_docx(tmp_path):
    from councilhound.db.models import Document
    from councilhound.extraction.pdf_text import extract_document
    p = tmp_path / "agenda.docx"
    _write_docx(p, [["Roll call"]])
    assert extract_document(Document(local_path=str(p))) == "Roll call"
    assert extract_document(Document(local_path=str(tmp_path / "x.bin"))) is None


def test_ext_for_sniffs_word_agendas():
    from councilhound.pipeline import _ext_for
    zip_head = b"PK\x03\x04" + b"\x00" * 26 + b"[Content_Types].xml"
    # Granicus labels .docx payloads as legacy Word
    assert _ext_for("application/msword", zip_head) == ".docx"
    assert _ext_for("application/vnd.openxmlformats-officedocument.wordprocessingml.document") == ".docx"
    # a vague header falls back to the bytes
    assert _ext_for("application/octet-stream", zip_head) == ".docx"
    assert _ext_for("application/octet-stream", b"%PDF-1.7 ...") == ".pdf"
    assert _ext_for("", b"<!DOCTYPE html><html>") == ".html"
    assert _ext_for("application/pdf") == ".pdf"
    assert _ext_for("text/html; charset=utf-8") == ".html"
    assert _ext_for("application/octet-stream", b"\x00\x01garbage") == ".bin"
