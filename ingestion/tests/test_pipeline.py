"""Pipeline ingest behavior. The key guarantee: a just-happened meeting whose
audio isn't downloadable yet must still reach 'fetched' so it can be
structured from its agenda/minutes — audio is best-effort, not a gate."""
import datetime

from councilhound import pipeline
from councilhound.db.models import Meeting


def _discovered(session, clip="900", day=14):
    m = Meeting(granicus_clip_id=clip, granicus_view_id="13", body="city_council",
                meeting_type="council_meeting", meeting_date=datetime.date(2026, 7, day),
                title="City Council Meeting", status="discovered")
    session.add(m)
    session.flush()
    return m


def test_media_failure_still_reaches_fetched(db_session, monkeypatch):
    s = db_session
    m = _discovered(s)
    monkeypatch.setattr(pipeline, "discover", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "fetch_documents", lambda session, meeting: 1)

    def audio_not_posted(session, meeting):
        raise RuntimeError("audio not downloadable yet")

    monkeypatch.setattr(pipeline, "fetch_media", audio_not_posted)

    run = pipeline.run_ingest(s, "13", since=datetime.date(2026, 7, 1))
    s.refresh(m)
    assert m.status == "fetched"  # not blocked by the audio failure
    assert run.meetings_processed == 1
    assert any("media" in e["error"] for e in run.errors)


def test_skip_media_never_fetches_audio(db_session, monkeypatch):
    s = db_session
    m = _discovered(s)
    monkeypatch.setattr(pipeline, "discover", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "fetch_documents", lambda session, meeting: 1)
    called = {"media": False}

    def spy(session, meeting):
        called["media"] = True

    monkeypatch.setattr(pipeline, "fetch_media", spy)

    pipeline.run_ingest(s, "13", since=datetime.date(2026, 7, 1), skip_media=True)
    s.refresh(m)
    assert m.status == "fetched"
    assert called["media"] is False  # the hourly catchup path skips audio
