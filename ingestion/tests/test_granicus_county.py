"""Fairfax County's Granicus archive (video.fairfaxcounty.gov): one view per
body, a single 'Archived Videos' section, two player clips per row (English
and Spanish captions), a MinutesViewer link that is the annotated agenda,
MP4-only downloads, and no Duration column. Fixtures are trimmed captures
from 2026-09-20."""
from pathlib import Path

import pytest

from councilhound.bodies import Registry
from councilhound.jurisdiction import JurisdictionConfig
from councilhound.scraper.granicus import (
    classify, classify_upcoming_title, match_index_point_by_title, parse_archive, parse_index_points,
    parse_upcoming,
)

FIX = Path(__file__).parent / "fixtures" / "granicus" / "fairfax_county_va"


@pytest.fixture(scope="module")
def county():
    cfg = JurisdictionConfig.load("fairfax_county_va")
    return cfg, Registry.from_config(cfg)


def test_board_rows_parse_as_single_body(county):
    cfg, reg = county
    meetings = parse_archive((FIX / "view7_archive.html").read_text(), "7", cfg, reg)
    assert len(meetings) == 3
    m = meetings[0]
    assert m.body == "board_of_supervisors" and m.meeting_type == "bos_meeting"
    assert m.title.startswith("Sept. 15, 2026 Board of Supervisors Meeting")
    assert m.meeting_date.isoformat() == "2026-09-15"
    assert m.clip_id == "4241"  # the English-captions clip, not the Spanish one (4247)
    assert m.duration_seconds is None  # no Duration column; filled from the transcript
    assert m.agenda_url and "MinutesViewer.php" in m.agenda_url and "clip_id=4241" in m.agenda_url
    assert m.minutes_url is None
    assert m.video_url.endswith(".mp4") and "/fairfaxva/" in m.video_url
    assert m.audio_url is None
    # the county-site "Full Meeting Archive" link is off until enabled
    assert not [d for d in m.extra_docs if d.doc_type == "meeting_page"]


def test_external_archive_link_when_enabled(county):
    cfg, reg = county
    cfg2 = cfg.model_copy(deep=True)
    cfg2.granicus.row.external_archive.enabled = True
    meetings = parse_archive((FIX / "view7_archive.html").read_text(), "7", cfg2, reg)
    docs = [d for d in meetings[0].extra_docs if d.doc_type == "meeting_page"]
    assert len(docs) == 1 and docs[0].url.startswith("https://www.fairfaxcounty.gov/boardofsupervisors/")


def test_planning_commission_view(county):
    cfg, reg = county
    meetings = parse_archive((FIX / "view10_archive.html").read_text(), "10", cfg, reg)
    assert len(meetings) == 3 and all(m.body == "planning_commission" for m in meetings)
    # the archive row's agenda cell is commented out; the agenda is the
    # date-named PDF on the county site, for regular meetings only
    assert meetings[0].agenda_url.endswith("/calendar/2026/9.16.26.pdf")
    assert meetings[1].agenda_url is None  # Policy Plan Committee
    assert meetings[2].agenda_url.endswith("/calendar/2026/9.9.26.pdf")
    assert meetings[0].duration_seconds is None  # the Duration cell is commented out here too
    assert [m.meeting_type for m in meetings] == [
        "planning_commission", "planning_commission_committee", "planning_commission"]


def test_county_classification_rules(county):
    _cfg, reg = county
    assert classify("board_of_supervisors", "Apr. 14, 2026 Board of Supervisors Budget Markup", reg) == (
        "board_of_supervisors", "bos_budget")
    assert classify("planning_commission", "Planning Commission Work Session", reg) == (
        "planning_commission", "planning_commission_work_session")
    assert classify("city_council", "City Council Regular Meeting", reg) is None
    assert classify_upcoming_title("September 29, 2026 Board of Supervisors Meeting", reg) == "board_of_supervisors"
    # a view owned by one body claims unmatched titles on that view only
    assert classify_upcoming_title("Public Hearing: FY 2027 Budget", reg, view_id="7") == "board_of_supervisors"
    assert classify_upcoming_title("Public Hearing: FY 2027 Budget", reg) is None


def test_upcoming_rows_on_a_single_body_view(county):
    _cfg, reg = county
    events = parse_upcoming((FIX / "view7_archive.html").read_text(), "7", reg)
    assert events and events[0].body == "board_of_supervisors"
    assert events[0].event_id == "2065" and events[0].starts_at is not None
    assert events[0].agenda_url and "AgendaViewer.php" in events[0].agenda_url


def test_player_index_points_use_the_same_markup():
    points = parse_index_points((FIX / "player_clip_4241_index.html").read_text())
    assert len(points) == 43
    assert points[0]["time"] == 5 and points[0]["text"].startswith("9:30 Presentations")
    assert any(p["time"] == 595 for p in points)


def test_index_points_match_by_title_when_labels_do_not():
    points = parse_index_points((FIX / "player_clip_4241_index.html").read_text())
    # the extractor labels County items by section ('Action Items 2'); the
    # player numbers them per section ('2.'), so titles do the matching
    assert match_index_point_by_title(
        "Endorsement of Design Plans for the Telegraph Road at Hayfield Road Safety and Accessibility Project",
        points) == 23511
    assert match_index_point_by_title("Fairfax County Police Civilian Review Panel Amended Bylaws", points) == 23858
    # a clock-time prefix on the index point is ignored
    assert match_index_point_by_title(
        "Public Hearing on SE-2026-PR-00019 (DICK'S Sporting Goods, Inc.) (Providence District)", points) == 27792
    assert match_index_point_by_title("Closed Session", points) is None  # too short to trust
    assert match_index_point_by_title("Something entirely different about nothing at all", points) is None
