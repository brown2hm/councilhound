"""Hot-topic scoring: named discussion time over recent transcribed meetings."""
import datetime

from councilhound.db.models import Entity, EntityAlias, Meeting, TranscriptChunk
from councilhound.hot_topics import hot_topics


def _meeting(db, clip, date):
    m = Meeting(granicus_clip_id=clip, granicus_view_id="13", body="city_council",
                meeting_type="council_regular", meeting_date=date,
                title=f"Meeting {clip}", status="fetched")
    db.add(m)
    db.flush()
    return m


def test_hot_topics_ranks_by_discussion_seconds(db_session):
    s = db_session
    old = _meeting(s, "1", datetime.date(2025, 1, 1))
    m1 = _meeting(s, "2", datetime.date(2025, 6, 1))
    m2 = _meeting(s, "3", datetime.date(2025, 6, 15))

    trail = Entity(entity_type="project", name="George Snyder Trail",
                   canonical_slug="george-snyder-trail")
    plaza = Entity(entity_type="project", name="Courthouse Plaza",
                   canonical_slug="courthouse-plaza")
    person = Entity(entity_type="person", name="Catherine Read",
                    canonical_slug="catherine-read")
    s.add_all([trail, plaza, person])
    s.flush()
    s.add(EntityAlias(entity_id=trail.id, alias="Snyder Trail"))

    def chunk(m, start, end, text):
        s.add(TranscriptChunk(meeting_id=m.id, start_seconds=start, end_seconds=end, text=text))

    # trail: 100s in m1 (via alias) + 50s in m2; plaza: 60s in m2
    chunk(m1, 0, 100, "Let's discuss the Snyder Trail funding gap.")
    chunk(m2, 0, 50, "Back to the George Snyder Trail repayment.")
    chunk(m2, 50, 110, "Courthouse Plaza redevelopment presentation follows.")
    # person mentions never rank; old-meeting chunks are outside the window
    chunk(m2, 110, 500, "Catherine Read called the meeting to order.")
    chunk(old, 0, 5000, "George Snyder Trail marathon session (too old to count).")
    s.commit()

    result = hot_topics(s, n_meetings=2, top=10)
    assert [m["id"] for m in result["meetings"]] == [m2.id, m1.id]

    by_slug = {t["slug"]: t for t in result["topics"]}
    assert "catherine-read" not in by_slug  # people excluded
    assert list(by_slug) == ["george-snyder-trail", "courthouse-plaza"]  # ranked
    assert by_slug["george-snyder-trail"]["seconds"] == 150
    assert by_slug["george-snyder-trail"]["chunk_mentions"] == 2
    assert by_slug["courthouse-plaza"]["seconds"] == 60
    assert by_slug["george-snyder-trail"]["per_meeting"] == {str(m1.id): 100, str(m2.id): 50}


def test_hot_topics_body_and_window(db_session):
    s = db_session
    today = datetime.date.today()
    council = _meeting(s, "10", today - datetime.timedelta(days=10))
    pc = Meeting(granicus_clip_id="11", granicus_view_id="13", body="planning_commission",
                 meeting_type="planning_commission", meeting_date=today - datetime.timedelta(days=5),
                 title="PC Meeting", status="fetched")
    old_council = _meeting(s, "12", today - datetime.timedelta(days=90))
    s.add(pc)
    s.flush()

    trail = Entity(entity_type="project", name="George Snyder Trail",
                   canonical_slug="george-snyder-trail")
    s.add(trail)
    s.flush()
    for m, dur in ((council, 100), (pc, 40), (old_council, 999)):
        s.add(TranscriptChunk(meeting_id=m.id, start_seconds=0, end_seconds=dur,
                              text="George Snyder Trail discussion."))
    s.commit()

    council_hot = hot_topics(s, days=60, body="city_council")
    assert [m["id"] for m in council_hot["meetings"]] == [council.id]  # 90-day-old excluded
    assert council_hot["topics"][0]["seconds"] == 100

    pc_hot = hot_topics(s, days=60, body="planning_commission")
    assert [m["id"] for m in pc_hot["meetings"]] == [pc.id]
    assert pc_hot["topics"][0]["seconds"] == 40
