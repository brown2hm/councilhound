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
    assert cues[0]["speaker"] == "TURN_0001"  # ...and starts the first turn
    assert all(c["end"] >= c["start"] for c in cues)
    assert is_real_captions(FIX.read_text())


def test_parse_vtt_rejects_placeholders():
    assert parse_vtt("") == [] and parse_vtt("WEBVTT\n\n") == []
    assert parse_vtt("<html>Not Found</html>") == []
    assert not is_real_captions("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n")
    # mm:ss.mmm stamps and positioning tags
    cues = parse_vtt("WEBVTT\n\n1\n00:01.500 --> 00:03.000 line:90%\n<v Chair>Call to <b>order</b>.\n")
    assert cues == [{"start": 1.5, "end": 3.0, "text": "Call to order.", "speaker": None}]


def test_speaker_markers_start_turns_even_mid_cue():
    vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n>> Thank you. Supervisor Lusk.\n\n"
           "00:00:03.000 --> 00:00:05.000\n>> Thank you, Chairman. I move\n\n"
           "00:00:05.000 --> 00:00:07.000\napproval. >> Second.\n\n"
           "00:00:07.000 --> 00:00:08.000\n>> Supervisor Lusk moves.\n")
    cues = parse_vtt(vtt)
    assert [(c["speaker"], c["text"]) for c in cues] == [
        ("TURN_0001", "Thank you. Supervisor Lusk."),
        ("TURN_0002", "Thank you, Chairman. I move"),
        ("TURN_0002", "approval."),
        ("TURN_0003", "Second."),
        ("TURN_0004", "Supervisor Lusk moves."),
    ]
    # the split cue's time is shared in proportion to its text
    approval, second = cues[2], cues[3]
    assert approval["start"] == 5.0 and second["end"] == 7.0
    assert approval["end"] == second["start"] and 5.0 < approval["end"] < 7.0
    # chunks never run across a change of speaker
    chunks = merge_segments(cues)
    assert [c["speaker"] for c in chunks] == ["TURN_0001", "TURN_0002", "TURN_0003", "TURN_0004"]
    assert chunks[1]["text"] == "Thank you, Chairman. I move approval."


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
    # the captioner's turns become the chunks' speaker labels for naming
    assert chunks[0].speaker_label == "TURN_0001"
    assert all(c.speaker_label and c.speaker_label.startswith("TURN_") for c in chunks)
    assert meeting.duration_seconds == int(parse_vtt(FIX.read_text())[-1]["end"])
