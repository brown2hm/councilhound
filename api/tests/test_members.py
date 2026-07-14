"""Member roster/detail: roles from title aliases, votes matched by the
last-name keys minutes use, commentary pulled from entity profiles."""
import datetime

from councilhound.db.models import (
    AgendaItem, Entity, EntityAlias, EntityProfile, Meeting, Vote,
)


def _seed_members(db):
    m = Meeting(granicus_clip_id="300", granicus_view_id="13", body="city_council",
                meeting_type="council_regular", meeting_date=datetime.date(2026, 6, 1),
                title="City Council Meeting", status="extracted")
    db.add(m)
    db.flush()
    item = AgendaItem(meeting_id=m.id, label="7a", title="Trail contract", start_seconds=100)
    db.add(item)
    db.flush()
    db.add(Vote(meeting_id=m.id, agenda_item_id=item.id, description="Approve",
                motion_result="passed",
                vote_breakdown={"Read": "yes", "Amos": "no"}))

    mayor = Entity(entity_type="person", name="Catherine Read", canonical_slug="catherine-read")
    amos = Entity(entity_type="person", name="Billy Amos", canonical_slug="billy-amos")
    civilian = Entity(entity_type="person", name="Random Speaker", canonical_slug="random-speaker")
    topic = Entity(entity_type="project", name="George Snyder Trail",
                   canonical_slug="george-snyder-trail")
    db.add_all([mayor, amos, civilian, topic])
    db.flush()
    db.add_all([
        EntityAlias(entity_id=mayor.id, alias="Mayor Read"),
        EntityAlias(entity_id=amos.id, alias="Councilmember Amos"),
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
    assert [m["slug"] for m in members] == ["catherine-read", "billy-amos"]
    assert members[0]["roles"] == ["Mayor"]
    assert members[0]["votes_cast"] == 1


def test_member_detail_votes_and_commentary(client, db):
    _seed_members(db)
    detail = client.get("/members/catherine-read").json()
    assert detail["vote_stats"] == {"yes": 1}
    v = detail["votes"][0]
    assert v["vote"] == "yes" and v["item_label"] == "7a"
    assert v["watch_url"].endswith("starttime=100&entrytime=100")
    assert detail["commentary"][0]["topic_slug"] == "george-snyder-trail"

    assert client.get("/members/george-snyder-trail").status_code == 404
    assert client.get("/members/nobody").status_code == 404
