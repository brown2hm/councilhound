import datetime

import numpy as np
import pytest
from sqlalchemy import select

from councilhound.db.models import Entity, Meeting, MeetingSpeaker, SpeakerVoice, TranscriptChunk
from councilhound.extraction import voice_match as vm
from councilhound.extraction import voices


def _unit(i, noise=0.0, seed=0):
    v = np.zeros(256)
    v[i] = 1.0
    if noise:
        v += np.random.default_rng(seed).normal(0, noise, 256)
    return (v / np.linalg.norm(v)).tolist()


def _mix(i, j):
    v = np.zeros(256)
    v[i] = v[j] = 1.0
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def world(db_session):
    s = db_session
    amos = Entity(entity_type="person", name="Anthony Amos", canonical_slug="anthony-amos")
    bates = Entity(entity_type="person", name="Billy Bates", canonical_slug="billy-bates")
    s.add_all([amos, bates])
    s.flush()
    meetings = []
    for day, clip in ((1, "a"), (8, "b"), (15, "c")):
        m = Meeting(granicus_view_id="13", granicus_clip_id=clip, body="city_council",
                    meeting_type="council_meeting", title="City Council Meeting",
                    meeting_date=datetime.date(2026, 9, day))
        s.add(m)
        s.flush()
        meetings.append(m)

    def label(m, lab, vec, sec=60.0, **row):
        s.add(SpeakerVoice(meeting_id=m.id, speaker_label=lab, embedding=vec, speech_seconds=sec))
        s.add(TranscriptChunk(meeting_id=m.id, start_seconds=0, end_seconds=5, text="words", speaker_label=lab))
        if row:
            s.add(MeetingSpeaker(meeting_id=m.id, speaker_label=lab, **{
                "confidence": "high", "mixed": False, "source": "model", **row}))

    a, b, c = meetings
    for m, seed in ((a, 1), (b, 2)):  # named by the transcript in two meetings each
        label(m, "SPEAKER_00", _unit(0, 0.02, seed), name="Anthony Amos", entity_id=amos.id, role="member")
        label(m, "SPEAKER_01", _unit(1, 0.02, seed + 10), name="Billy Bates", entity_id=bates.id, role="member")
    s.commit()
    return s, (a, b, c), amos, bates, label


def test_unnamed_label_is_voice_named(world):
    s, (a, b, c), amos, bates, label = world
    label(c, "SPEAKER_05", _unit(0, 0.02, 3), name=None, confidence="low", role="unknown")
    label(c, "SPEAKER_06", _unit(0, 0.02, 4))  # no meeting_speakers row at all
    s.commit()
    r = vm.match_meeting(s, c)
    assert r["named"] == 2
    rows = {x.speaker_label: x for x in s.scalars(select(MeetingSpeaker).where(MeetingSpeaker.meeting_id == c.id))}
    assert (rows["SPEAKER_05"].entity_id, rows["SPEAKER_05"].source, rows["SPEAKER_05"].role) == (amos.id, "voice", "member")
    assert rows["SPEAKER_06"].name == "Anthony Amos"
    linked = s.scalars(select(TranscriptChunk.speaker_entity_id).where(
        TranscriptChunk.meeting_id == c.id, TranscriptChunk.speaker_label == "SPEAKER_05")).all()
    assert linked == [amos.id]


@pytest.mark.parametrize("vec, sec, why", [
    (_mix(0, 1), 60.0, "ambiguous between two voiceprints"),
    (_unit(0, 0.02, 5), 10.0, "too little speech"),
    (_unit(7), 60.0, "nobody we know"),
])
def test_rule_leaves_doubtful_labels_alone(world, vec, sec, why):
    s, (a, b, c), *_, label = world
    label(c, "SPEAKER_05", vec, sec=sec, name=None, confidence="low", role="unknown")
    s.commit()
    assert vm.match_meeting(s, c)["named"] == 0, why


def test_never_overrides_manual_student_mixed_or_public(world):
    s, (a, b, c), amos, bates, label = world
    label(c, "SPEAKER_10", _unit(0, 0.02, 6), name="Melissa", source="manual", role="clerk")
    label(c, "SPEAKER_11", _unit(0, 0.02, 7), name="Veronica", role="student")
    label(c, "SPEAKER_12", _unit(0, 0.02, 8), name="Someone", role="other", mixed=True)
    label(c, "SPEAKER_13", _unit(0, 0.02, 9), name="Billy Bates", entity_id=bates.id, role="member")
    s.commit()
    assert vm.match_meeting(s, c)["candidates"] == 0


def test_voiceprints_need_two_other_meetings_and_ignore_voice_rows(world):
    s, (a, b, c), amos, bates, label = world
    # in meeting a, Amos's print only has meeting b left: one meeting is not enough
    label(a, "SPEAKER_07", _unit(2, 0.02, 11), name=None, confidence="low", role="unknown")
    # a voice-named label elsewhere must not become a voiceprint for someone new
    label(c, "SPEAKER_08", _unit(2, 0.02, 12), name="Anthony Amos", entity_id=amos.id,
          role="member", source="voice")
    s.commit()
    prints = vm.Voiceprints(s, "city_council").prints(a.id)
    assert set(prints) == set()  # Amos and Bates each have only meeting b outside a
    assert vm.match_meeting(s, a)["named"] == 0


def test_rerun_withdraws_a_voice_name_that_no_longer_holds(world):
    s, (a, b, c), amos, bates, label = world
    label(c, "SPEAKER_05", _unit(0, 0.02, 3), name=None, confidence="low", role="unknown")
    s.commit()
    vm.match_meeting(s, c)
    voice = s.scalar(select(SpeakerVoice).where(SpeakerVoice.meeting_id == c.id))
    voice.embedding = _unit(9)
    s.commit()
    r = vm.match_meeting(s, c)
    assert r["withdrawn"] == 1
    row = s.scalar(select(MeetingSpeaker).where(MeetingSpeaker.meeting_id == c.id))
    assert (row.name, row.entity_id, row.confidence) == (None, None, "low")


def test_disagreements_report_without_changing(world):
    s, (a, b, c), amos, bates, label = world
    label(c, "SPEAKER_20", _unit(0, 0.02, 13), name="Billy Bates", entity_id=bates.id, role="member")
    s.commit()
    d = vm.disagreements(s)
    assert [(x["clip"], x["transcript_says"], x["voice_says"]) for x in d] == [("c", "Billy Bates", "Anthony Amos")]
    row = s.scalar(select(MeetingSpeaker).where(MeetingSpeaker.speaker_label == "SPEAKER_20"))
    assert row.name == "Billy Bates" and row.source == "model"


def test_bodies_not_enabled_are_skipped(world):
    s, (a, b, c), *_ = world
    c.body = "school_board"
    s.commit()
    assert vm.match_meeting(s, c)["status"] == "body_not_enabled"


def test_compute_voices_uses_the_longest_spans():
    audio = np.zeros(16000 * 120, dtype=np.float32)
    calls = []

    def embed(batch):
        calls.append(batch.shape)
        return np.ones((batch.shape[0], 256))

    out = voices.compute_voices(audio, {"SPEAKER_00": [(0, 1.5), (10, 40), (50, 55)],
                                        "SPEAKER_01": [(60, 61)]}, embed)
    assert set(out) == {"SPEAKER_00"}  # SPEAKER_01 only has a 1 s span
    vec, sec = out["SPEAKER_00"]
    assert len(vec) == 256 and abs(np.linalg.norm(vec) - 1) < 1e-6
    assert sec == pytest.approx(15.0)  # a 10 s window from (10, 40) + all 5 s of (50, 55)
    assert calls == [(2, 1, 160000)]
