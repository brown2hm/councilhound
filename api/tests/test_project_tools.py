"""Project tools for /ask: impact estimates with their ranges (one project,
or one measure ranked across projects), project lists by status, type or
distance from an address, passages from projects' own filings (newest
revision of a repeated passage only), and a project's next posted agenda."""
import datetime

import pytest

from councilhound.db.models import (
    CityProject, Entity, EntityUpdate, Meeting, ProjectDocumentChunk, ProjectEvaluation,
    UpcomingMeeting,
)

from app import ask_tools
from app.routers import ask

from tests.test_ask import _install, _number, _text, _tool

NEAR = [1.0] + [0.0] * 767
FAR = [0.0, 1.0] + [0.0] * 766


@pytest.fixture(autouse=True)
def _query_vector(monkeypatch):
    monkeypatch.setattr("app.ask_tools.embed_query", lambda q: NEAR)

def _metric(name, value, unit, low=None, high=None, headline=False):
    return {"name": name, "value": value, "unit": unit, "low": low, "high": high,
            "method": "a method", "headline": headline, "provenance": [], "assumptions": []}


REPORT = """# Impact analysis: {name}

## Executive summary

{name} would add homes.

## Fiscal effects

Real estate tax would rise.

## Not evaluated in this version

Traffic and environmental effects were not computed.
"""


def _seed(db):
    gallery_e = Entity(entity_type="project", name="Gallery at City Center", canonical_slug="gallery-at-city-center",
                       current_status="in_progress")
    orphan = Entity(entity_type="project", name="Old Town Plaza Refresh", canonical_slug="old-town-plaza-refresh")
    db.add_all([gallery_e, orphan])
    db.flush()
    gallery = CityProject(external_slug="Gallery-at-City-Center", name="Gallery at City Center",
                          entity_id=gallery_e.id, project_type="Private Development",
                          official_status="Under Review", address="4085 Chain Bridge Road",
                          description="Three mixed-use buildings.", lat=38.8463, lng=-77.3065,
                          detail_url="https://www.fairfaxva.gov/gallery", documents=[{}] * 17)
    paul = CityProject(external_slug="Paul-VI", name="Paul VI", project_type="Private Development",
                       official_status="Under Construction", address="10675 Fairfax Boulevard",
                       lat=38.8550, lng=-77.3120, detail_url="https://www.fairfaxva.gov/paul-vi")
    trail = CityProject(external_slug="Wilcoxon-Trail-Extension", name="Wilcoxon Trail Extension",
                        project_type="City Project", lat=38.8700, lng=-77.2800,
                        detail_url="https://www.fairfaxva.gov/wilcoxon")
    db.add_all([gallery, paul, trail])
    db.flush()
    for cp, students, tax in ((gallery, 31.0, 900000.0), (paul, 27.0, 1200000.0)):
        db.add(ProjectEvaluation(
            city_project_id=cp.id, status="synthesized",
            synthesized_at=datetime.datetime(2026, 9, 14, tzinfo=datetime.timezone.utc),
            module_results=[
                {"module": "economic", "narrative_notes": ["A screening estimate."], "metrics": [
                    _metric("New residents", 600.0, "residents", 500.0, 700.0, headline=True),
                    _metric("Estimated K-12 students", students, "students", students - 10, students + 15)]},
                {"module": "fiscal", "metrics": [
                    _metric("Annual school cost within the service-cost estimates", 600000.0, "$/yr", 400000.0, 900000.0),
                    _metric("Projected real estate tax", tax, "$/yr", tax * 0.8, tax * 1.2)]},
            ],
            report_markdown=REPORT.format(name=cp.name)))
    meeting = Meeting(granicus_clip_id="1", granicus_view_id="13", body="city_council",
                      meeting_type="council_regular", meeting_date=datetime.date(2026, 6, 9), title="Council")
    db.add(meeting)
    db.flush()
    db.add_all([EntityUpdate(entity_id=gallery_e.id, meeting_id=meeting.id, update_text="Work session held."),
                EntityUpdate(entity_id=orphan.id, meeting_id=meeting.id, update_text="Discussed.")])
    trips = ("The site is expected to generate approximately 292 trips in the AM peak hour and "
             "2,482 daily trips at full build-out after reductions agreed with the City.")
    url = "https://www.fairfaxva.gov/files/gallery/{}.pdf"
    db.add_all([
        # the same passage in two revisions of the study: only the newer one is kept
        ProjectDocumentChunk(city_project_id=gallery.id, doc_url=url.format("tis-april"), page=56, ordinal=0,
                             doc_label="April 24, 2023 Transportation Impact Study (PDF, 23MB)",
                             doc_date=datetime.date(2023, 4, 24), text=trips + " Page 56 April", embedding=NEAR),
        ProjectDocumentChunk(city_project_id=gallery.id, doc_url=url.format("tis-july"), page=53, ordinal=0,
                             doc_label="July 3, 2023 Transportation Impact Study (PDF, 22MB)",
                             doc_date=datetime.date(2023, 7, 3), text=trips + " Page 53 July", embedding=NEAR),
        ProjectDocumentChunk(city_project_id=gallery.id, doc_url=url.format("narrative"), page=11, ordinal=0,
                             doc_label="July 3, 2023 Narrative (PDF, 232KB)", doc_date=datetime.date(2023, 7, 3),
                             text="Five affordable dwelling units are provided on site.", embedding=FAR),
    ])
    db.add(UpcomingMeeting(granicus_event_id="e1", granicus_view_id="13", title="Planning Commission",
                           body="planning_commission", starts_at=datetime.datetime(2026, 10, 26, 19, 0),
                           agenda_url="https://fairfax.granicus.com/agenda/e1",
                           agenda_text="Public hearing: Gallery at City Center rezoning"))
    db.commit()
    return gallery, paul, trail


def _texts(sources, nums):
    return [sources.get(n) for n in nums]


def test_one_projects_estimates_with_ranges_and_gaps(db):
    _seed(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_impact(db, sources, "Gallery")
    rows = _texts(sources, nums)
    assert "modelled screening estimates" in header
    economic = next(r for r in rows if "economic estimates" in r["title"])
    assert "New residents: 600 residents (range 500 residents to 700 residents)" in economic["text"]
    assert "Notes: A screening estimate." in economic["text"]
    titles = [r["title"] for r in rows]
    # the summary and what wasn't evaluated always come along; other sections on request
    assert any("Executive summary" in t for t in titles)
    assert any("Not evaluated in this version" in t for t in titles)
    assert not any("Fiscal effects" in t for t in titles)


def test_a_measure_narrows_to_its_estimates_and_section(db):
    _seed(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_impact(db, sources, "Gallery at City Center", "real estate tax")
    rows = _texts(sources, nums)
    fiscal = next(r for r in rows if "fiscal (tax) estimates" in r["title"])
    assert fiscal["text"].startswith("Projected real estate tax: $900,000/yr (range $720,000/yr to $1,080,000/yr)")
    assert not any("economic estimates" in r["title"] for r in rows)
    assert any("Fiscal effects" in r["title"] for r in rows)
    nums, header = ask_tools.get_impact(db, sources, "Gallery", "parking spaces")
    assert "No estimate is named like 'parking spaces'" in header and "Estimated K-12 students" in header


def test_a_measure_ranks_every_analysed_project(db):
    _seed(db)
    sources = ask_tools.Sources()
    (n,), header = ask_tools.get_impact(db, sources, measure="school students")
    # the student count, not the school cost that also says "school"
    assert header.startswith("'Estimated K-12 students' across the 2 of 2 analysed projects")
    lines = sources.get(n)["text"].splitlines()
    assert lines[0].startswith("Gallery at City Center (Under Review): 31 students (range 21 students to 46 students)")
    assert lines[1].startswith("Paul VI (Under Construction): 27 students")
    nums, header = ask_tools.get_impact(db, sources, measure="noise")
    assert nums == [] and header.startswith("No impact estimate is named like 'noise'")
    assert ask_tools.get_impact(db, sources, "Wilcoxon")[1] == "Wilcoxon Trail Extension has no completed impact analysis."


def test_projects_by_status_type_and_query(db):
    _seed(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.find_projects(db, sources, status="under construction")
    assert [sources.get(n)["title"] for n in nums] == ["Paul VI: official project record"]
    assert header.startswith("1 official project (status under construction)")
    nums, header = ask_tools.find_projects(db, sources, project_type="City Project")
    assert [sources.get(n)["title"] for n in nums] == ["Wilcoxon Trail Extension: official project record"]
    # no status or type filter: projects known only from meetings come too
    nums, header = ask_tools.find_projects(db, sources)
    titles = [sources.get(n)["title"] for n in nums]
    assert "Old Town Plaza Refresh: tracked from meetings (not in the City's project directory)" in titles
    assert "3 official projects, plus 1 known only from meetings" in header
    gallery = next(sources.get(n) for n in nums if sources.get(n)["title"].startswith("Gallery"))
    assert "Impact analysis: yes" in gallery["text"] and "Tracked in meetings: 1 updates" in gallery["text"]


def test_projects_near_an_address_nearest_first(db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(ask_tools, "_geocode", lambda a: {"lat": 38.8466, "lng": -77.3060,
                                                           "matched_address": "10455 ARMSTRONG ST"})
    sources = ask_tools.Sources()
    nums, header = ask_tools.find_projects(db, sources, near="10455 Armstrong St", radius_m=1500)
    rows = _texts(sources, nums)
    assert [r["title"].split(":")[0] for r in rows] == ["Gallery at City Center", "Paul VI"]
    assert "m away" in rows[0]["text"]
    assert "within 1500 m of 10455 ARMSTRONG ST" in header
    monkeypatch.setattr(ask_tools, "_geocode", lambda a: None)
    assert ask_tools.find_projects(db, sources, near="nowhere")[1] == "The address 'nowhere' couldn't be located."


def test_filings_search_keeps_the_newest_revision(db):
    _seed(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.search_project_documents(db, sources, "peak hour trips", "Gallery")
    rows = _texts(sources, nums)
    assert header.startswith("Documents indexed for Gallery at City Center (3 of 17 listed")
    assert [r["title"] for r in rows] == [
        "Gallery at City Center: July 3, 2023 Transportation Impact Study (PDF, 22MB), page 53"]
    assert rows[0]["link"].endswith("tis-july.pdf#page=53") and rows[0]["date"] == "2023-07-03"
    assert rows[0]["kind"] == "document"
    # an exact phrase finds a passage the meaning search ranks far away
    nums, _ = ask_tools.search_project_documents(db, sources, "affordable dwelling units")
    assert any("Narrative" in sources.get(n)["title"] for n in nums)
    nums, header = ask_tools.search_project_documents(db, sources, "trips", "Wilcoxon")
    assert nums == [] and header.startswith("None of the 0 documents on Wilcoxon Trail Extension's City page")


def test_topic_carries_its_next_posted_agenda(db):
    _seed(db)
    sources = ask_tools.Sources()
    nums, header, _ = ask_tools.get_topic(db, sources, "Gallery at City Center")
    upcoming = [sources.get(n) for n in nums if sources.get(n)["kind"] == "upcoming"]
    assert upcoming and upcoming[0]["title"].startswith("Gallery at City Center on the agenda: Planning Commission")
    assert upcoming[0]["date"] == "2026-10-26"


def test_answer_cites_an_impact_estimate(client, db, monkeypatch):
    _seed(db)

    def answer(messages):
        n = _number(messages[-1]["content"][0]["content"], "economic estimates")
        return "end_turn", [_text(f"About 31 students, a modelled estimate [{n}].")]

    _install(monkeypatch, [
        lambda m: ("tool_use", [_tool("t1", "get_impact", project="Gallery", measure="students")]),
        answer,
    ])
    body = client.post("/ask/", json={"question": "How many students would the Gallery add?"}).json()
    (cite,) = body["citations"]
    assert cite["kind"] == "impact" and cite["link"] == "/development/Gallery-at-City-Center"
    assert ask._step_label("get_impact", {"project": "Gallery"}) == "Reading the impact analysis of Gallery"
