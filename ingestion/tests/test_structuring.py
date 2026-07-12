"""Phase 3 apply/resolution tests — no LLM involved; extraction dicts are
synthetic. Proves the PLAN.md definition of done: re-runs converge to the
same rows, and an entity discussed at two meetings has an ordered timeline
with the latest status rolled up."""
import datetime

from sqlalchemy import func, select

from councillens.db.models import (
    AgendaItem, Document, Entity, EntityUpdate, Meeting, Vote,
)
from councillens.entities import add_alias, resolve_entity
from councillens.extraction.llm_structure import apply_extraction


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
