import json

import pytest
from sqlalchemy import select

from councilhound.db.models import Meeting, TranscriptChunk
from councilhound.extraction import retranscribe as rt


def test_word_count_ignores_whisper_loops():
    assert rt.word_count("Good evening. " + "okay. " * 30 + "Next item.") == 4
    assert rt.word_count("thank you thank you, members of council") == 7  # short repeats are speech


def test_coverage_compares_cleaned_word_counts():
    old = ["one two three four " + "millions " * 20, "five six seven eight nine ten"]
    assert rt.coverage(old, ["one two three four five six seven eight nine"]) == pytest.approx(0.9)
    assert rt.coverage([], ["anything"]) == 1.0


def _meeting(s, day, clip, labelled=None, audio=True, chunk=True):
    m = Meeting(granicus_view_id="13", granicus_clip_id=clip, body="city_council",
                meeting_type="council_meeting", title="City Council Meeting",
                meeting_date=f"2026-09-{day:02d}",
                audio_url=f"https://archive-video.granicus.com/fairfax/{clip}.mp3" if audio else None)
    s.add(m)
    s.flush()
    if chunk:
        s.add(TranscriptChunk(meeting_id=m.id, start_seconds=0, end_seconds=5,
                              text="good evening and welcome to the meeting", speaker_label=labelled))
    s.commit()
    return m


def test_candidates_newest_first_skipping_done_untranscribed_and_audioless(db_session):
    _meeting(db_session, 1, "a", labelled=None)          # transcribed, unlabelled
    _meeting(db_session, 8, "b", labelled=None)          # newer
    _meeting(db_session, 15, "c", labelled="SPEAKER_00")  # already done
    _meeting(db_session, 20, "d", chunk=False)             # never transcribed
    _meeting(db_session, 22, "e", labelled=None, audio=False)
    assert [m.granicus_clip_id for m in rt.candidates(db_session)] == ["b", "a"]
    assert [m.granicus_clip_id for m in rt.candidates(db_session, limit=1)] == ["b"]


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """Stub the download, whisper, diarization and embedding."""
    monkeypatch.setattr(rt, "LOG_PATH", str(tmp_path / "log.jsonl"))

    def download(url, dest, timeout=0):
        open(dest, "wb").write(b"mp3")
        return dest
    monkeypatch.setattr(rt.http, "download", download)
    segments = [{"start": 0.0, "end": 4.0, "text": "good evening and welcome to the meeting second",
                 "words": [{"start": i * 0.5, "end": i * 0.5 + 0.4, "word": " " + w}
                           for i, w in enumerate("good evening and welcome to the meeting second".split())]}]
    monkeypatch.setattr(rt, "transcribe_audio", lambda path: segments)
    turns = [{"start": 0.0, "end": 3.4, "speaker": "SPEAKER_05"},
             {"start": 3.4, "end": 4.0, "speaker": "SPEAKER_21"}]
    state = {"turns": turns}
    monkeypatch.setattr(rt, "diarize", lambda path: state["turns"])
    import councilhound.embeddings.embed as embed
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[0.0] * 768 for _ in texts])
    return state


def test_retranscribe_replaces_chunks_with_labelled_embedded_ones(db_session, fake_pipeline, tmp_path):
    m = _meeting(db_session, 1, "a", labelled=None)
    r = rt.retranscribe_meeting(db_session, m, str(tmp_path))
    assert r["status"] == "replaced" and r["speakers"] == 2
    rows = db_session.scalars(select(TranscriptChunk).where(TranscriptChunk.meeting_id == m.id)
                              .order_by(TranscriptChunk.start_seconds)).all()
    assert [(c.speaker_label, c.text) for c in rows] == [
        ("SPEAKER_05", "good evening and welcome to the meeting"), ("SPEAKER_21", "second")]
    assert all(c.embedding is not None for c in rows)
    assert not list(tmp_path.glob("*.mp3"))  # audio cleaned up
    assert json.loads(open(rt.LOG_PATH).read().splitlines()[-1])["status"] == "replaced"


def test_retranscribe_keeps_old_chunks_when_coverage_is_low(db_session, fake_pipeline, tmp_path):
    m = _meeting(db_session, 1, "a", labelled=None)
    db_session.add(TranscriptChunk(meeting_id=m.id, start_seconds=5, end_seconds=60,
                                   text=" ".join(f"w{i}" for i in range(200))))
    db_session.commit()
    r = rt.retranscribe_meeting(db_session, m, str(tmp_path))
    assert r["status"] == "low_coverage"
    assert db_session.scalars(select(TranscriptChunk.speaker_label)
                              .where(TranscriptChunk.meeting_id == m.id)).all() == [None, None]


def test_retranscribe_refuses_without_diarization(db_session, fake_pipeline, tmp_path):
    fake_pipeline["turns"] = []
    m = _meeting(db_session, 1, "a", labelled=None)
    with pytest.raises(RuntimeError, match="no speaker turns"):
        rt.retranscribe_meeting(db_session, m, str(tmp_path))
    assert len(db_session.scalars(select(TranscriptChunk)).all()) == 1
    assert not list(tmp_path.glob("*.mp3"))


def test_dry_run_changes_nothing(db_session, fake_pipeline, tmp_path):
    m = _meeting(db_session, 1, "a", labelled=None)
    r = rt.retranscribe_meeting(db_session, m, str(tmp_path), dry_run=True)
    assert r["status"] == "dry_run"
    assert db_session.scalars(select(TranscriptChunk.speaker_label)).all() == [None]
