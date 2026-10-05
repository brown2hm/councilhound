"""Candidates on the November ballot: the pinned outside sources agree with
the official ballot, names find the right candidate, and get_candidate
brings every candidate in a contest back alike, with citations marked as
outside the record."""
import datetime
from types import SimpleNamespace

import pytest

from app import ask_tools, candidates, terms
from app.routers import ask

from tests.test_ask import _install, _number, _text, _tool
from tests.test_endpoints import _seed


def _ballot() -> dict[str, str]:
    """Every name on the sample ballot -> its contest key."""
    keys = {label: key for key, (_, label) in candidates.CONTESTS.items()}
    return {name: keys[contest]
            for t in terms.TERMS.values() for contest, names in t.candidates for name in names}


# ---------------------------------------------------------------- the data

def test_every_name_on_the_ballot_has_one_entry():
    ballot = _ballot()
    names = [c.ballot_name for c in candidates.CANDIDATES]
    assert sorted(names) == sorted(ballot)
    for c in candidates.CANDIDATES:
        assert c.contest == ballot[c.ballot_name], c.ballot_name


def test_sources_are_complete_and_dated():
    for c in candidates.CANDIDATES:
        # something to say either way: a source, or what was looked for
        assert c.sources or c.not_found, c.ballot_name
        for s in c.sources:
            assert s.kind in candidates.KIND_LABEL, (c.ballot_name, s.kind)
            assert s.url.startswith("https://") and s.facts and all(f.strip() for f in s.facts)
            assert s.checked <= datetime.date.today()
            # each candidate's sources are about that candidate: one URL once
        assert len({s.url for s in c.sources}) == len(c.sources), c.ballot_name


def test_names_find_the_candidate():
    def one(name):
        hits = candidates.match(name)
        assert len(hits) == 1, (name, [c.ballot_name for c in hits])
        return hits[0].ballot_name

    assert one("Tom Peterson") == 'Thomas D. "Tom" Peterson'
    assert one("Padmore") == "María José Padmore"
    assert one("Maria Padmore") == "María José Padmore"
    assert one("Kristen Lockhart") == "Kirsten Sides Lockhart"   # misspelt first name
    assert one("Sandi Brown") == "Sandi W. Slappey Brown"
    assert one("candidate Lough") == "Jessica L. Lough"
    assert candidates.match("Nobody Atall") == []


def test_question_names_candidates_but_not_city_hall():
    named = lambda q: [c.ballot_name for c in candidates.named_in(q)]
    assert named("What is happening at City Hall?") == []
    assert named("Who is Stacy Hall running against?") == ["Stacy R. Hall"]
    assert named("What does Padmore want to do about housing?") == ["María José Padmore"]


# ---------------------------------------------------------------- the tool

_SRC = candidates.CandidateSource
_FAKE = (
    candidates.Candidate(
        "Ann B. Newcomer", "mayor",
        sources=(_SRC("https://example.org/ann", "Ann for Mayor", "campaign", "About Ann",
                      datetime.date(2026, 10, 5), ("The campaign site lists parks as a priority.",)),),
        not_found=("no Vote411 answers",)),
    candidates.Candidate(
        "Carl D. Sitting", "mayor", incumbent="City Councilmember",
        sources=(_SRC("https://example.org/carl", "VPAP", "finance", "Carl D. Sitting",
                      datetime.date(2026, 10, 5), ("Reported $1,000 raised through 2026-09-30.",),
                      published=datetime.date(2026, 10, 1)),)),
)


@pytest.fixture
def fake_ballot(monkeypatch):
    monkeypatch.setattr(candidates, "CANDIDATES", _FAKE)
    monkeypatch.setattr(candidates, "RACE_SOURCES", {"mayor": (
        _SRC("https://example.org/forum", "League of Women Voters", "forum", "Mayoral forum",
             datetime.date(2026, 10, 5), ("Both candidates took part.",)),)})


def test_one_candidate_with_opponents_and_gaps(fake_ballot):
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_candidate(sources, "Newcomer")
    summary, campaign = (sources.get(n) for n in nums)
    assert summary["kind"] == campaign["kind"] == "candidate"
    assert "Has no voting record in the meetings CouncilHound indexes" in summary["text"]
    assert "Also on the ballot for this contest: Carl D. Sitting." in summary["text"]
    assert "Looked for and not found as of 2026-10-05: no Vote411 answers." in summary["text"]
    assert campaign["title"] == "Ann B. Newcomer: Ann for Mayor (campaign site)"
    assert campaign["link"] == "https://example.org/ann"


def test_whole_contest_comes_back_alike(fake_ballot):
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_candidate(sources, contest="mayor")
    assert header == "Everyone on the ballot for Mayor (vote for one): Ann B. Newcomer, Carl D. Sitting."
    titles = [sources.get(n)["title"] for n in nums]
    assert titles[0].startswith("Mayor (vote for one): League of Women Voters")
    assert sum(t.endswith("candidate for Mayor (vote for one)") for t in titles) == 2
    sitting = next(sources.get(n) for n in nums if "Carl D. Sitting: candidate" in sources.get(n)["title"])
    assert "Currently: City Councilmember." in sitting["text"]
    # a published source is dated by publication, not by when it was checked
    assert next(sources.get(n) for n in nums if "VPAP" in sources.get(n)["title"])["date"] == "2026-10-01"


def test_unknown_and_ambiguous_names(fake_ballot, monkeypatch):
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_candidate(sources, "Nobody")
    assert nums == [] and "No candidate on the City's November ballot matches" in header
    monkeypatch.setattr(candidates, "CANDIDATES", _FAKE + (
        candidates.Candidate("Ann Q. Newcomer", "school_board", not_found=("anything",)),))
    nums, header = ask_tools.get_candidate(sources, "Newcomer")
    assert nums == [] and header.startswith("Several candidates match")


def test_answer_cites_a_candidate_source(client, db, monkeypatch, fake_ballot):
    _seed(db)

    def answer(messages):
        result = messages[-1]["content"][0]["content"]
        n = _number(result, "Ann for Mayor")
        return "end_turn", [_text(f"Her campaign site lists parks as a priority [{n}].")]

    fake = _install(monkeypatch, [
        lambda m: ("tool_use", [_tool("t1", "get_candidate", name="Ann Newcomer")]),
        answer,
    ])
    resp = client.post("/ask/", json={"question": "What does Ann Newcomer stand for?"})
    assert resp.status_code == 200
    body = resp.json()
    (cite,) = body["citations"]
    assert cite["kind"] == "candidate" and cite["link"] == "https://example.org/ann"
    # the opening turn already points at the candidate
    assert "Candidates the question names: Ann B. Newcomer (running for Mayor)." in \
        fake.calls[0]["messages"][0]["content"]
    # and no member card: an outside source is not a seat on a body
    assert body["members"] == []
