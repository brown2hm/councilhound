"""Endpoint tests against a scratch database with realistic Phase 1-4 rows.
The /ask test mocks the embedding + Claude calls — it exercises retrieval
SQL and citation wiring, not the models."""
import datetime

from councilhound.db.models import (
    AgendaItem, Entity, EntityAlias, EntityMention, EntityProfile, EntityUpdate,
    Meeting, TranscriptChunk, Vote,
)


def _seed(db):
    m1 = Meeting(granicus_clip_id="100", granicus_view_id="13", body="city_council",
                 meeting_type="council_regular", meeting_date=datetime.date(2025, 1, 7),
                 title="City Council Regular Meeting", status="extracted")
    m2 = Meeting(granicus_clip_id="101", granicus_view_id="13", body="planning_commission",
                 meeting_type="planning_commission", meeting_date=datetime.date(2025, 6, 3),
                 title="Planning Commission Meeting", status="extracted")
    db.add_all([m1, m2])
    db.flush()

    item = AgendaItem(meeting_id=m1.id, label="7a", title="Trail design contract",
                      outcome="Approved 5-1", start_seconds=439, embedding=[0.1] * 768)
    db.add(item)
    db.flush()
    db.add(Vote(meeting_id=m1.id, agenda_item_id=item.id, description="Approve contract",
                motion_result="passed", vote_breakdown={"Read": "yes"}))

    trail = Entity(entity_type="project", name="George Snyder Trail",
                   canonical_slug="george-snyder-trail", current_status="completed")
    db.add(trail)
    db.flush()
    db.add_all([
        EntityUpdate(entity_id=trail.id, meeting_id=m1.id, agenda_item_id=item.id,
                     update_text="Design contract approved.", status_after="in_progress"),
        EntityUpdate(entity_id=trail.id, meeting_id=m2.id,
                     update_text="Completed.", status_after="completed"),
        ])
    db.add(TranscriptChunk(meeting_id=m1.id, start_seconds=120, end_seconds=180,
                           text="Discussion of the trail design contract.",
                           embedding=[0.1] * 768))
    db.commit()
    return m1, m2


def test_meetings_list_and_filters(client, db):
    m1, _m2 = _seed(db)
    all_meetings = client.get("/meetings/").json()
    assert len(all_meetings) == 2
    assert all_meetings[0]["date"] == "2025-06-03"  # newest first

    council_only = client.get("/meetings/", params={"body": "city_council"}).json()
    assert [m["id"] for m in council_only] == [m1.id]
    assert council_only[0]["agenda_item_count"] == 1


def test_meeting_detail(client, db):
    m1, _ = _seed(db)
    detail = client.get(f"/meetings/{m1.id}").json()
    item = detail["agenda_items"][0]
    assert item["label"] == "7a"
    assert item["votes"][0]["motion_result"] == "passed"
    # official index-point timestamp -> Granicus deep link (never hosted video);
    # starttime seeks the legacy player, entrytime the modern /player/clip/ one
    assert item["start_seconds"] == 439
    assert item["watch_url"].endswith(
        "MediaPlayer.php?view_id=13&clip_id=100&starttime=439&entrytime=439")
    assert client.get("/meetings/999999").status_code == 404


def test_timeline_watch_url(client, db):
    _seed(db)
    detail = client.get("/entities/george-snyder-trail").json()
    linked = [t for t in detail["timeline"] if t["watch_url"]]
    assert len(linked) == 1  # only the entry whose agenda item has a timestamp
    assert linked[0]["watch_url"].endswith("&starttime=439&entrytime=439")


def test_entity_timeline(client, db):
    _seed(db)
    listing = client.get("/entities/", params={"entity_type": "project"}).json()
    assert listing[0]["slug"] == "george-snyder-trail"
    assert listing[0]["update_count"] == 2

    detail = client.get("/entities/george-snyder-trail").json()
    assert detail["current_status"] == "completed"
    assert detail["profile"] is None  # not yet synthesized
    dates = [t["date"] for t in detail["timeline"]]
    assert dates == sorted(dates)  # chronological
    assert detail["timeline"][0]["status_after"] == "in_progress"
    assert detail["timeline"][1]["status_after"] == "completed"
    assert client.get("/entities/nope").status_code == 404


def test_entity_status_source_votes_and_alias_redirect(client, db):
    m1, _m2 = _seed(db)
    detail = client.get("/entities/george-snyder-trail").json()

    # provenance: the latest status-bearing timeline entry
    assert detail["status_source"]["meeting_title"] == "Planning Commission Meeting"
    assert detail["status_source"]["date"] == "2025-06-03"

    # votes ride along on the timeline entry whose agenda item has them
    assert detail["timeline"][0]["votes"][0]["motion_result"] == "passed"
    assert detail["timeline"][0]["votes"][0]["vote_breakdown"] == {"Read": "yes"}
    assert detail["timeline"][1]["votes"] == []

    # a merged-away slug lives on as an alias and keeps resolving
    from sqlalchemy import select
    trail = db.scalar(select(Entity).where(Entity.canonical_slug == "george-snyder-trail"))
    db.add(EntityAlias(entity_id=trail.id, alias="george-snyder-trail-project"))
    db.commit()
    redirected = client.get("/entities/george-snyder-trail-project").json()
    assert redirected["slug"] == "george-snyder-trail"


def test_entity_related_by_co_mention(client, db):
    m1, m2 = _seed(db)
    from sqlalchemy import select
    trail = db.scalar(select(Entity).where(Entity.canonical_slug == "george-snyder-trail"))
    plaza = Entity(entity_type="project", name="Courthouse Plaza", canonical_slug="courthouse-plaza")
    once = Entity(entity_type="topic", name="One Off", canonical_slug="one-off")
    db.add_all([plaza, once])
    db.flush()
    db.add_all([
        EntityMention(entity_id=trail.id, meeting_id=m1.id, role="discussed"),
        EntityMention(entity_id=trail.id, meeting_id=m2.id, role="discussed"),
        EntityMention(entity_id=plaza.id, meeting_id=m1.id, role="discussed"),
        EntityMention(entity_id=plaza.id, meeting_id=m2.id, role="discussed"),
        EntityMention(entity_id=once.id, meeting_id=m1.id, role="discussed"),
    ])
    db.commit()

    detail = client.get("/entities/george-snyder-trail").json()
    related = detail["related"]
    assert [r["slug"] for r in related] == ["courthouse-plaza"]  # >= 2 shared meetings
    assert related[0]["shared_meetings"] == 2


def test_meeting_stats(client, db):
    _seed(db)  # 2025 meetings fall outside the window
    m = Meeting(granicus_clip_id="200", granicus_view_id="13", body="city_council",
                meeting_type="council_regular", title="Recent Meeting", status="extracted",
                meeting_date=datetime.date.today() - datetime.timedelta(days=3),
                duration_seconds=7200)
    db.add(m)
    db.flush()
    db.add_all([
        Vote(meeting_id=m.id, description="Motion A", motion_result="passed",
             vote_breakdown={"Read": "yes"}),
        Vote(meeting_id=m.id, description="Motion B", motion_result="failed",
             vote_breakdown={"Read": "no"}),
    ])
    db.commit()

    stats = client.get("/meetings/stats").json()
    assert stats["meetings_held"] == 1
    assert stats["hours_of_meetings"] == 2.0
    assert stats["votes_taken"] == 2
    assert stats["motions_passed"] == 1
    assert stats["motions_failed"] == 1


def test_entity_profile_in_detail(client, db):
    _seed(db)
    from sqlalchemy import select
    trail = db.scalar(select(Entity).where(Entity.canonical_slug == "george-snyder-trail"))
    db.add(EntityProfile(
        entity_id=trail.id,
        summary="A trail project with a contested history.",
        open_questions=["VDOT repayment amount not finalized."],
        member_commentary=[{"member": "Councilmember Hall", "slug": "stacy-hall",
                            "summary": "Requested cancellation cost analysis."}],
    ))
    db.commit()

    detail = client.get("/entities/george-snyder-trail").json()
    assert detail["profile"]["summary"].startswith("A trail project")
    assert detail["profile"]["open_questions"] == ["VDOT repayment amount not finalized."]
    assert detail["profile"]["member_commentary"][0]["slug"] == "stacy-hall"


def test_hot_topics_endpoint(client, db):
    _seed(db)
    resp = client.get("/entities/hot")
    assert resp.status_code == 200
    data = resp.json()
    # seeded transcript chunk mentions 'the trail' but not the entity name;
    # shape is what matters here (scoring logic is unit-tested in ingestion)
    assert "meetings" in data and "topics" in data


def test_ask_with_mocked_llm(client, db, monkeypatch):
    _seed(db)
    monkeypatch.setattr("app.routers.ask.embed_query", lambda q: [0.1] * 768)
    monkeypatch.setattr("app.routers.ask._answer",
                        lambda q, sources: "The contract was approved [1].")

    resp = client.post("/ask/", json={"question": "What happened with the trail?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "[1]" in data["answer"]
    assert len(data["citations"]) == 1
    cite = data["citations"][0]
    assert cite["index"] == 1
    assert cite["link"]  # every citation must link back to a source
