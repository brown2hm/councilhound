"""WebVTT captions as a transcript source (the County publishes real ones)."""
from pathlib import Path

from councilhound.db.models import Meeting, TranscriptChunk
from councilhound.extraction.captions import is_real_captions, parse_vtt
from councilhound.extraction.transcript import merge_segments, transcribe_meeting

FIX = Path(__file__).parent / "fixtures" / "granicus" / "fairfax_county_va" / "captions_4241_head.vtt"


def test_parse_vtt_cues_and_speaker_markers():
    cues = parse_vtt(FIX.read_text())
    assert len(cues) == 60
    assert cues[0]["start"] == 4.87 and cues[0]["end"] == 5.95
    assert cues[0]["text"] == "Good morning, everyone."  # '>>' speaker marker dropped
    assert all(c["end"] >= c["start"] for c in cues)
    assert is_real_captions(FIX.read_text())


def test_parse_vtt_rejects_placeholders():
    assert parse_vtt("") == [] and parse_vtt("WEBVTT\n\n") == []
    assert parse_vtt("<html>Not Found</html>") == []
    assert not is_real_captions("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n")
    # mm:ss.mmm stamps and positioning tags
    cues = parse_vtt("WEBVTT\n\n1\n00:01.500 --> 00:03.000 line:90%\n<v Chair>Call to <b>order</b>.\n")
    assert cues == [{"start": 1.5, "end": 3.0, "text": "Call to order."}]


def test_merge_segments_builds_chunks_from_cues():
    chunks = merge_segments(parse_vtt(FIX.read_text()), target_chars=200)
    assert len(chunks) > 1
    assert chunks[0]["start"] == 4.87 and chunks[-1]["end"] > chunks[0]["end"]
    assert all(len(c["text"]) >= 200 for c in chunks[:-1])


def test_transcribe_meeting_reads_vtt_and_fills_duration(db_session):
    meeting = Meeting(granicus_clip_id="4241", granicus_view_id="7", body="board_of_supervisors",
                      meeting_type="bos_meeting", meeting_date="2026-09-15",
                      title="Board", audio_local_path=str(FIX), duration_seconds=None)
    db_session.add(meeting)
    db_session.commit()
    n = transcribe_meeting(db_session, meeting)
    assert n >= 1
    chunks = db_session.query(TranscriptChunk).filter_by(meeting_id=meeting.id).all()
    assert len(chunks) == n and chunks[0].text.startswith("Good morning")
    assert meeting.duration_seconds == int(parse_vtt(FIX.read_text())[-1]["end"])
