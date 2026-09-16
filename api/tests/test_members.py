"""Member roster/detail: roles from title aliases, votes matched by the
last-name keys minutes use, commentary pulled from entity profiles."""
import datetime

from councilhound.db.models import (
    AgendaItem, Document, Entity, EntityAlias, EntityMention, EntityProfile, Meeting, Vote,
)

# latest council agenda header: Read is on the roster, Amos is not -> former
ROSTER_HEADER = """City of Fairfax
Mayor
Catherine S. Read
City Council
Billy M. Bates
Stacy R. Hall
"""


def _seed_members(db):
    m = Meeting(granicus_clip_id="300", granicus_view_id="13", body="city_council",
                meeting_type="council_regular", meeting_date=datetime.date(2026, 6, 1),
                title="City Council Meeting", status="extracted")
    db.add(m)
    db.flush()
    item = AgendaItem(meeting_id=m.id, label="7a", title="Trail contract", start_seconds=100)
    db.add(item)
    db.flush()
    db.add(Document(meeting_id=m.id, doc_type="agenda", source_url="x",
                    raw_text=ROSTER_HEADER))
    db.add(Vote(meeting_id=m.id, agenda_item_id=item.id, description="Approve",
                motion_result="passed",
                vote_breakdown={"Read": "yes", "Amos": "no"}))
    # a second, contested vote on a public hearing so the detail page has a
    # tally, a split and a category to show
    hearing = AgendaItem(meeting_id=m.id, label="8a", title="Public hearing on the trail budget")
    db.add(hearing)
    db.flush()
    db.add(Vote(meeting_id=m.id, agenda_item_id=hearing.id, description="Adopt the appropriation",
                motion_result="failed",
                vote_breakdown={"Read": "yes", "Amos": "no", "Hall": "no"}))

    mayor = Entity(entity_type="person", name="Catherine Read", canonical_slug="catherine-read")
    amos = Entity(entity_type="person", name="Billy Amos", canonical_slug="billy-amos")
    hall = Entity(entity_type="person", name="Stacy Hall", canonical_slug="stacy-hall")
    civilian = Entity(entity_type="person", name="Random Speaker", canonical_slug="random-speaker")
    topic = Entity(entity_type="project", name="George Snyder Trail",
                   canonical_slug="george-snyder-trail")
    db.add_all([mayor, amos, hall, civilian, topic])
    db.flush()
    db.add_all([
        EntityAlias(entity_id=mayor.id, alias="Mayor Read"),
        EntityAlias(entity_id=amos.id, alias="Councilmember Amos"),
        EntityAlias(entity_id=hall.id, alias="Councilmember Hall"),
        EntityMention(entity_id=topic.id, meeting_id=m.id, agenda_item_id=item.id, role="subject"),
        EntityMention(entity_id=topic.id, meeting_id=m.id, agenda_item_id=hearing.id, role="subject"),
    ])
    db.add(EntityProfile(
        entity_id=topic.id, summary="s",
        member_commentary=[{"member": "Mayor Read", "slug": "catherine-read",
                            "summary": "Wants a cost analysis."}],
    ))
    db.commit()


def test_member_list_roster_only(client, db):
    _seed_members(db)
    members = client.get("/members/").json()
    # civilians without title aliases are not on the roster
    assert [m["slug"] for m in members] == ["catherine-read", "stacy-hall", "billy-amos"]
    assert members[0]["roles"] == ["Mayor"]
    assert members[0]["votes_cast"] == 2
    # the latest agenda header names Read and Hall but not Amos
    assert members[0]["is_current"] is True
    assert members[2]["is_current"] is False
    # the record behind the roster table: split, share with the outcome, last no
    read, hall, amos = members
    assert read["vote_stats"] == {"yes": 2} and read["with_outcome_pct"] == 50
    assert read["last_no"] is None
    assert amos["vote_stats"] == {"no": 2} and amos["with_outcome_pct"] == 50
    assert amos["last_no"]["date"] == "2026-06-01"
    assert amos["last_no"]["subject"] in ("Approve", "Adopt the appropriation")


def test_member_detail_votes_and_commentary(client, db):
    _seed_members(db)
    detail = client.get("/members/catherine-read").json()
    assert detail["is_current"] is True
    assert client.get("/members/billy-amos").json()["is_current"] is False
    assert detail["vote_stats"] == {"yes": 2}
    v = next(x for x in detail["votes"] if x["item_label"] == "7a")
    assert v["vote"] == "yes"
    assert v["watch_url"].endswith("starttime=100&entrytime=100")
    assert detail["commentary"][0]["topic_slug"] == "george-snyder-trail"

    assert client.get("/members/george-snyder-trail").status_code == 404
    assert client.get("/members/nobody").status_code == 404


def test_member_detail_reads_the_record(client, db):
    """The detail page's analytics: each vote carries the body's tally and
    topics, the record summarises minority and close votes, colleagues are
    the current members of the same body with alignment, and the splits
    name who voted no together."""
    _seed_members(db)
    hall = client.get("/members/stacy-hall").json()
    assert hall["body"] == "city_council"
    assert hall["record"]["votes"] == 1 and hall["record"]["meetings"] == 1
    v = hall["votes"][0]
    assert v["tally"] == {"yes": 1, "no": 2} and v["contested"] is True
    # a no on a motion that failed is the winning side
    assert v["in_minority"] is False
    assert v["category"] == "hearing"
    assert [t["slug"] for t in v["topics"]] == ["george-snyder-trail"]
    assert hall["record"]["minority"] == {"total": 0, "no_on_passed": 0, "yes_on_failed": 0}
    assert hall["record"]["close_votes"] == {"total": 1, "lost": 0}
    assert hall["record"]["comparisons"] is False  # one contested vote is no basis
    assert hall["categories"][0] == {"key": "hearing", "label": "Public hearings", "votes": 1, "no": 1, "absent": 0}
    assert hall["matters"][0]["slug"] == "george-snyder-trail" and hall["matters"][0]["votes"] == {"no": 1}
    # Read is the only other current council member; she voted the other way
    assert [c["slug"] for c in hall["colleagues"]] == ["catherine-read"]
    assert hall["colleagues"][0]["agree_pct"] == 0 and hall["colleagues"][0]["no_votes"] == 0
    assert hall["splits"] == [{"no": ["stacy-hall"], "count": 1}]
    assert hall["by_meeting"][0]["contested"] == 1 and hall["by_meeting"][0]["absent"] == 0

    read = client.get("/members/catherine-read").json()
    # yes on a motion that failed: in the minority, on a one-vote margin
    assert read["record"]["minority"] == {"total": 1, "no_on_passed": 0, "yes_on_failed": 1}
    assert read["record"]["close_votes"] == {"total": 2, "lost": 1}  # 1–1 passed, 1–2 failed
    assert read["record"]["absent_meetings"] == []


def test_hyphenated_last_name_matches_its_tail():
    from app.routers.members import _cast_for, _cast_keys
    keys = _cast_keys("Stacey Hardy-Chandler")
    assert _cast_for({"Chandler": "no"}, keys) == "no"
    assert _cast_for({"Hardy-Chandler": "yes"}, keys) == "yes"
    assert _cast_for({"Hardy": "yes"}, keys) is None
