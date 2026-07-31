"""The late-document re-extraction trigger.

Minutes are approved at the NEXT meeting and the actions report posts a day
or two after, so the nightly job routinely structures a fresh meeting from
its agenda alone — honestly recording "no votes" — and then never revisited
it when the decision documents arrived. The July 28, 2026 council meeting sat
on the homepage with zero votes while its actions report (with a 4-2 zoning
vote) was already in the database.
"""
import datetime as dt

from councilhound.db.models import Document, Extraction, Meeting
from councilhound.extraction import llm_structure
from councilhound.extraction.llm_structure import (PROMPT_VERSION,
                                                   late_document_meetings,
                                                   structure_pending)


def _meeting(s, date=dt.date(2026, 7, 28), clip="4623"):
    m = Meeting(body="city_council", meeting_type="council_meeting",
                meeting_date=date, title="City Council Meeting",
                granicus_clip_id=clip, granicus_view_id="11",
                status="extracted")
    s.add(m)
    s.flush()
    return m


def _extraction(s, meeting, created_at):
    e = Extraction(meeting_id=meeting.id, prompt_version=PROMPT_VERSION,
                   raw_json={"agenda_items": []})
    s.add(e)
    s.flush()
    e.created_at = created_at
    s.flush()
    return e


def _doc(s, meeting, doc_type, fetched_at, raw_text="Approved, 4-2, ..."):
    d = Document(meeting_id=meeting.id, doc_type=doc_type,
                 source_url=f"https://example/{doc_type}/{meeting.id}",
                 raw_text=raw_text, fetched_at=fetched_at)
    s.add(d)
    s.flush()
    return d


T0 = dt.datetime(2026, 7, 29, 3, 0, tzinfo=dt.timezone.utc)   # nightly extract
T1 = dt.datetime(2026, 7, 30, 3, 0, tzinfo=dt.timezone.utc)   # next night


def test_actions_report_arriving_after_extraction_triggers(db_session):
    m = _meeting(db_session)
    _extraction(db_session, m, created_at=T0)
    _doc(db_session, m, "actions_report", fetched_at=T1)
    db_session.commit()
    assert [x.id for x in late_document_meetings(db_session)] == [m.id]


def test_documents_present_at_extraction_time_do_not_trigger(db_session):
    m = _meeting(db_session)
    _doc(db_session, m, "actions_report", fetched_at=T0 - dt.timedelta(hours=1))
    _extraction(db_session, m, created_at=T0)
    db_session.commit()
    assert late_document_meetings(db_session) == []


def test_late_document_without_text_does_not_trigger(db_session):
    """A scanned or unfetchable document must not re-fire nightly — the
    trigger waits until text extraction has something to offer."""
    m = _meeting(db_session)
    _extraction(db_session, m, created_at=T0)
    _doc(db_session, m, "actions_report", fetched_at=T1, raw_text=None)
    db_session.commit()
    assert late_document_meetings(db_session) == []


def test_late_agenda_item_pdf_does_not_trigger(db_session):
    """Only decision documents (minutes/actions report) warrant a re-run;
    packet attachments arrive late all the time and change nothing."""
    m = _meeting(db_session)
    _extraction(db_session, m, created_at=T0)
    _doc(db_session, m, "agenda_item_pdf", fetched_at=T1)
    db_session.commit()
    assert late_document_meetings(db_session) == []


def test_structure_pending_reextracts_and_rearms_only_once(db_session, monkeypatch):
    """The end-to-end loop: the trigger fires, structure_meeting(force=True)
    runs, the refreshed extraction timestamp disarms the trigger."""
    m = _meeting(db_session)
    _extraction(db_session, m, created_at=T0)
    _doc(db_session, m, "actions_report", fetched_at=T1)
    # a second, already-current meeting must not be touched
    other = _meeting(db_session, date=dt.date(2026, 7, 14), clip="4599")
    _doc(db_session, other, "actions_report", fetched_at=T0 - dt.timedelta(days=1))
    _extraction(db_session, other, created_at=T0)
    db_session.commit()

    forced = []

    def fake_structure(session, meeting, force=False, reapply_only=False):
        forced.append((meeting.id, force))
        ext = session.scalar(
            llm_structure.select(Extraction).where(Extraction.meeting_id == meeting.id))
        ext.created_at = dt.datetime.now(dt.timezone.utc)
        session.commit()
        return ext

    monkeypatch.setattr(llm_structure, "structure_meeting", fake_structure)
    result = structure_pending(db_session)
    assert result["restructured"] == 1
    assert forced == [(m.id, True)]
    # trigger is disarmed: a second nightly pass does nothing
    forced.clear()
    result = structure_pending(db_session)
    assert result["restructured"] == 0
    assert forced == []
