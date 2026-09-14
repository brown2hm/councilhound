"""The unified directory filters, the change feed (+ Atom), typeahead,
entity hits in search, near-me, geocode proxying, and the meeting page's
per-item topic/document links."""
import datetime

from sqlalchemy import select

from councilhound.db.models import (
    EntityProfile,
    AgendaItem, CityProject, Document, Entity, EntityAlias, EntityGeocode, EntityMention,
    EntityUpdate, Meeting,
)


def _meeting(db, day, body="city_council", clip="500"):
    m = Meeting(granicus_clip_id=clip, granicus_view_id="13", body=body,
                meeting_type="council_regular", meeting_date=day,
                title="City Council Regular Meeting" if body == "city_council"
                else "Planning Commission Meeting", status="extracted")
    db.add(m)
    db.flush()
    return m


def _seed(db):
    today = datetime.date.today()
    old = _meeting(db, today - datetime.timedelta(days=400), clip="1")
    recent_pc = _meeting(db, today - datetime.timedelta(days=3),
                         body="planning_commission", clip="2")
    recent = _meeting(db, today - datetime.timedelta(days=2), clip="3")

    item = AgendaItem(meeting_id=recent.id, label="7a", title="Willard Way townhomes rezoning",
                      outcome="Approved 5-1", start_seconds=300)
    db.add(item)
    db.flush()
    db.add(Document(meeting_id=recent.id, agenda_item_id=item.id, doc_type="agenda_item_pdf",
                    title="Staff report 7a", source_url="https://example.gov/7a.pdf"))
    db.add(Document(meeting_id=recent.id, doc_type="actions_report",
                    title="Actions report", source_url="https://example.gov/actions.pdf"))

    trail = Entity(entity_type="project", name="George Snyder Trail",
                   canonical_slug="george-snyder-trail", current_status="in_progress")
    homes = Entity(entity_type="project", name="Willard Way Townhomes",
                   canonical_slug="willard-way-townhomes", current_status="approved")
    plan = Entity(entity_type="topic", name="Old Town Parking Study",
                  canonical_slug="old-town-parking-study", current_status="proposed")
    loc = Entity(entity_type="location", name="10300 Willard Way",
                 canonical_slug="10300-willard-way")
    mayor = Entity(entity_type="person", name="Catherine Read", canonical_slug="catherine-read")
    db.add_all([trail, homes, plan, loc, mayor])
    db.flush()
    db.add(EntityAlias(entity_id=trail.id, alias="Snyder Trail"))
    db.add(EntityAlias(entity_id=mayor.id, alias="Mayor Read"))
    db.add_all([
        # trail: old proposed -> recent in_progress (a status change in-window)
        EntityUpdate(entity_id=trail.id, meeting_id=old.id, update_text="Proposed.",
                     status_after="proposed"),
        EntityUpdate(entity_id=trail.id, meeting_id=recent.id, update_text="Design underway.",
                     status_after="in_progress"),
        # homes: first ever appearance in-window, with a status
        EntityUpdate(entity_id=homes.id, meeting_id=recent.id, agenda_item_id=item.id,
                     update_text="Rezoning approved.", status_after="approved"),
        # parking study: only the PC has touched it, long ago
        EntityUpdate(entity_id=plan.id, meeting_id=old.id, update_text="Scoped.",
                     status_after="proposed"),
        # a same-status update is NOT a change
        EntityUpdate(entity_id=plan.id, meeting_id=recent_pc.id, update_text="Still scoping.",
                     status_after="proposed"),
    ])
    db.add(EntityMention(entity_id=loc.id, meeting_id=recent.id, agenda_item_id=item.id,
                         context_text="at 10300 Willard Way"))
    db.add(EntityGeocode(entity_id=loc.id, status="ok", lat=38.8480, lng=-77.3064,
                         matched_address="10300 WILLARD WAY, FAIRFAX, VA"))
    db.add(CityProject(external_slug="willard-way", entity_id=homes.id,
                       name="Willard Way Townhomes", project_type="Residential",
                       official_status="Under Review", address="10300 Willard Way",
                       detail_url="https://example.gov/p/willard", image_url="https://example.gov/w.jpg",
                       lat=38.8462, lng=-77.3064, documents=[], official_timeline=[]))
    db.commit()
    return {"old": old, "recent": recent, "recent_pc": recent_pc, "item": item}


def test_directory_filters_and_card_fields(client, db):
    _seed(db)
    rows = client.get("/entities/").json()
    by_slug = {r["slug"]: r for r in rows}
    homes = by_slug["willard-way-townhomes"]
    assert homes["official"]["image_url"] == "https://example.gov/w.jpg"
    assert homes["official"]["slug"] == "willard-way"
    assert homes["lat"] == 38.8462 and homes["bodies"] == ["city_council"]
    assert by_slug["george-snyder-trail"]["official"] is None
    assert by_slug["george-snyder-trail"]["bodies"] == ["city_council"]

    # recency: only topics updated in the last 7 days
    recent = {r["slug"] for r in client.get("/entities/", params={"days": 7}).json()}
    assert recent == {"george-snyder-trail", "willard-way-townhomes", "old-town-parking-study"}
    # body: the parking study has only been before the commission... and council long ago
    pc = {r["slug"] for r in client.get("/entities/", params={"body": "planning_commission"}).json()}
    assert pc == {"old-town-parking-study"}
    # the one-mention tail
    busy = {r["slug"] for r in client.get("/entities/", params={"min_updates": 2}).json()}
    assert busy == {"george-snyder-trail", "old-town-parking-study"}
    # official-only and alias search
    assert [r["slug"] for r in client.get("/entities/", params={"official": "true"}).json()] == [
        "willard-way-townhomes"]
    assert [r["slug"] for r in client.get("/entities/", params={"q": "snyder trail"}).json()] == [
        "george-snyder-trail"]
    # sort=active puts the busiest first
    assert client.get("/entities/", params={"sort": "active"}).json()[0]["update_count"] == 2


def test_directory_can_hide_people_and_reports_counts(client, db):
    seeded = _seed(db)
    mayor = db.scalar(select(Entity).where(Entity.canonical_slug == "catherine-read"))
    db.add(EntityUpdate(entity_id=mayor.id, meeting_id=seeded["recent"].id,
                        update_text="Presided.", status_after=None))
    db.commit()

    everyone = {r["slug"] for r in client.get("/entities/").json()}
    assert "catherine-read" in everyone
    no_people = {r["slug"] for r in client.get("/entities/", params={"exclude_type": "person"}).json()}
    assert no_people == everyone - {"catherine-read"}

    counts = client.get("/entities/counts").json()
    assert counts["by_type"] == {"project": 2, "topic": 1, "person": 1}
    assert counts["total"] == 4 and counts["people"] == 1 and counts["records"] == 3
    assert counts["official"] == 1
    assert counts["recurring"] == 2  # trail and parking study; the mayor's single update never counts


def test_entity_threads_group_history_by_project(client, db):
    seeded = _seed(db)
    loc = db.scalar(select(Entity).where(Entity.canonical_slug == "10300-willard-way"))
    homes = db.scalar(select(Entity).where(Entity.canonical_slug == "willard-way-townhomes"))
    # the street is named on the townhomes' item (a thread) and in an update
    # with no agenda item (unthreaded)
    db.add(EntityUpdate(entity_id=loc.id, meeting_id=seeded["recent"].id,
                        agenda_item_id=seeded["item"].id, update_text="Site of the rezoning."))
    db.add(EntityUpdate(entity_id=loc.id, meeting_id=seeded["old"].id, update_text="Mentioned in passing."))
    db.add(EntityProfile(entity_id=homes.id, summary="Twelve townhomes on Willard Way. Rezoned in 2026. Construction follows."))
    db.commit()

    detail = client.get("/entities/10300-willard-way").json()
    assert [t["date"] for t in detail["timeline"]] == [detail["timeline"][0]["date"], detail["timeline"][1]["date"]]
    assert len(detail["threads"]) == 1
    thread = detail["threads"][0]
    assert thread["slug"] == "willard-way-townhomes" and thread["current_status"] == "approved"
    assert thread["official_status"] == "Under Review" and thread["official_slug"] == "willard-way"
    assert thread["lead"] == "Twelve townhomes on Willard Way. Rezoned in 2026."
    assert thread["rows"] == [1]  # the recent, item-bearing row; the old one stays unthreaded
    # a project with no shared items has no threads at all
    assert client.get("/entities/george-snyder-trail").json()["threads"] == []


def test_changes_feed_reports_transitions_and_new_topics(client, db):
    _seed(db)
    data = client.get("/entities/changes", params={"days": 7}).json()
    by_slug = {c["slug"]: c for c in data["changes"]}
    assert by_slug["george-snyder-trail"]["kind"] == "status_change"
    assert by_slug["george-snyder-trail"]["from_status"] == "proposed"
    assert by_slug["george-snyder-trail"]["to_status"] == "in_progress"
    assert by_slug["willard-way-townhomes"]["kind"] == "new"
    assert by_slug["willard-way-townhomes"]["watch_url"].endswith("starttime=300&entrytime=300")
    # same status again is not news
    assert "old-town-parking-study" not in by_slug

    atom = client.get("/entities/changes.atom")
    assert atom.status_code == 200
    assert atom.headers["content-type"].startswith("application/atom+xml")
    assert "George Snyder Trail: proposed → in progress" in atom.text
    assert "New topic: Willard Way Townhomes" in atom.text


def test_suggest_typeahead_covers_topics_and_members(client, db):
    _seed(db)
    hits = client.get("/entities/suggest", params={"q": "snyder"}).json()
    assert hits[0]["slug"] == "george-snyder-trail" and hits[0]["href"] == "/topics/george-snyder-trail"
    members = client.get("/entities/suggest", params={"q": "read"}).json()
    assert members[0] == {
        "kind": "member", "slug": "catherine-read", "name": "Catherine Read",
        "entity_type": "person", "current_status": None, "update_count": 0,
        "last_seen": None, "href": "/members/catherine-read"}
    assert client.get("/entities/suggest", params={"q": "z"}).status_code == 422


def test_search_leads_with_matching_topics(client, db, monkeypatch):
    _seed(db)
    monkeypatch.setattr("app.routers.search.embed_query", lambda q: [0.1] * 768)
    data = client.get("/search/", params={"q": "willard"}).json()
    assert [e["slug"] for e in data["entities"]] == ["willard-way-townhomes"]
    assert any(r["kind"] == "agenda_item" for r in data["results"])
    # body filter applies to entity hits too
    data = client.get("/search/", params={"q": "willard", "body": "planning_commission"}).json()
    assert data["entities"] == []


def test_near_sorts_by_distance_within_radius(client, db):
    _seed(db)
    data = client.get("/entities/near", params={"lat": 38.8462, "lng": -77.3064,
                                               "radius_m": 500}).json()
    slugs = [r["slug"] for r in data["results"]]
    assert slugs == ["willard-way-townhomes", "10300-willard-way"]
    assert data["results"][0]["distance_m"] == 0
    assert data["results"][0]["official"]["image_url"] == "https://example.gov/w.jpg"
    # a tight radius excludes the geocoded location ~200 m away
    data = client.get("/entities/near", params={"lat": 38.8462, "lng": -77.3064,
                                               "radius_m": 100}).json()
    assert [r["slug"] for r in data["results"]] == ["willard-way-townhomes"]


def test_geocode_proxies_and_maps_misses_to_404(client, monkeypatch):
    calls = []

    def fake(address):
        calls.append(address)
        return {"lat": 38.85, "lng": -77.3, "matched_address": "X"} if "Main" in address else None

    monkeypatch.setattr("councilhound.geocode.geocode_address", fake)
    assert client.get("/entities/geocode", params={"q": "10455 Armstrong St"}).status_code == 404
    hit = client.get("/entities/geocode", params={"q": "123 Main St"}).json()
    assert hit["lat"] == 38.85 and calls[-1] == "123 Main St"


def test_meeting_items_carry_topics_and_documents(client, db):
    ctx = _seed(db)
    detail = client.get(f"/meetings/{ctx['recent'].id}").json()
    item = detail["agenda_items"][0]
    topics = {e["slug"]: e for e in item["entities"]}
    # the tracked update leads; the bare mention of the address follows
    assert list(topics) == ["willard-way-townhomes", "10300-willard-way"]
    assert topics["willard-way-townhomes"]["status_after"] == "approved"
    assert [d["title"] for d in item["documents"]] == ["Staff report 7a"]
    assert [d["doc_type"] for d in detail["documents"] if d["agenda_item_id"] is None] == [
        "actions_report"]
