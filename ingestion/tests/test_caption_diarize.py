"""Captions without speaker marks (the County's Planning Commission) take
their speakers from the meeting audio: the audio track is fetched next to
the captions and diarized, and its labels go on the caption text."""
import pytest
from pydantic import ValidationError

from councilhound import pipeline
from councilhound.db.models import Meeting, TranscriptChunk
from councilhound.extraction import transcript
from councilhound.jurisdiction import JurisdictionConfig

UNMARKED = ("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nGood evening. Welcome to the Planning Commission.\n\n"
            "00:00:04.000 --> 00:00:08.000\nCommissioner Sargeant, the floor is yours.\n\n"
            "00:00:08.000 --> 00:00:12.000\nThank you, Madam Chair. I move approval.\n")
MARKED = UNMARKED.replace("Good evening.", ">> Good evening.")


def _caption_meeting(db_session, tmp_path, vtt, audio=True, body="planning_commission"):
    d = tmp_path / "4245"
    d.mkdir()
    (d / "captions.vtt").write_text(vtt)
    if audio:
        (d / "audio.m4a").write_bytes(b"\x00" * 16)
    m = Meeting(granicus_clip_id="4245", granicus_view_id="10", body=body,
                meeting_type="planning_commission", meeting_date="2026-09-16", title="Commission",
                audio_local_path=str(d / "captions.vtt"), video_url="https://example/clip.mp4")
    db_session.add(m)
    db_session.commit()
    return m


@pytest.fixture
def fake_voice(monkeypatch):
    calls = {"diarize": [], "fingerprint": []}

    def diarize(path):
        calls["diarize"].append(path)
        return [{"start": 0.0, "end": 7.9, "speaker": "SPEAKER_00"},
                {"start": 7.9, "end": 12.0, "speaker": "SPEAKER_03"}]

    monkeypatch.setattr(transcript, "diarize", diarize)
    from councilhound.extraction import voices
    monkeypatch.setattr(voices, "fingerprint_meeting",
                        lambda session, meeting, path: calls["fingerprint"].append(path))
    return calls


def test_unmarked_captions_take_speakers_from_the_audio(db_session, tmp_path, fake_voice):
    m = _caption_meeting(db_session, tmp_path, UNMARKED)
    transcript.transcribe_meeting(db_session, m)
    audio = str(tmp_path / "4245" / "audio.m4a")
    assert fake_voice["diarize"] == [audio] and fake_voice["fingerprint"] == [audio]
    chunks = db_session.query(TranscriptChunk).filter_by(meeting_id=m.id).order_by(TranscriptChunk.start_seconds).all()
    # the caption text is kept; the voices supply the labels
    assert [(c.speaker_label, c.text) for c in chunks] == [
        ("SPEAKER_00", "Good evening. Welcome to the Planning Commission. Commissioner Sargeant, the floor is yours."),
        ("SPEAKER_03", "Thank you, Madam Chair. I move approval."),
    ]


def test_marked_captions_keep_the_captioners_turns(db_session, tmp_path, fake_voice):
    m = _caption_meeting(db_session, tmp_path, MARKED)
    transcript.transcribe_meeting(db_session, m)
    assert fake_voice["diarize"] == []
    labels = {c.speaker_label for c in db_session.query(TranscriptChunk).filter_by(meeting_id=m.id)}
    assert labels == {"TURN_0001"}


def test_unmarked_captions_without_audio_stay_unlabelled(db_session, tmp_path, fake_voice):
    m = _caption_meeting(db_session, tmp_path, UNMARKED, audio=False)
    transcript.transcribe_meeting(db_session, m)
    assert fake_voice["diarize"] == [] and fake_voice["fingerprint"] == []
    assert {c.speaker_label for c in db_session.query(TranscriptChunk).filter_by(meeting_id=m.id)} == {None}


def test_caption_audio_is_fetched_only_where_it_is_needed(db_session, tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(pipeline, "_mp4_audio", lambda m: fetched.append(m.granicus_clip_id) or "audio")
    monkeypatch.setattr(pipeline.JURISDICTION.granicus.media, "caption_diarize_bodies", ["planning_commission"])
    m = _caption_meeting(db_session, tmp_path, UNMARKED, audio=False)
    assert pipeline.fetch_caption_audio(m) == "audio" and fetched == ["4245"]

    m.body = "board_of_supervisors"  # not configured: captions alone
    assert pipeline.fetch_caption_audio(m) is None
    m.body = "planning_commission"
    (tmp_path / "4245" / "captions.vtt").write_text(MARKED)  # the captioner marked speakers
    assert pipeline.fetch_caption_audio(m) is None
    assert fetched == ["4245"]


def test_caption_diarize_bodies_must_be_bodies():
    cfg = JurisdictionConfig.load("fairfax_county_va")
    assert cfg.granicus.media.caption_diarize_bodies == ["planning_commission"]
    data = cfg.model_dump()
    data["granicus"]["media"]["caption_diarize_bodies"] = ["zoning_board"]
    with pytest.raises(ValidationError, match="unknown body 'zoning_board'"):
        JurisdictionConfig.model_validate(data)
