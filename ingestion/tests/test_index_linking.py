"""link_index_points: matching official index-point labels to agenda_items
(normalization, first-occurrence-wins, unmatched items stay NULL)."""
import datetime

from councilhound import pipeline
from councilhound.db.models import AgendaItem, Meeting


def test_link_index_points_matching(db_session, monkeypatch):
    s = db_session
    meeting = Meeting(granicus_clip_id="4565", granicus_view_id="13", body="city_council",
                      meeting_type="council_regular", meeting_date=datetime.date(2026, 5, 26),
                      title="City Council Meeting", status="extracted",
                      video_url="https://archive-video.granicus.com/fairfax/fairfax_x.mp4")
    s.add(meeting)
    s.flush()
    items = {
        label: AgendaItem(meeting_id=meeting.id, label=label, title=f"Item {label}")
        for label in ("1", "7a.", "9")  # '7a.' exercises label normalization
    }
    s.add_all(items.values())
    s.commit()

    monkeypatch.setattr(pipeline.granicus, "fetch_index_points", lambda clip, view: [
        {"label": "1", "time": 9, "text": "1. Call to order."},
        {"label": "7a", "time": 439, "text": "7a. Rezoning."},
        {"label": "7a", "time": 900, "text": "7a. Rezoning continued."},  # dup: first wins
        {"label": None, "time": 500, "text": "Unlabeled segment"},
    ])

    matched = pipeline.link_index_points(s, meeting)
    assert matched == 2
    assert items["1"].start_seconds == 9
    assert items["7a."].start_seconds == 439  # normalized match + first occurrence
    assert items["9"].start_seconds is None  # no marker -> no timestamp, no guess


def test_unrecorded_meetings_are_skipped(db_session, monkeypatch):
    """Advisory-board meetings (PRAB, HHCAB) have agenda items but no
    recording; Granicus 404s their player page, and there is nothing to
    timestamp anyway. They must neither be fetched nor retried every run."""
    s = db_session
    meeting = Meeting(granicus_clip_id="4642", granicus_view_id="13", body="prab",
                      meeting_type="prab_meeting", meeting_date=datetime.date(2026, 9, 10),
                      title="PRAB Regular Meeting", status="extracted")
    s.add(meeting)
    s.flush()
    s.add(AgendaItem(meeting_id=meeting.id, label="1", title="Call to Order"))
    s.commit()

    def boom(clip, view):
        raise AssertionError("player page must not be fetched for an unrecorded meeting")
    monkeypatch.setattr(pipeline.granicus, "fetch_index_points", boom)

    assert pipeline.link_index_points(s, meeting) == 0
    assert pipeline.link_index_points_pending(s) == {"meetings": 0, "failed": 0, "candidates": 0}
