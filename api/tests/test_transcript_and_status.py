"""The transcript reading view and the public freshness surface."""
import datetime

from councilhound.db.models import (
    AgendaItem, Entity, IngestRun, Meeting, TranscriptChunk, UpcomingMeeting,
)


def _meeting(db, **kw):
    m = Meeting(granicus_clip_id="200", granicus_view_id="13", body="city_council",
                meeting_type="council_regular", meeting_date=datetime.date(2025, 3, 4),
                title="City Council Regular Meeting", status="extracted",
                video_url="https://example.invalid/clip", **kw)
    db.add(m)
    db.flush()
    return m


def test_transcript_orders_segments_and_deep_links(client, db):
    m = _meeting(db)
    # inserted out of order on purpose — the endpoint must sort by timestamp
    db.add_all([
        TranscriptChunk(meeting_id=m.id, start_seconds=300, end_seconds=330, text="Later."),
        TranscriptChunk(meeting_id=m.id, start_seconds=60, end_seconds=90, text="Earlier."),
    ])
    db.commit()

    body = client.get(f"/meetings/{m.id}/transcript").json()
    assert [s["text"] for s in body["segments"]] == ["Earlier.", "Later."]

    first = body["segments"][0]
    assert first["start_seconds"] == 60
    # both seek params, so the link works on either Granicus player generation
    assert "starttime=60" in first["watch_url"]
    assert "entrytime=60" in first["watch_url"]


def test_transcript_returns_agenda_index_points(client, db):
    m = _meeting(db)
    db.add_all([
        AgendaItem(meeting_id=m.id, label="7a", title="Trail contract", start_seconds=400),
        # no index point — can't anchor a section, so it must be left out
        AgendaItem(meeting_id=m.id, label="8b", title="Unindexed item"),
    ])
    db.add(TranscriptChunk(meeting_id=m.id, start_seconds=410, text="On the trail contract."))
    db.commit()

    body = client.get(f"/meetings/{m.id}/transcript").json()
    assert [i["label"] for i in body["agenda_items"]] == ["7a"]
    assert body["agenda_items"][0]["start_seconds"] == 400


def test_transcript_untranscribed_meeting_is_empty_not_404(client, db):
    m = _meeting(db)
    db.commit()
    body = client.get(f"/meetings/{m.id}/transcript").json()
    assert body["segments"] == []
    assert body["title"] == "City Council Regular Meeting"


def test_transcript_missing_meeting_404s(client, db):
    assert client.get("/meetings/99999/transcript").status_code == 404


def test_status_reports_latest_meeting_and_counts(client, db):
    _meeting(db)
    older = Meeting(granicus_clip_id="199", granicus_view_id="13", body="city_council",
                    meeting_type="council_regular", meeting_date=datetime.date(2024, 1, 2),
                    title="Older meeting", status="extracted")
    db.add(older)
    db.flush()
    db.add(TranscriptChunk(meeting_id=older.id, start_seconds=1, text="Only this one is transcribed."))
    db.add_all([
        Entity(entity_type="project", name="Trail", canonical_slug="trail"),
        # people aren't "topics" and must not inflate the count
        Entity(entity_type="person", name="A Member", canonical_slug="a-member"),
    ])
    db.commit()

    body = client.get("/status/").json()
    assert body["latest_meeting"]["date"] == "2025-03-04"
    assert body["counts"] == {"meetings": 2, "meetings_transcribed": 1, "topics": 1}


def test_status_flags_a_run_that_never_finished(client, db):
    db.add(IngestRun(phase="phase1_ingest", meetings_processed=3, errors=[]))
    db.commit()
    body = client.get("/status/").json()
    assert body["last_run"]["meetings_processed"] == 3
    # no finished_at → the pass died partway, and the footer must say so
    assert body["last_run"]["ok"] is False


def test_status_flags_a_run_that_recorded_errors(client, db):
    db.add(IngestRun(phase="phase1_ingest", meetings_processed=2,
                     finished_at=datetime.datetime(2025, 3, 4, 6, 0),
                     errors=[{"clip_id": "200", "error": "boom"}]))
    db.commit()
    body = client.get("/status/").json()
    assert body["last_run"]["error_count"] == 1
    assert body["last_run"]["ok"] is False


def test_status_on_an_empty_database(client, db):
    body = client.get("/status/").json()
    assert body["last_run"] is None
    assert body["latest_meeting"] is None
    assert body["next_meeting"] is None
    assert body["counts"]["meetings"] == 0


def test_status_surfaces_the_next_meeting(client, db):
    db.add_all([
        UpcomingMeeting(granicus_event_id="e2", granicus_view_id="13",
                        title="Later council meeting",
                        starts_at=datetime.datetime(2025, 4, 2, 19, 0)),
        UpcomingMeeting(granicus_event_id="e1", granicus_view_id="13",
                        title="Next council meeting",
                        starts_at=datetime.datetime(2025, 3, 5, 19, 0)),
    ])
    db.commit()
    body = client.get("/status/").json()
    assert body["next_meeting"]["title"] == "Next council meeting"


def test_entities_list_pages_with_offset(client, db):
    m = _meeting(db)
    from councilhound.db.models import EntityUpdate
    for i in range(3):
        e = Entity(entity_type="project", name=f"Project {i}", canonical_slug=f"project-{i}")
        db.add(e)
        db.flush()
        db.add(EntityUpdate(entity_id=e.id, meeting_id=m.id, update_text="Discussed."))
    db.commit()

    first = client.get("/entities/", params={"limit": 2, "offset": 0}).json()
    second = client.get("/entities/", params={"limit": 2, "offset": 2}).json()
    assert len(first) == 2
    assert len(second) == 1
    # no row appears on both pages
    assert not {e["slug"] for e in first} & {e["slug"] for e in second}
