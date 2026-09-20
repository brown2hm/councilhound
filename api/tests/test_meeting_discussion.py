"""The meeting page's account of what was discussed and how it relates to
the wiki: the filed sentence per topic, the transcript's per-item discussion,
topics the transcript names that the agenda never linked, and the wiki
context (lede, open questions, this meeting's history anchor)."""
import datetime

from councilhound.db.models import (
    AgendaItem, CityProject, Entity, EntityAlias, EntityMention, EntityProfile, EntityUpdate,
    Meeting, TranscriptChunk, WikiPage,
)

from app.discussion import slugify


def _seed(db):
    m = Meeting(granicus_clip_id="4200", granicus_view_id="13", body="city_council",
                meeting_type="council_regular", meeting_date=datetime.date(2026, 7, 14),
                title="City Council Meeting", status="extracted", duration_seconds=3600)
    db.add(m)
    db.flush()
    forest = AgendaItem(meeting_id=m.id, label="12b", title="Work Session – Urban Forest Master Plan",
                        outcome="Discussed in work session; no action taken.", start_seconds=600)
    housing = AgendaItem(meeting_id=m.id, label="12c", title="Work Session – Housing Trust Fund",
                         outcome="Discussed in work session; no action taken.", start_seconds=1800)
    unchaptered = AgendaItem(meeting_id=m.id, label="7", title="Consent Agenda", outcome="Approved.")
    db.add_all([forest, housing, unchaptered])
    db.flush()

    ufmp = Entity(entity_type="project", name="Urban Forest Master Plan",
                  canonical_slug="urban-forest-master-plan", current_status="in_progress")
    beacon = Entity(entity_type="project", name="Beacon Landing",
                    canonical_slug="beacon-landing", current_status="in_progress")
    fund = Entity(entity_type="topic", name="Housing Trust Fund", canonical_slug="housing-trust-fund")
    quiet = Entity(entity_type="project", name="Quiet Project", canonical_slug="quiet-project")
    # a generic topic whose name sits inside the UFMP's; a street with a profile
    generic = Entity(entity_type="topic", name="Master Plan", canonical_slug="master-plan")
    street = Entity(entity_type="location", name="Pickett Road", canonical_slug="pickett-road")
    db.add_all([ufmp, beacon, fund, quiet, generic, street])
    db.flush()
    db.add_all([
        EntityAlias(entity_id=beacon.id, alias="Beacon Landing project"),
        EntityUpdate(entity_id=ufmp.id, meeting_id=m.id, agenda_item_id=forest.id,
                     update_text="[12b] Council received a 1-year plan and 5-year outlook; no action.",
                     status_after=None),
        EntityUpdate(entity_id=fund.id, meeting_id=m.id, agenda_item_id=housing.id,
                     update_text="[12c] Guidelines and an application were discussed."),
        EntityMention(entity_id=ufmp.id, meeting_id=m.id, agenda_item_id=housing.id,
                      role="subject", context_text="mentioned"),
        CityProject(external_slug="urban-forest-master-plan-official", entity_id=ufmp.id,
                    name="Urban Forest Master Plan", detail_url="https://example.test/ufmp"),
        EntityProfile(entity_id=beacon.id, summary="Beacon Landing is 54 supportive units. It broke ground in 2025. Completion is due in 2026.",
                      open_questions=["Will a competitive process replace the one-off grant?"],
                      member_commentary=[]),
        EntityProfile(entity_id=fund.id, summary="The fund pools cash-in-lieu payments.",
                      open_questions=[], member_commentary=[]),
        EntityProfile(entity_id=generic.id, summary="Plans in general.", open_questions=[], member_commentary=[]),
        EntityProfile(entity_id=street.id, summary="A road.", open_questions=[], member_commentary=[]),
        WikiPage(path="projects/urban-forest-master-plan/overview.md", entity_id=ufmp.id,
                 kind="concept", page="overview", frontmatter={"title": "UFMP"},
                 body="<!-- Curator-owned page -->\n\nThe Urban Forest Master Plan (UFMP) is the city's first 20-year roadmap. Development began in May 2024. Phase 2 nears completion.\n\n<!-- curator:off -->\n\n## In this wiki\n\n- history\n",
                 content_hash="a"),
        WikiPage(path="projects/urban-forest-master-plan/history.md", entity_id=ufmp.id,
                 kind="concept", page="history", frontmatter={"title": "history"},
                 body="## 2026-02-10 — City Council Meeting\n\n- adopted\n\n## 2026-07-14 — City Council Meeting\n\n- work session\n",
                 content_hash="b"),
    ])
    chunks = [
        # inside 12b: names its own topic (filed) — not "also named"
        (610, 700, "Staff presented the Urban Forest Master Plan one year plan."),
        # inside 12c: names Beacon Landing by alias, twice, and the fund's own topic
        (1810, 1900, "The funding that was utilized for the Beacon Landing project came from the Housing Trust Fund."),
        (1900, 1960, "I think the Beacon Landing project used tax credits."),
        # inside 12c: names the UFMP, which 12c is filed under via a mention
        (1960, 2000, "This ties back to the Urban Forest Master Plan too."),
        # a topic named without a wiki or profile: invisible to the scan; a
        # street named in passing: places count only with a wiki
        (2000, 2030, "Quiet Project also came up, over on Pickett Road."),
        # before any chaptered item: counts toward the meeting, no item
        (100, 130, "Beacon Landing was raised during public comment."),
    ]
    db.add_all([TranscriptChunk(meeting_id=m.id, start_seconds=s, end_seconds=e, text=t,
                                embedding=[0.1] * 768) for s, e, t in chunks])
    db.commit()
    return m, forest, housing, unchaptered


def test_item_topics_carry_the_filed_sentence_and_wiki_home(client, db):
    m, forest, housing, _ = _seed(db)
    detail = client.get(f"/meetings/{m.id}").json()
    by_label = {it["label"]: it for it in detail["agenda_items"]}
    ufmp = by_label["12b"]["entities"][0]
    assert ufmp["update_text"].startswith("[12b] Council received")
    assert ufmp["has_wiki"] is True
    assert ufmp["official_slug"] == "urban-forest-master-plan-official"
    # the bare mention on 12c has no sentence, but still knows where its wiki is
    mention = next(e for e in by_label["12c"]["entities"] if e["slug"] == "urban-forest-master-plan")
    assert mention["update_text"] is None and mention["has_wiki"] is True
    fund = next(e for e in by_label["12c"]["entities"] if e["slug"] == "housing-trust-fund")
    assert fund["has_wiki"] is False and fund["official_slug"] is None


def test_transcript_discussion_per_item(client, db):
    m, forest, housing, unchaptered = _seed(db)
    detail = client.get(f"/meetings/{m.id}").json()
    assert detail["transcribed"] is True
    by_label = {it["label"]: it for it in detail["agenda_items"]}
    # 12b runs from its index point to 12c's: one chunk, its own topic not re-listed
    # "Master Plan" is inside "Urban Forest Master Plan", the item's own topic: not named
    assert by_label["12b"]["discussion"] == {"seconds": 90, "exact": True, "chunks": 1, "named": []}
    d = by_label["12c"]["discussion"]
    # the unchaptered consent agenda is filed after 12c, so its window is not its own
    assert d["seconds"] == 220 and d["chunks"] == 4 and d["exact"] is False
    # Beacon Landing (alias hit) is named twice and not filed on 12c; the
    # UFMP is filed there via a mention so it is not "also named"
    assert d["named"] == [{"slug": "beacon-landing", "name": "Beacon Landing", "count": 2}]
    assert by_label["7"]["discussion"] is None  # no index point


def test_named_in_discussion_is_what_the_agenda_never_linked(client, db):
    m, *_ = _seed(db)
    detail = client.get(f"/meetings/{m.id}").json()
    named = detail["named_in_discussion"]
    # Quiet Project has no wiki or profile, Pickett Road is a place without
    # one, "Master Plan" only ever appears inside the UFMP's name
    assert [t["slug"] for t in named] == ["beacon-landing"]
    beacon = named[0]
    assert beacon["count"] == 3 and beacon["seconds"] == 180
    assert beacon["first"]["start_seconds"] == 100
    assert "starttime=100" in beacon["first"]["watch_url"]
    assert "Beacon Landing was raised" in beacon["first"]["excerpt"]
    assert beacon["has_wiki"] is False and beacon["official_slug"] is None


def test_topics_carry_wiki_context_and_history_anchor(client, db):
    m, *_ = _seed(db)
    detail = client.get(f"/meetings/{m.id}").json()
    topics = {t["slug"]: t for t in detail["topics"]}
    assert list(topics) == ["urban-forest-master-plan", "housing-trust-fund"]  # agenda order, once each
    ufmp = topics["urban-forest-master-plan"]
    # overview lede: comments stripped, nav section dropped, two sentences
    assert ufmp["lede"] == "The Urban Forest Master Plan (UFMP) is the city's first 20-year roadmap. Development began in May 2024."
    assert ufmp["history_anchor"] == slugify("2026-07-14 — City Council Meeting") == "2026-07-14-city-council-meeting"
    assert ufmp["has_wiki"] is True and ufmp["official_slug"] == "urban-forest-master-plan-official"
    fund = topics["housing-trust-fund"]
    assert fund["lede"] == "The fund pools cash-in-lieu payments."  # profile lead when no wiki
    assert fund["history_anchor"] is None and fund["open_questions"] == []


def test_untranscribed_meeting_has_no_discussion(client, db):
    m = Meeting(granicus_clip_id="4201", granicus_view_id="13", body="prab",
                meeting_type="prab", meeting_date=datetime.date(2026, 9, 10),
                title="PRAB Regular Meeting", status="extracted")
    db.add(m)
    db.flush()
    db.add(AgendaItem(meeting_id=m.id, label="3", title="Park update", start_seconds=10))
    db.commit()
    detail = client.get(f"/meetings/{m.id}").json()
    assert detail["transcribed"] is False
    assert detail["agenda_items"][0]["discussion"] is None
    assert detail["named_in_discussion"] == [] and detail["topics"] == []
