"""Phase 3 apply/resolution tests — no LLM involved; extraction dicts are
synthetic. Proves the PLAN.md definition of done: re-runs converge to the
same rows, and an entity discussed at two meetings has an ordered timeline
with the latest status rolled up."""
import datetime

from sqlalchemy import func, select

from councilhound.db.models import (
    AgendaItem, Document, Entity, EntityUpdate, Extraction, Meeting, Vote,
)
from councilhound.entities import add_alias, resolve_entity
from councilhound.extraction.llm_structure import apply_extraction


def _make_meeting(session, clip_id, date):
    meeting = Meeting(
        granicus_clip_id=clip_id, granicus_view_id="13", body="city_council",
        meeting_type="council_regular", meeting_date=date,
        title="City Council Regular Meeting", status="fetched",
    )
    session.add(meeting)
    session.flush()
    session.add(Document(meeting_id=meeting.id, doc_type="minutes",
                         source_url=f"https://x/minutes/{clip_id}", raw_text="minutes text"))
    session.flush()
    return meeting


EXTRACTION_1 = {
    "summary": "Council discussed the trail project.",
    "agenda_items": [
        {
            "label": "7a",
            "title": "George Snyder Trail — design contract",
            "outcome": "Motion approved 5-1.",
            "votes": [{
                "description": "Approve the design contract",
                "motion_result": "passed",
                "vote_breakdown": {"Read": "yes", "Bates": "yes", "Hall": "no"},
            }],
            "entities": [{
                "entity_type": "project",
                "name": "George Snyder Trail",
                "role": "subject",
                "update_text": "Design contract approved.",
                "status_after": "in_progress",
            }, {
                "entity_type": "person",
                "name": "Mayor Read",
                "role": "sponsor",
                "update_text": "Mayor Read sponsored the motion.",
            }],
        },
    ],
}

EXTRACTION_2 = {
    "summary": "Trail project completed.",
    "agenda_items": [
        {
            "label": "4",
            "title": "George Snyder Trail — ribbon cutting",
            "outcome": "Announced completion.",
            "votes": [],
            "entities": [{
                "entity_type": "project",
                "name": "the George Snyder Trail",  # different surface form
                "role": "subject",
                "update_text": "Project completed; ribbon cutting scheduled.",
                "status_after": "completed",
            }],
        },
    ],
}


def _counts(session):
    return {
        "items": session.scalar(select(func.count(AgendaItem.id))),
        "votes": session.scalar(select(func.count(Vote.id))),
        "updates": session.scalar(select(func.count(EntityUpdate.id))),
        "entities": session.scalar(select(func.count(Entity.id))),
    }


def test_apply_is_idempotent(db_session):
    s = db_session
    meeting = _make_meeting(s, "100", datetime.date(2025, 1, 7))
    # seeded person, as seed-entities would create it
    mayor = resolve_entity(s, "person", "Catherine S. Read")
    add_alias(s, mayor, "Mayor Read")

    apply_extraction(s, meeting, EXTRACTION_1)
    s.commit()
    first = _counts(s)
    assert first["items"] == 1 and first["votes"] == 1 and first["updates"] == 2

    apply_extraction(s, meeting, EXTRACTION_1)
    s.commit()
    assert _counts(s) == first  # re-run converges, nothing duplicated

    # "Mayor Read" resolved to the seeded person, no new person entity
    people = s.scalars(select(Entity).where(Entity.entity_type == "person")).all()
    assert len(people) == 1 and people[0].canonical_slug == "catherine-read"


def test_timeline_across_meetings_and_status_rollup(db_session):
    s = db_session
    m1 = _make_meeting(s, "101", datetime.date(2025, 1, 7))
    m2 = _make_meeting(s, "102", datetime.date(2025, 6, 3))

    apply_extraction(s, m1, EXTRACTION_1)
    apply_extraction(s, m2, EXTRACTION_2)
    s.commit()

    # one project entity despite different surface forms
    projects = s.scalars(select(Entity).where(Entity.entity_type == "project")).all()
    assert len(projects) == 1
    trail = projects[0]
    assert trail.canonical_slug == "george-snyder-trail"

    updates = s.execute(
        select(EntityUpdate, Meeting.meeting_date)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .where(EntityUpdate.entity_id == trail.id)
        .order_by(Meeting.meeting_date)
    ).all()
    assert len(updates) == 2
    assert updates[0][0].status_after == "in_progress"
    assert updates[1][0].status_after == "completed"
    # every update cites its meeting; mention rows cite the minutes doc
    assert all(u.meeting_id in (m1.id, m2.id) for u, _ in updates)

    assert trail.current_status == "completed"

    # re-applying meeting 1 later must not regress the rollup
    apply_extraction(s, m1, EXTRACTION_1)
    s.commit()
    s.refresh(trail)
    assert trail.current_status == "completed"


def test_prompt_includes_known_entities(db_session):
    from councilhound.db.models import Entity, Meeting
    from councilhound.extraction.llm_structure import _build_prompt, _known_entities

    s = db_session
    m = Meeting(granicus_clip_id="900", granicus_view_id="13", body="city_council",
                meeting_type="council_meeting", meeting_date="2026-06-01",
                title="City Council Meeting", status="fetched")
    s.add(m)
    s.add(Entity(entity_type="project", name="Courthouse Plaza",
                 canonical_slug="courthouse-plaza"))
    s.add(Entity(entity_type="topic", name="Urban Agriculture",
                 canonical_slug="urban-agriculture"))
    s.flush()

    texts = {"agenda": "Public hearing on the Courthouse Plaza redevelopment plan."}
    known = _known_entities(s, texts)
    assert known == ["Courthouse Plaza"]  # urban agriculture isn't mentioned

    prompt = _build_prompt(m, texts, known)
    assert "ALREADY-TRACKED ENTITIES" in prompt
    assert "- Courthouse Plaza" in prompt
    # candidates come before the documents so the model reads them first
    assert prompt.index("ALREADY-TRACKED") < prompt.index("=== AGENDA ===")

    assert "ALREADY-TRACKED" not in _build_prompt(m, texts, [])


EXTRACTION_WITH_COMMENTS = {
    "summary": "Budget adopted; vape shops raised in comments.",
    "agenda_items": [
        {
            "label": "3e",
            "title": "Consideration and appropriation of the FY 2026 Budget",
            "outcome": "Adopted 4-3.",
            "votes": [{"description": "Adopt the budget", "motion_result": "passed",
                       "vote_breakdown": {"Read": "yes", "Hall": "no"}}],
            "entities": [
                {"entity_type": "topic", "name": "FY 2026 Budget", "role": "subject",
                 "update_text": "Budget adopted.", "status_after": "approved"},
                # a remark an older extraction filed under the last item
                {"entity_type": "topic", "name": "Vape Shop Proximity Restrictions", "role": "subject",
                 "update_text": "During council comments, Councilmember McQuillen raised vape shops near schools."},
            ],
        },
        {
            "label": "11",
            "title": "Council Comments and Committee reports out",
            "outcome": "Comments heard.",
            "votes": [],
            "entities": [{"entity_type": "topic", "name": "GIS Day", "role": "subject",
                          "update_text": "During council comments, Rice reported on GIS Day."}],
        },
    ],
    "other_discussion": [
        {"entity_type": "project", "name": "Old Town Splash Pad", "period": "reports",
         "update_text": "The City Manager reported the splash pad opens in June."},
    ],
}


def test_comment_period_remarks_do_not_join_an_item(db_session):
    """A remark from a comments or reports period lands on the meeting, not
    on an item: from the other_discussion bucket, or unfiled from the last
    item on re-apply of an older extraction. A remark under the agenda's own
    comments item stays there."""
    s = db_session
    meeting = _make_meeting(s, "4191", datetime.date(2025, 5, 6))
    apply_extraction(s, meeting, EXTRACTION_WITH_COMMENTS)
    s.commit()

    def update_for(slug):
        e = s.scalar(select(Entity).where(Entity.canonical_slug == slug))
        return s.scalar(select(EntityUpdate).where(EntityUpdate.entity_id == e.id))

    budget_item = s.scalar(select(AgendaItem).where(AgendaItem.label == "3e"))
    comments_item = s.scalar(select(AgendaItem).where(AgendaItem.label == "11"))
    assert update_for("fy-2026-budget").agenda_item_id == budget_item.id
    vape = update_for("vape-shop-proximity-restrictions")
    assert vape.agenda_item_id is None and vape.update_text.startswith("[comments] ")
    splash = update_for("old-town-splash-pad")
    assert splash.agenda_item_id is None and splash.update_text.startswith("[reports] ")
    assert update_for("gis-day").agenda_item_id == comments_item.id
    # the schema advertises the bucket and the prompt says how to use it
    from councilhound.extraction.llm_structure import EXTRACTION_TOOL, SYSTEM_PROMPT
    assert "other_discussion" in EXTRACTION_TOOL["input_schema"]["properties"]
    assert "other_discussion" in SYSTEM_PROMPT


def test_votes_need_minutes_or_an_actions_report(db_session):
    """With only an agenda (and packet) on file, the model has recorded the
    packet's sample motions as passed votes. Votes are dropped unless a
    minutes or actions-report document with text exists; the item and its
    outcome text stay."""
    meeting = Meeting(
        granicus_clip_id="4646", granicus_view_id="13", body="planning_commission",
        meeting_type="planning_commission", meeting_date=datetime.date(2026, 7, 27),
        title="Planning Commission Regular Meeting/Work Session", status="fetched",
    )
    db_session.add(meeting)
    db_session.flush()
    db_session.add(Document(meeting_id=meeting.id, doc_type="agenda",
                            source_url="https://x/agenda/4646", raw_text="agenda text"))
    db_session.flush()

    apply_extraction(db_session, meeting, EXTRACTION_1)
    assert db_session.scalar(select(func.count(Vote.id))) == 0
    assert db_session.scalar(select(func.count(AgendaItem.id))) == 1

    # minutes arrive later: the re-apply keeps the votes
    db_session.add(Document(meeting_id=meeting.id, doc_type="minutes",
                            source_url="https://x/minutes/4646", raw_text="minutes text"))
    db_session.flush()
    apply_extraction(db_session, meeting, EXTRACTION_1)
    assert db_session.scalar(select(func.count(Vote.id))) == 1


def test_city_and_its_bodies_are_never_entities(db_session):
    """PRAB agendas carry "Stakeholder Updates: Planning Commission – Matt
    Rice; School Board – Amit Hickman", and the model turned the bodies and
    the city into topics. Those names are skipped in items and in the
    other_discussion bucket alike; real topics on the same item survive."""
    meeting = _make_meeting(db_session, "4642", datetime.date(2026, 9, 10))
    data = {
        "summary": "Parks board stakeholder updates.",
        "agenda_items": [{
            "label": "6",
            "title": "Stakeholder Updates",
            "outcome": "Updates received.",
            "votes": [],
            "entities": [
                {"entity_type": "topic", "name": "Planning Commission", "role": "subject",
                 "update_text": "Matt Rice reported on the commission's work."},
                {"entity_type": "topic", "name": "the City of Fairfax School Board", "role": "subject",
                 "update_text": "Amit Hickman reported for the board."},
                {"entity_type": "location", "name": "City of Fairfax", "role": "location",
                 "update_text": "Citywide."},
                {"entity_type": "project", "name": "Van Dyck Park Playground", "role": "subject",
                 "update_text": "Playground replacement is out to bid.", "status_after": "in_progress"},
            ],
        }],
        "other_discussion": [
            {"entity_type": "topic", "name": "Fairfax City Council", "period": "member_comments",
             "update_text": "Council adopted the budget."},
            {"entity_type": "topic", "name": "Native Planting Program", "period": "member_comments",
             "update_text": "A member proposed native plantings at the park."},
        ],
    }
    apply_extraction(db_session, meeting, data)
    names = sorted(db_session.scalars(select(Entity.name)))
    assert names == ["Native Planting Program", "Van Dyck Park Playground"]
    assert db_session.scalar(select(func.count(EntityUpdate.id))) == 2


def test_structure_pending_skips_meetings_without_agenda_text(db_session, monkeypatch):
    """A recording-only swearing-in (no agenda document) or a closed meeting
    whose agenda has no text yet cannot be structured; retrying them every
    hour only produced tracebacks. They are not candidates until the agenda
    has text, at which point they are picked up like any other meeting."""
    from councilhound.extraction import llm_structure

    s = db_session
    no_agenda = _make_meeting(s, "4048", datetime.date(2025, 1, 13))
    untexted = _make_meeting(s, "4364", datetime.date(2025, 10, 23))
    s.add(Document(meeting_id=untexted.id, doc_type="agenda",
                   source_url="https://x/agenda/4364", local_path="/tmp/agenda.bin"))
    ready = _make_meeting(s, "4646", datetime.date(2026, 8, 18))
    s.add(Document(meeting_id=ready.id, doc_type="agenda",
                   source_url="https://x/agenda/4646", raw_text="1. Call to order"))
    s.commit()

    structured = []

    def fake_structure(session, meeting, force=False):
        structured.append(meeting.granicus_clip_id)
        session.add(Extraction(meeting_id=meeting.id, model="fake", raw_json={},
                               prompt_version=llm_structure.PROMPT_VERSION))
        session.commit()

    monkeypatch.setattr(llm_structure, "structure_meeting", fake_structure)
    monkeypatch.setattr(llm_structure, "late_document_meetings", lambda session: [])

    result = llm_structure.structure_pending(s)
    assert structured == ["4646"]
    assert result == {"structured": 1, "restructured": 0, "failed": 0, "candidates": 1}

    # once the Word agenda has been read, the closed meeting becomes a candidate
    doc = s.scalar(select(Document).where(Document.source_url == "https://x/agenda/4364"))
    doc.raw_text = "School Board Closed Meeting Agenda"
    s.commit()
    structured.clear()
    llm_structure.structure_pending(s)
    assert structured == ["4364"]
    assert no_agenda.granicus_clip_id not in structured
