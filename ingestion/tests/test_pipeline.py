"""Pipeline ingest behavior. The key guarantee: a just-happened meeting whose
audio isn't downloadable yet must still reach 'fetched' so it can be
structured from its agenda/minutes — audio is best-effort, not a gate."""
import datetime

from councilhound import pipeline
from councilhound.db.models import CityProject, Entity, EntityGeocode, Meeting


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


def test_sync_projects_links_entities_and_geocodes(db_session, monkeypatch):
    from councilhound.scraper.fairfax_projects import DiscoveredProject

    s = db_session
    projects = [
        DiscoveredProject(
            external_slug="Courthouse-Plaza",
            name="Courthouse Plaza",
            detail_url="https://example.test/Courthouse-Plaza",
            project_type="Private Development",
            division="Community & Development",
            official_status="Under Review",
            description="Official summary.",
            address="10300 Willard Way",
            lat=38.8476,
            lng=-77.3025,
        )
    ]
    monkeypatch.setattr(pipeline.fairfax_projects, "list_projects", lambda fetch_details=True: projects)

    result = pipeline.sync_projects(s)
    assert result["created"] == 1
    row = s.query(CityProject).one()
    assert row.name == "Courthouse Plaza"
    assert row.entity_id is not None
    geo = s.query(EntityGeocode).filter_by(entity_id=row.entity_id).one()
    assert float(geo.lat) == 38.8476
    assert geo.matched_address == "10300 Willard Way"


def test_sync_projects_promotes_linked_location_entity(db_session, monkeypatch):
    from councilhound.scraper.fairfax_projects import DiscoveredProject

    s = db_session
    entity = Entity(
        entity_type="location",
        name="10340 Democracy Lane",
        canonical_slug="10340-democracy-lane",
    )
    s.add(entity)
    s.flush()
    monkeypatch.setattr(
        pipeline.fairfax_projects,
        "list_projects",
        lambda fetch_details=True: [DiscoveredProject(
            external_slug="10340-Democracy-Lane",
            name="10340 Democracy Lane",
            detail_url="https://example.test/10340-Democracy-Lane",
        )],
    )

    pipeline.sync_projects(s)
    s.refresh(entity)
    assert entity.entity_type == "project"
