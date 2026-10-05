"""Pipeline ingest behavior. The key guarantee: a just-happened meeting whose
audio isn't downloadable yet must still reach 'fetched' so it can be
structured from its agenda/minutes — audio is best-effort, not a gate."""
import datetime
import os

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


def test_rescan_never_downgrades_extracted(db_session, monkeypatch):
    s = db_session
    m = _discovered(s)
    m.status = "extracted"
    s.flush()
    monkeypatch.setattr(pipeline, "discover", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "fetch_documents", lambda session, meeting: 1)
    monkeypatch.setattr(pipeline, "fetch_media", lambda session, meeting: None)

    pipeline.run_ingest(s, "13", since=datetime.date(2026, 7, 1))
    s.refresh(m)
    assert m.status == "extracted"  # nightly window re-scan must not reset it


def test_sync_projects_links_entities_and_geocodes(db_session, monkeypatch):
    # these exercise the City's OpenCities adapter whatever JURISDICTION the
    # process runs under (CI also runs this file as the County)
    from councilhound.jurisdiction import JurisdictionConfig
    monkeypatch.setattr(pipeline, "JURISDICTION", JurisdictionConfig.load("fairfax_city_va"))
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
    monkeypatch.setattr(pipeline.fairfax_projects, "list_projects",
                        lambda fetch_details=True: (projects, True))

    result = pipeline.sync_projects(s)
    assert result["created"] == 1
    row = s.query(CityProject).one()
    assert row.name == "Courthouse Plaza"
    assert row.entity_id is not None
    geo = s.query(EntityGeocode).filter_by(entity_id=row.entity_id).one()
    assert float(geo.lat) == 38.8476
    assert geo.matched_address == "10300 Willard Way"


def test_sync_projects_promotes_linked_location_entity(db_session, monkeypatch):
    # these exercise the City's OpenCities adapter whatever JURISDICTION the
    # process runs under (CI also runs this file as the County)
    from councilhound.jurisdiction import JurisdictionConfig
    monkeypatch.setattr(pipeline, "JURISDICTION", JurisdictionConfig.load("fairfax_city_va"))
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
        lambda fetch_details=True: ([DiscoveredProject(
            external_slug="10340-Democracy-Lane",
            name="10340 Democracy Lane",
            detail_url="https://example.test/10340-Democracy-Lane",
        )], True),
    )

    pipeline.sync_projects(s)
    s.refresh(entity)
    assert entity.entity_type == "project"


def test_sync_projects_partial_preserves_seeded_detail(db_session, monkeypatch):
    # these exercise the City's OpenCities adapter whatever JURISDICTION the
    # process runs under (CI also runs this file as the County)
    from councilhound.jurisdiction import JurisdictionConfig
    monkeypatch.setattr(pipeline, "JURISDICTION", JurisdictionConfig.load("fairfax_city_va"))
    """A partial (ArcGIS-only, html_complete=False) sync must update coords/
    status but neither prune HTML-only rows nor blank their rich detail."""
    from councilhound.scraper.fairfax_projects import DiscoveredProject
    from councilhound.db.models import CityProject

    s = db_session
    # a fully-seeded row (as a local run would leave it) + an HTML-only row
    seeded = CityProject(external_slug="Courthouse-Plaza", name="Courthouse Plaza",
                         detail_url="https://x/Courthouse-Plaza", planner_email="p@fairfaxva.gov",
                         documents=[{"label": "MDP", "url": "https://x/mdp"}],
                         official_status="Under Review")
    html_only = CityProject(external_slug="Sidewalk-Project", name="Sidewalk Project",
                           detail_url="https://x/Sidewalk-Project")
    s.add_all([seeded, html_only])
    s.flush()

    # ArcGIS-only view: just Courthouse Plaza, no detail fields, html incomplete
    monkeypatch.setattr(
        pipeline.fairfax_projects, "list_projects",
        lambda fetch_details=True: ([DiscoveredProject(
            external_slug="Courthouse-Plaza", name="Courthouse Plaza",
            detail_url="https://x/Courthouse-Plaza",
            official_status="Approved", lat=38.85, lng=-77.30,
        )], False),
    )

    result = pipeline.sync_projects(s)
    assert result["complete"] is False
    assert result["removed"] == 0  # HTML-only row NOT pruned
    assert s.query(CityProject).filter_by(external_slug="Sidewalk-Project").one()
    row = s.query(CityProject).filter_by(external_slug="Courthouse-Plaza").one()
    assert row.official_status == "Approved"          # ArcGIS field updated
    assert float(row.lat) == 38.85                    # coords updated
    assert row.planner_email == "p@fairfaxva.gov"     # HTML detail preserved
    assert row.documents == [{"label": "MDP", "url": "https://x/mdp"}]


def test_discover_body_filter(db_session, monkeypatch):
    """`bodies` narrows a discovery to the named bodies so a newly tracked
    board can be backfilled without re-walking every other body's history."""
    import datetime

    from councilhound import pipeline
    from councilhound.db.models import Meeting
    from councilhound.scraper.granicus import DiscoveredMeeting

    def fake_list(view_id):
        return [
            DiscoveredMeeting("1", view_id, "city_council", "council_regular",
                              datetime.date(2026, 3, 3), "City Council Regular Meeting"),
            DiscoveredMeeting("2", view_id, "prab", "prab_meeting",
                              datetime.date(2026, 3, 5), "PRAB Regular Meeting"),
        ]
    monkeypatch.setattr(pipeline.granicus, "list_meetings", fake_list)

    result = pipeline.discover(db_session, "13", bodies=("prab",))
    assert result == {"created": 1, "updated": 0, "total_in_scope": 1}
    assert [m.body for m in db_session.query(Meeting).all()] == ["prab"]


def _meeting(db_session, **kw):
    from councilhound.db.models import Meeting
    m = Meeting(granicus_clip_id=kw.pop("clip", "1"), granicus_view_id="7", body="board_of_supervisors",
                meeting_type="bos_meeting", meeting_date=datetime.date(2026, 9, 15), title="Board", **kw)
    db_session.add(m)
    db_session.commit()
    return m


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.content = status, text, text.encode()


def test_fetch_media_prefers_real_captions(db_session, monkeypatch, tmp_path):
    from councilhound.jurisdiction import JurisdictionConfig
    county = JurisdictionConfig.load("fairfax_county_va")
    monkeypatch.setattr(pipeline, "JURISDICTION", county)
    monkeypatch.setattr(pipeline, "RAW_DATA_DIR", str(tmp_path))
    vtt = "WEBVTT\n\n" + "\n\n".join(f"00:00:{i:02d}.000 --> 00:00:{i+1:02d}.000\nline {i}" for i in range(30))
    monkeypatch.setattr(pipeline.http, "get_http_session",
                        lambda: type("S", (), {"get": lambda self, url, timeout=0: _Resp(200, vtt)})())
    downloads = []
    monkeypatch.setattr(pipeline.http, "download", lambda url, dest, timeout=0: downloads.append(url))
    m = _meeting(db_session, video_url="https://archive-video.granicus.com/fairfaxva/x.mp4")
    path = pipeline.fetch_media(db_session, m)
    assert path.endswith("captions.vtt") and m.audio_local_path == path
    assert downloads == []  # never touched the 8 GB MP4


def test_fetch_media_falls_back_to_mp4_audio(db_session, monkeypatch, tmp_path):
    from councilhound.jurisdiction import JurisdictionConfig
    county = JurisdictionConfig.load("fairfax_county_va")
    monkeypatch.setattr(pipeline, "JURISDICTION", county)
    monkeypatch.setattr(pipeline, "RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline.http, "get_http_session",
                        lambda: type("S", (), {"get": lambda self, url, timeout=0: _Resp(404, "<html>Not Found")})())

    def fake_download(url, dest, timeout=0):
        with open(dest, "wb") as f:
            f.write(b"video")
    monkeypatch.setattr(pipeline.http, "download", fake_download)
    extracted = []

    def fake_extract(video, audio):
        extracted.append(video)
        with open(audio, "wb") as f:
            f.write(b"audio")
        return audio
    monkeypatch.setattr(pipeline, "extract_audio_track", fake_extract)
    m = _meeting(db_session, clip="2", video_url="https://archive-video.granicus.com/fairfaxva/x.mp4")
    path = pipeline.fetch_media(db_session, m)
    assert path.endswith("audio.m4a") and extracted and not os.path.exists(extracted[0])  # video removed


def test_fetch_media_city_still_downloads_mp3(db_session, monkeypatch, tmp_path):
    from councilhound.jurisdiction import JurisdictionConfig
    monkeypatch.setattr(pipeline, "JURISDICTION", JurisdictionConfig.load("fairfax_city_va"))
    monkeypatch.setattr(pipeline, "RAW_DATA_DIR", str(tmp_path))
    downloads = []

    def fake_download(url, dest, timeout=0):
        downloads.append(url)
        with open(dest, "wb") as f:
            f.write(b"mp3")
    monkeypatch.setattr(pipeline.http, "download", fake_download)
    m = _meeting(db_session, clip="3", audio_url="https://archive-video.granicus.com/fairfax/x.mp3")
    m.body = "city_council"
    db_session.commit()
    path = pipeline.fetch_media(db_session, m)
    assert path.endswith("audio.mp3") and downloads == [m.audio_url]
