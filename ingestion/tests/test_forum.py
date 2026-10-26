"""Candidate forum transcripts: runs follow the diarization, the plan names
speakers and questions, and cuts and fixes only touch the exact text they
name, so a turn stays contiguous whisper output."""
import pytest

from councilhound.extraction import forum


def _seg(start, end, text, speaker_words=None):
    words, t = [], start
    step = (end - start) / max(len(text.split()), 1)
    for w in text.split():
        words.append({"start": t, "end": t + step, "word": " " + w})
        t += step
    return {"start": start, "end": end, "text": text, "words": words}


RAW = {
    "url": "https://www.youtube.com/watch?v=abc",
    "segments": [
        _seg(0, 4, "Welcome. First, growth. What would you do?"),
        _seg(4, 6, "Ann, two minutes."),
        _seg(6, 26, "Thank you. We should grow carefully near transit."),
        _seg(26, 46, "And protect the tree canopy for for votes."),
        _seg(46, 50, "Bob, your turn."),
        _seg(50, 75, "I agree on transit, but taxes come first. Thank you, Bob."),
    ],
    "turns": [
        {"start": 0, "end": 6, "speaker": "SPEAKER_00"},
        {"start": 6, "end": 46, "speaker": "SPEAKER_01"},
        {"start": 46, "end": 50, "speaker": "SPEAKER_00"},
        {"start": 50, "end": 75, "speaker": "SPEAKER_02"},
    ],
}

PLAN = {
    "key": "test_forum",
    "speakers": {"SPEAKER_00": "moderator", "SPEAKER_01": "Ann B. Newcomer", "SPEAKER_02": "Carl D. Sitting"},
    "questions": [{"id": "growth", "topic": "Growth", "start": 0, "asked_at": 0}],
    "cuts": {"50": {"suffix": " Thank you, Bob."}, "6": {"fixes": [{"from": "for for votes", "to": "four votes"}]}},
}


def test_runs_follow_the_speaker_turns():
    runs = forum.speaker_runs(RAW)
    assert [r["label"] for r in runs] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00", "SPEAKER_02"]
    assert runs[1]["text"].startswith("Thank you. We should grow")
    assert [int(p["start"]) for p in runs[1]["parts"]] == [6, 26]


def test_build_names_speakers_and_questions():
    out = forum.build(RAW, PLAN)
    assert out["questions"] == [{"id": "growth", "topic": "Growth", "start": 0,
                                 "asked": "Welcome. First, growth. What would you do? Ann, two minutes."}]
    ann, carl = out["turns"]
    assert ann["speaker"] == "Ann B. Newcomer" and ann["question"] == "growth"
    assert ann["start"] == 6 and ann["end"] == 46
    assert [p["text"] for p in ann["parts"]] == [
        "Thank you. We should grow carefully near transit.", "And protect the tree canopy four votes."]
    # the moderator's thanks, credited to the wrong voice, is cut from the end
    assert [p["text"] for p in carl["parts"]] == ["I agree on transit, but taxes come first."]


def test_cut_drops_a_leading_part_and_keeps_starts():
    parts = [{"start": 1, "text": "Kirsten, two minutes."}, {"start": 3, "text": "Thank you. So first, growth."}]
    assert forum._cut(parts, "Kirsten, two minutes. Thank you.", None) == [{"start": 3, "text": "So first, growth."}]


def test_cuts_and_fixes_must_match_exactly():
    with pytest.raises(ValueError, match="does not end with"):
        forum.build(RAW, {**PLAN, "cuts": {"50": {"suffix": "Thanks, Bob."}}})
    with pytest.raises(ValueError, match="matches 0 parts"):
        forum.build(RAW, {**PLAN, "cuts": {"6": {"fixes": [{"from": "five votes", "to": "x"}]}}})
    with pytest.raises(ValueError, match="do not exist"):
        forum.build(RAW, {**PLAN, "cuts": {"999": {"prefix": "x"}}})
    with pytest.raises(ValueError, match="no moderator run"):
        forum.build(RAW, {**PLAN, "questions": [{"id": "q", "topic": "Q", "start": 6, "asked_at": 6}]})
