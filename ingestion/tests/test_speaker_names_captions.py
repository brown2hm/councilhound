"""Naming caption turns: the County's captions mark each change of speaker
('>>'), so labels are turns, one person speaks under many of them, and
each turn is named from the cue next to it."""
import datetime

from sqlalchemy import select

from councilhound.db.models import (
    AgendaItem, Entity, EntityAlias, Meeting, MeetingSpeaker, TranscriptChunk, Vote,
)
from councilhound.extraction import speaker_names as sn


def _board_meeting(s):
    m = Meeting(granicus_view_id="7", granicus_clip_id="4241", body="board_of_supervisors",
                meeting_type="bos_meeting", title="Board of Supervisors Meeting",
                meeting_date=datetime.date(2026, 9, 15))
    s.add(m)
    s.flush()
    lusk = Entity(entity_type="person", name="Rodney L. Lusk", canonical_slug="rodney-lusk")
    mckay = Entity(entity_type="person", name="Jeffrey C. McKay", canonical_slug="jeffrey-mckay")
    s.add_all([lusk, mckay])
    s.flush()
    s.add_all([EntityAlias(entity_id=lusk.id, alias="Supervisor Lusk"),
               EntityAlias(entity_id=mckay.id, alias="Chairman McKay")])
    item = AgendaItem(meeting_id=m.id, label="1", title="Presentations")
    s.add(item)
    s.flush()
    s.add(Vote(meeting_id=m.id, agenda_item_id=item.id, description="motion",
               vote_breakdown={"Lusk": "yes", "McKay": "yes"}))
    s.add_all(TranscriptChunk(meeting_id=m.id, start_seconds=t, end_seconds=t + 5, text=text,
                              speaker_label=label) for t, label, text in [
        (5, "TURN_0001", "Good morning, everyone. And welcome to our board meeting."),
        (600, "TURN_0002", "Thank you. Supervisor Lusk."),
        (603, "TURN_0003", "Thank you, Mr. Chairman. I want to recognize our recruits."),
        (700, "TURN_0004", "Thank you. Next item."),
        (900, "TURN_0005", "Good morning. My name is Dana Ortiz and I live in Mason."),
    ])
    s.commit()
    return m, lusk


def test_caption_labels_are_recognized_as_turns():
    assert sn.is_caption_turns(["TURN_0001", "TURN_0002"])
    assert not sn.is_caption_turns(["SPEAKER_05"])
    assert not sn.is_caption_turns(["TURN_0001", "SPEAKER_05"])
    assert not sn.is_caption_turns([])


def test_caption_prompt_counts_turns_instead_of_listing_them(db_session):
    m, _ = _board_meeting(db_session)
    chunks = db_session.scalars(select(TranscriptChunk).where(TranscriptChunk.meeting_id == m.id)
                                .order_by(TranscriptChunk.start_seconds)).all()
    labels = sorted({c.speaker_label for c in chunks})
    prompt = sn._prompt(m, sn.roster(db_session, m), [], chunks, labels)
    assert "5 caption turns, TURN_0001 to TURN_0005; name only those you can." in prompt
    assert "SPEAKER LABELS TO IDENTIFY" not in prompt
    assert "[00:10:03] TURN_0003: Thank you, Mr. Chairman." in prompt or "TURN_0003: Thank you, Mr. Chairman." in prompt


def test_name_meeting_names_turns_from_the_cue_beside_them(db_session, monkeypatch):
    m, lusk = _board_meeting(db_session)
    calls = []

    def fake(prompt, captions=False):
        calls.append(captions)
        return ([
            # called on in the turn just before: high, and verifiable
            {"label": "TURN_0003", "name": "Rodney L. Lusk", "slug": "rodney-lusk", "role": "member",
             "confidence": "high", "mixed": False,
             "evidence": [{"time": "0:10:00", "quote": "Thank you. Supervisor Lusk."}]},
            {"label": "TURN_0005", "name": "Dana Ortiz", "slug": None, "role": "public commenter",
             "confidence": "high", "mixed": False,
             "evidence": [{"time": "0:15:00", "quote": "My name is Dana Ortiz"}]},
        ], "claude-opus-5-5")

    monkeypatch.setattr(sn, "_call_claude", fake)
    result = sn.name_meeting(db_session, m)
    assert calls == [True]  # the caption prompt and budget
    assert result["labels"] == 5 and result["public"] == 2
    rows = {r.speaker_label: r for r in db_session.scalars(
        select(MeetingSpeaker).where(MeetingSpeaker.meeting_id == m.id))}
    assert rows["TURN_0003"].entity_id == lusk.id and rows["TURN_0003"].confidence == "high"
    assert rows["TURN_0003"].model == "claude-opus-5-5/speakers-captions-v1"
    # turns the model left out are recorded as unidentified
    assert rows["TURN_0001"].name is None and rows["TURN_0001"].confidence == "low"
    linked = db_session.scalars(select(TranscriptChunk).where(
        TranscriptChunk.meeting_id == m.id, TranscriptChunk.speaker_entity_id == lusk.id)).all()
    assert [c.speaker_label for c in linked] == ["TURN_0003"]


def test_voice_separated_meetings_keep_the_original_prompt(db_session, monkeypatch):
    m, _ = _board_meeting(db_session)
    db_session.query(TranscriptChunk).filter_by(meeting_id=m.id).update(
        {TranscriptChunk.speaker_label: "SPEAKER_01"})
    db_session.commit()
    seen = []
    monkeypatch.setattr(sn, "_call_claude", lambda prompt: seen.append(prompt) or ([], "claude-opus-5-5"))
    sn.name_meeting(db_session, m)
    assert "SPEAKER LABELS TO IDENTIFY" in seen[0]
