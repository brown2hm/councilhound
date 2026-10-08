"""compare_answers puts every candidate's answer to the same questionnaire
question side by side, in ballot order, naming who didn't respond;
get_meeting reads one meeting start to finish in agenda order."""
import datetime

import pytest

from app import ask_tools, candidates, questionnaires
from app.routers import ask

from tests.test_ask import _install, _number, _text, _tool
from tests.test_endpoints import _seed

_Q = questionnaires.Questionnaire
_R = questionnaires.Response
_C = candidates.Candidate


@pytest.fixture
def fake_race(monkeypatch):
    monkeypatch.setattr(candidates, "CANDIDATES", (
        _C("Ann B. Newcomer", "mayor", not_found=("x",)),
        _C("Carl D. Sitting", "mayor", not_found=("x",)),
        _C("Dee E. Quiet", "mayor", not_found=("x",)),
    ))
    monkeypatch.setattr(questionnaires, "QUESTIONNAIRES", (
        _Q("vote411_mayor", "mayor", "League of Women Voters (Vote411)", "Vote411, Mayor",
           "https://vote411.example/mayor", datetime.date(2026, 10, 5),
           questions=(("priorities", "What are your priorities?"),
                      ("urgent", "What is the most urgent issue facing the City?")),
           responses=(_R("Carl D. Sitting", (("priorities", "Budget discipline and parks."),
                                             ("urgent", None))),
                      _R("Ann B. Newcomer", (("priorities", "Housing near transit."),
                                             ("urgent", "Communication with residents."))))),
        _Q("patch_mayor", "mayor", "Patch (Fairfax City)", "Patch, Mayor", "https://patch.example",
           datetime.date(2026, 10, 5),
           questions=(("development", "What approach should the City take to new development and housing?"),),
           responses=(_R("Dee E. Quiet", (("development", "Smaller buildings in Old Town."),),
                         url="https://patch.example/quiet", published=datetime.date(2026, 9, 17)),)),
    ))


def test_answers_side_by_side_in_ballot_order(fake_race):
    sources = ask_tools.Sources()
    nums, header = ask_tools.compare_answers(sources, "mayor", "priorities")
    rows = [sources.get(n) for n in nums]
    # ballot order, not the order the guide lists them in
    assert [r["title"].split(":")[0] for r in rows[:2]] == ["Ann B. Newcomer", "Carl D. Sitting"]
    assert rows[0]["text"].endswith("Answer (paraphrased from the candidate's written reply): Housing near transit.")
    assert rows[0]["kind"] == "candidate" and rows[0]["link"] == "https://vote411.example/mayor"
    assert rows[2]["title"] == "Vote411, Mayor: candidates who did not respond"
    assert rows[2]["text"] == "As of 2026-10-05, no reply from: Dee E. Quiet."
    assert "Patch (Fairfax City) asked nothing close to 'priorities'" in header
    assert "development = “What approach should the City take" in header


def test_a_topic_finds_each_guides_closest_question(fake_race):
    sources = ask_tools.Sources()
    nums, header = ask_tools.compare_answers(sources, "mayor", "housing")
    rows = [sources.get(n) for n in nums]
    quiet = next(r for r in rows if r["title"].startswith("Dee E. Quiet"))
    assert quiet["link"] == "https://patch.example/quiet" and quiet["date"] == "2026-09-17"
    assert "Vote411) asked nothing close to 'housing'" in header
    # a blank answer is said to be blank, not skipped
    nums, _ = ask_tools.compare_answers(sources, "mayor", "urgent")
    carl = next(sources.get(n) for n in nums if sources.get(n)["title"].startswith("Carl"))
    assert carl["text"].endswith("Left this question blank.")
    assert ask_tools.compare_answers(sources, "governor", "x")[0] == []


def test_meeting_by_body_and_date(db):
    m1, m2 = _seed(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_meeting(db, sources, "city_council", "2025-01-07")
    overview, item = (sources.get(n) for n in nums)
    assert overview["kind"] == "meeting" and overview["link"] == f"/meetings/{m1.id}"
    assert "1 agenda items, 1 with recorded votes" in overview["text"]
    assert "George Snyder Trail (in_progress)" in overview["text"]
    assert item["kind"] == "agenda_item" and item["agenda_item_label"] == "7a"
    assert "Outcome: Approved 5-1" in item["text"]
    assert "Roll call: Approve contract — passed, 1-0 (yes: Read)" in item["text"]
    assert "George Snyder Trail: Design contract approved. (status after: in_progress)" in item["text"]
    assert "starttime=439" in item["link"]


def test_latest_meeting_and_misses(db, monkeypatch):
    m1, m2 = _seed(db)
    monkeypatch.setattr(ask_tools, "_today", lambda: datetime.date(2026, 10, 6))
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_meeting(db, sources, "planning_commission")
    assert sources.get(nums[0])["date"] == "2025-06-03"
    assert header.endswith("No date was given, so this is the body's most recent meeting.")
    nums, header = ask_tools.get_meeting(db, sources, "city_council", "2025-02-02")
    assert nums == [] and header == "No City Council meeting is in the record on 2025-02-02."
    nums, header = ask_tools.get_meeting(db, sources, "city_council", "2026-12-01")
    assert header == "That date is in the future; get_upcoming has posted agendas."


def test_answer_cites_a_meeting_item(client, db, monkeypatch):
    _seed(db)

    def answer(messages):
        n = _number(messages[-1]["content"][0]["content"], "item 7a")
        return "end_turn", [_text(f"Council approved the trail design contract [{n}].")]

    _install(monkeypatch, [
        lambda m: ("tool_use", [_tool("t1", "get_meeting", body="city_council", date="2025-01-07")]),
        answer,
    ])
    body = client.post("/ask/", json={"question": "What happened at the January 7 2025 Council meeting?"}).json()
    (cite,) = body["citations"]
    assert cite["kind"] == "agenda_item" and cite["agenda_item_label"] == "7a"
    assert ask._step_label("get_meeting", {"body": "city_council", "date": "2025-01-07"}) == \
        "Reading the City Council meeting of 2025-01-07"
