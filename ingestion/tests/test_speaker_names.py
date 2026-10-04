import datetime

import pytest
from sqlalchemy import select

from councilhound.db.models import (
    AgendaItem, Entity, EntityAlias, Meeting, MeetingSpeaker, TranscriptChunk, Vote,
)
from councilhound.extraction import speaker_names as sn


def _meeting(s, day=22, body="city_council", clip="4655"):
    m = Meeting(granicus_view_id="13", granicus_clip_id=clip, body=body,
                meeting_type="council_meeting", title="City Council Meeting",
                meeting_date=datetime.date(2026, 9, day))
    s.add(m)
    s.flush()
    return m


def _person(s, name, slug, *aliases):
    p = Entity(entity_type="person", name=name, canonical_slug=slug)
    s.add(p)
    s.flush()
    s.add_all(EntityAlias(entity_id=p.id, alias=a) for a in aliases)
    return p


def _chunks(s, m, rows):
    s.add_all(TranscriptChunk(meeting_id=m.id, start_seconds=t, end_seconds=t + 5, text=text,
                              speaker_label=label) for t, label, text in rows)
    s.flush()


@pytest.fixture
def council(db_session):
    """The mayor calls on Amos; a public commenter introduces herself."""
    s = db_session
    m = _meeting(s)
    read = _person(s, "Catherine Read", "catherine-read", "Mayor Read")
    amos = _person(s, "Anthony Amos", "anthony-amos", "Councilmember Amos")
    _person(s, "Pat Amos", "pat-amos")  # unrelated namesake, no title
    item = AgendaItem(meeting_id=m.id, label="7a", title="Public hearing")
    s.add(item)
    s.flush()
    s.add(Vote(meeting_id=m.id, agenda_item_id=item.id, description="motion",
               vote_breakdown={"Amos": "yes"}))
    _chunks(s, m, [
        (0, "SPEAKER_05", "Good evening. I call the meeting to order."),
        (6534, "SPEAKER_05", "Thank you. Councilmember Amos."),
        (6537, "SPEAKER_16", "I only have a couple of questions for staff."),
        (6600, "SPEAKER_25", "Good evening. My name is Joan Goodman."),
        (6700, "SPEAKER_19", "And big smile."),
    ])
    s.commit()
    return m, read, amos


def test_roster_has_voters_and_the_mayor_not_untitled_namesakes(db_session, council):
    m, read, amos = council
    people = sn.roster(db_session, m)
    assert set(people) == {"catherine-read", "anthony-amos"}
    assert people["anthony-amos"]["entity_id"] == amos.id


def test_verify_evidence_needs_the_quote_near_the_labels_own_turn(db_session, council):
    m, *_ = council
    chunks = db_session.scalars(select(TranscriptChunk).order_by(TranscriptChunk.start_seconds)).all()
    good = {"time": "1:48:54", "quote": "Councilmember Amos."}
    assert sn.verify_evidence("SPEAKER_16", [good], chunks) == [good]
    # right quote, but nowhere near this label's turns
    assert sn.verify_evidence("SPEAKER_16", [{"time": "0:00:00", "quote": "I call the meeting"}], chunks) == []
    # invented quote
    assert sn.verify_evidence("SPEAKER_16", [{"time": "1:48:54", "quote": "Thank you, Mr. Amos"}], chunks) == []


def test_name_meeting_publishes_only_verified_high_confidence(db_session, council, monkeypatch):
    m, read, amos = council
    answer = [
        {"label": "SPEAKER_05", "name": "Catherine Read", "slug": "catherine-read",
         "role": "presiding officer", "confidence": "high", "mixed": False,
         "evidence": [{"time": "0:00:00", "quote": "I call the meeting to order"}]},
        {"label": "SPEAKER_16", "name": "Anthony Amos", "slug": "anthony-amos", "role": "member",
         "confidence": "high", "mixed": False,
         "evidence": [{"time": "1:48:54", "quote": "Councilmember Amos."}]},
        # high, but the quote isn't in the transcript: downgraded, not shown
        {"label": "SPEAKER_25", "name": "Joan Goodman", "slug": "joan-goodman",
         "role": "public commenter", "confidence": "high", "mixed": False,
         "evidence": [{"time": "1:50:00", "quote": "I am Joan Goodman of Fairfax"}]},
        # SPEAKER_19 left out by the model; a label not in the meeting is ignored
        {"label": "SPEAKER_99", "name": "Nobody", "slug": None, "role": "other",
         "confidence": "high", "mixed": False, "evidence": []},
    ]
    monkeypatch.setattr(sn, "_call_claude", lambda prompt: (answer, "claude-opus-5-5"))
    r = sn.name_meeting(db_session, m)
    assert r["public"] == 2 and r["downgraded"] == 1 and r["labels"] == 4

    rows = {row.speaker_label: row for row in db_session.scalars(select(MeetingSpeaker))}
    assert set(rows) == {"SPEAKER_05", "SPEAKER_16", "SPEAKER_19", "SPEAKER_25"}
    assert rows["SPEAKER_25"].confidence == "medium" and rows["SPEAKER_25"].entity_id is None
    assert rows["SPEAKER_19"].confidence == "low" and rows["SPEAKER_19"].name is None
    assert rows["SPEAKER_16"].entity_id == amos.id
    links = dict(db_session.execute(select(TranscriptChunk.speaker_label, TranscriptChunk.speaker_entity_id)).all())
    assert links["SPEAKER_16"] == amos.id and links["SPEAKER_05"] == read.id
    assert links["SPEAKER_25"] is None


def test_manual_rows_survive_a_rerun(db_session, council, monkeypatch):
    m, *_ = council
    sn.set_speaker(db_session, m, "SPEAKER_19", "Melanie Shinneberry", role="clerk")
    answer = [{"label": "SPEAKER_19", "name": "Someone Else", "slug": None, "role": "other",
               "confidence": "high", "mixed": False,
               "evidence": [{"time": "1:51:40", "quote": "And big smile."}]}]
    monkeypatch.setattr(sn, "_call_claude", lambda prompt: (answer, "claude-opus-5-5"))
    sn.name_meeting(db_session, m)
    row = db_session.scalar(select(MeetingSpeaker).where(MeetingSpeaker.speaker_label == "SPEAKER_19"))
    assert (row.name, row.source, sn.is_public(row)) == ("Melanie Shinneberry", "manual", True)


def test_set_speaker_by_slug_links_chunks(db_session, council):
    m, read, amos = council
    sn.set_speaker(db_session, m, "SPEAKER_16", None, slug="anthony-amos", role="member")
    linked = db_session.scalars(select(TranscriptChunk.speaker_entity_id)
                                .where(TranscriptChunk.speaker_label == "SPEAKER_16")).all()
    assert linked == [amos.id]
    with pytest.raises(ValueError):
        sn.set_speaker(db_session, m, "SPEAKER_16", None, slug="no-such-person")


def test_pending_respects_the_lookback_window(db_session, council):
    m, *_ = council
    old = _meeting(db_session, day=1, clip="4641")
    _chunks(db_session, old, [(0, "SPEAKER_00", "Hello.")])
    db_session.commit()
    assert [x.id for x in sn.pending(db_session)] == [m.id, old.id]
    assert [x.id for x in sn.pending(db_session, since=datetime.date(2026, 9, 15))] == [m.id]


def test_roster_falls_back_to_body_titles_without_votes(db_session):
    """A Planning Commission meeting before its minutes has no votes."""
    m = _meeting(db_session, body="planning_commission", clip="4649")
    feather = _person(db_session, "James Feather", "james-feather", "Commissioner Feather", "Chair Feather")
    _person(db_session, "Billy Bates", "billy-bates", "Councilmember Bates")  # other body
    db_session.commit()
    assert set(sn.roster(db_session, m)) == {"james-feather"}
    assert sn.roster(db_session, m)["james-feather"]["entity_id"] == feather.id


def test_name_attested_requires_the_spoken_name():
    words = set("i am going to recognize brian lovegerman our city attorney ms shinneberry".split())
    assert sn.name_attested("Brian Lovegerman", words)
    assert sn.name_attested("Melanie Shinneberry", words) is False  # first name never spoken
    assert sn.name_attested("Ms. Shineberry", words)  # small spelling drift is fine
    assert sn.name_attested("Brian Lubkin", words) is False  # outside knowledge, not the transcript
    assert sn.name_attested("Dr. A", words) is False


def test_unattested_non_roster_names_are_not_public(db_session, council, monkeypatch):
    m, *_ = council
    answer = [{"label": "SPEAKER_25", "name": "Joan Goodwin-Smith", "slug": None,
               "role": "public commenter", "confidence": "high", "mixed": False,
               "evidence": [{"time": "1:50:00", "quote": "My name is Joan Goodman."}]}]
    monkeypatch.setattr(sn, "_call_claude", lambda prompt: (answer, "claude-opus-5-5"))
    r = sn.name_meeting(db_session, m)
    assert r["unattested"] == 1 and r["public"] == 0


@pytest.mark.parametrize("text, student", [
    ("Hello, my name is Veronica, and I'm a junior at Fairfax High School.", True),
    ("Hi, I'm Leanne. I am a sophomore at Fairfax High School", True),
    ("I'm a student at George Mason", True),
    ("our student representative for his first report, Mr. Kevin Murray", False),  # cue-only rule
    ("I'm in the 8th grade", True),
    ("I'm a senior planner with the City of Fairfax", False),
    ("I'm a senior at heart and I've lived here 40 years", True),  # rare false positive: hidden, not misnamed
    ("I am a retired teacher at Lanier", False),
])
def test_student_pattern(text, student):
    assert bool(sn._STUDENT.search(text)) is student


def test_mark_students_hides_names_but_keeps_them(db_session, council, monkeypatch):
    m, *_ = council
    _chunks(db_session, m, [(6800, "SPEAKER_30", "Hello, I'm Olivia and I'm a sophomore at Fairfax High.")])
    db_session.commit()
    answer = [{"label": "SPEAKER_30", "name": "Olivia", "slug": None, "role": "public commenter",
               "confidence": "high", "mixed": False,
               "evidence": [{"time": "1:53:20", "quote": "Hello, I'm Olivia"}]}]
    monkeypatch.setattr(sn, "_call_claude", lambda prompt: (answer, "claude-opus-5-5"))
    r = sn.name_meeting(db_session, m)
    assert r["students"] == 1 and r["public"] == 0
    row = db_session.scalar(select(MeetingSpeaker).where(MeetingSpeaker.speaker_label == "SPEAKER_30"))
    assert (row.name, row.role, sn.is_public(row), sn.is_student(row)) == ("Olivia", "student", False, True)


def test_chair_introducing_the_student_rep_is_not_a_student(db_session, council, monkeypatch):
    m, *_ = council
    _chunks(db_session, m, [
        (7000, "SPEAKER_06", "Next we'll hear from our student representative, Mr. Kevin Murray."),
        (7010, "SPEAKER_17", "Thank you. This month at Fairfax High we held homecoming."),
    ])
    db_session.commit()
    answer = [
        {"label": "SPEAKER_06", "name": "Carolyn Pitches", "slug": None, "role": "presiding officer",
         "confidence": "high", "mixed": False,
         "evidence": [{"time": "1:56:40", "quote": "Next we'll hear from our student representative"}]},
        {"label": "SPEAKER_17", "name": "Kevin Murray", "slug": None, "role": "other",
         "confidence": "high", "mixed": False,
         "evidence": [{"time": "1:56:40", "quote": "our student representative, Mr. Kevin Murray"}]},
    ]
    monkeypatch.setattr(sn, "_call_claude", lambda prompt: (answer, "claude-opus-5-5"))
    sn.name_meeting(db_session, m)
    roles = dict(db_session.execute(select(MeetingSpeaker.speaker_label, MeetingSpeaker.role)).all())
    # both cue quotes contain the phrase; only the one spoken by someone else counts
    assert roles["SPEAKER_17"] == "student"
    assert roles["SPEAKER_06"] == "presiding officer"
