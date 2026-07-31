"""The council-packet bridge: staff reports reaching the spec extractor.

The project-directory scraper only collects the applicant's own submissions, so
the city staff report — which carries staff's independent fiscal estimate and
the program council actually voted on — was absent from every spec corpus even
though the meeting pipeline had already ingested and text-extracted it.
"""
import datetime as dt

import pytest

from councilhound.db.models import (AgendaItem, CityProject, Document, Entity,
                                    EntityMention, Meeting)
from councilhound.impact.intake.documents import gather_meeting_documents


@pytest.fixture
def session(db_session):
    return db_session


def _meeting(s, date, external_id):
    m = Meeting(body="city_council", meeting_type="council_regular",
                meeting_date=date, title=f"Meeting {external_id}",
                granicus_clip_id=external_id, granicus_view_id="1")
    s.add(m)
    s.flush()
    return m


def _doc(s, meeting, title, text, doc_type="agenda_item_pdf"):
    d = Document(meeting_id=meeting.id, doc_type=doc_type, title=title,
                 source_url=f"https://example/doc/{title}/{meeting.id}",
                 raw_text=text)
    s.add(d)
    s.flush()
    return d


def _project(s, name="City Centre West", entity=True):
    ent = None
    if entity:
        ent = Entity(entity_type="project", name=name,
                     canonical_slug=name.lower().replace(" ", "-").replace("%", ""))
        s.add(ent)
        s.flush()
    p = CityProject(external_slug="City-Centre-West", name=name,
                    detail_url="https://example/project",
                    address="10501 Main Street",
                    entity_id=ent.id if ent else None)
    s.add(p)
    s.flush()
    return p


def test_packet_found_by_project_name_without_any_mention_rows(session):
    """The mention pipeline reads agendas/minutes only — it never links entities
    from packet PDFs — so a project can have a staff report in the corpus and no
    mention rows at all. Name matching is what makes the bridge work anyway."""
    m = _meeting(session, dt.date(2026, 7, 11), "m1")
    _doc(session, m, "Staff Report",
         "FISCAL IMPACT: the anticipated fiscal impact estimate for City Centre "
         "West ranges from $543,000 and $741,000 annually.")
    _doc(session, m, "Unrelated Item", "A resolution about street trees.")
    project = _project(session)
    session.commit()

    docs = gather_meeting_documents(session, project)
    assert len(docs) == 1
    assert "Staff Report" in docs[0].label
    assert "543,000" in docs[0].text


def test_agenda_item_title_match_ranks_first(session):
    m = _meeting(session, dt.date(2026, 7, 11), "m1")
    item = AgendaItem(meeting_id=m.id, title="City Centre West Rezoning",
                      label="8a")
    session.add(item)
    session.flush()
    # mentions the project only obliquely, but IS the packet entry for the item
    _doc(session, m, "City Centre West Rezoning", "Attachment set for the item.")
    _doc(session, m, "Other Attachment",
         "Background mentioning City Centre West once.")
    project = _project(session)
    session.add(EntityMention(entity_id=project.entity_id, meeting_id=m.id,
                              agenda_item_id=item.id, role="discussed"))
    session.commit()

    docs = gather_meeting_documents(session, project)
    assert docs[0].label.startswith("Council packet: City Centre West Rezoning")


def test_unrelated_documents_are_excluded(session):
    m = _meeting(session, dt.date(2026, 7, 11), "m1")
    _doc(session, m, "Staff Report", "A resolution about refuse collection fees.")
    project = _project(session)
    session.commit()
    assert gather_meeting_documents(session, project) == []


def test_cap_limits_the_corpus(session):
    m = _meeting(session, dt.date(2026, 7, 11), "m1")
    for i in range(12):
        _doc(session, m, f"Attachment {i}",
             "Staff report discussing City Centre West at length.")
    project = _project(session)
    session.commit()
    assert len(gather_meeting_documents(session, project, max_docs=3)) == 3


def test_newest_first_within_equal_relevance(session):
    old = _meeting(session, dt.date(2026, 5, 1), "m-old")
    new = _meeting(session, dt.date(2026, 7, 11), "m-new")
    _doc(session, old, "Staff Report", "City Centre West background.")
    _doc(session, new, "Staff Report", "City Centre West background.")
    project = _project(session)
    session.commit()
    docs = gather_meeting_documents(session, project)
    assert "2026-07-11" in docs[0].label


def test_project_without_entity_still_matches_by_name(session):
    m = _meeting(session, dt.date(2026, 7, 11), "m1")
    _doc(session, m, "Staff Report", "Report on City Centre West.")
    project = _project(session, entity=False)
    session.commit()
    assert len(gather_meeting_documents(session, project)) == 1


def test_like_metacharacters_in_a_project_name_do_not_widen_the_match(session):
    m = _meeting(session, dt.date(2026, 7, 11), "m1")
    _doc(session, m, "Staff Report", "A report about something else entirely.")
    project = _project(session, name="100% Affordable_Housing")
    session.commit()
    # "_" and "%" would match any character / any run in a raw LIKE pattern
    assert gather_meeting_documents(session, project) == []


def test_no_session_returns_nothing(session):
    project = _project(session)
    session.commit()
    assert gather_meeting_documents(None, project) == []
