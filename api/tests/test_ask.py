"""/ask: the agent loop with Claude scripted, the knowledge tools against
seeded rows, and the term schedule read from the jurisdiction config.
Exercises retrieval SQL, source numbering and citation wiring, not the
models."""
import json
from types import SimpleNamespace

import pytest

from app import ask_tools
from app.routers import ask

from tests.test_endpoints import _seed
from tests.test_members import _seed_members


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(id_, tool_name, **args):
    return SimpleNamespace(type="tool_use", id=id_, name=tool_name, input=args)


class FakeClient:
    """Replays scripted responses; each script entry is a function of the
    messages so far, so a later turn can cite numbers a tool returned."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        stop, content = self.script.pop(0)(kw["messages"])
        return SimpleNamespace(stop_reason=stop, content=content)


@pytest.fixture(autouse=True)
def _no_embeddings(monkeypatch):
    monkeypatch.setattr("app.ask_tools.embed_query", lambda q: [0.1] * 768)


def _install(monkeypatch, script):
    fake = FakeClient(script)
    monkeypatch.setattr(ask, "_client", lambda: fake)
    return fake


def _number(text, marker):
    """The [n] of the first source block whose header contains marker."""
    for line in text.splitlines():
        if line.startswith("[") and marker in line:
            return int(line[1:line.index("]")])
    raise AssertionError(f"{marker!r} not in {text!r}")


def test_answer_straight_from_the_opening_search(client, db, monkeypatch):
    _seed(db)

    def answer(messages):
        n = _number(messages[0]["content"], "item 7a")
        return "end_turn", [_text(f"The contract was approved [{n}]. Also [99].")]

    fake = _install(monkeypatch, [answer])
    data = client.post("/ask/", json={"question": "What happened with the trail design contract?"}).json()
    opening = fake.calls[0]["messages"][0]["content"]
    assert "Today is" in opening and "Question: What happened" in opening
    assert "Tracked topics the question names" not in opening  # no full topic name in it
    # the agenda-item source carries its roll call
    assert "Roll call (Approve contract): passed" in opening
    assert len(data["citations"]) == 1  # [99] was never shown, so it is not a citation
    cite = data["citations"][0]
    assert cite["kind"] == "agenda_item" and cite["agenda_item_label"] == "7a"
    assert cite["link"].endswith("starttime=439&entrytime=439")
    assert [t["slug"] for t in data["topics"]] == ["george-snyder-trail"]
    assert data["topics"][0]["update_count"] == 2
    assert data["members"] == []


def test_tool_round_reaches_the_topic_record(client, db, monkeypatch):
    _seed(db)

    def call_topic(messages):
        assert "Tracked topics the question names: George Snyder Trail" in messages[0]["content"]
        return "tool_use", [_tool("t1", "get_topic", name="George Snyder Trail")]

    def answer(messages):
        result = messages[-1]["content"][0]
        assert result["tool_use_id"] == "t1" and not result["is_error"]
        n = _number(result["content"], "Planning Commission Meeting")
        return "end_turn", [_text(f"It was completed [{n}].")]

    fake = _install(monkeypatch, [call_topic, answer])
    steps = []
    result = ask.run_ask(db, "Where does the George Snyder Trail stand?", on_step=steps.append)
    assert steps == ["Reading the record on George Snyder Trail"]
    assert result["citations"][0]["kind"] == "timeline"
    assert result["citations"][0]["date"] == "2025-06-03"
    # a cited topic record puts the topic on the card
    assert result["topics"][0]["slug"] == "george-snyder-trail"
    # the final round is allowed tools; nothing forced it
    assert fake.calls[-1]["tool_choice"] == {"type": "auto"}


def test_last_round_must_answer(client, db, monkeypatch):
    _seed(db)
    script = [lambda m: ("tool_use", [_tool(f"t{i}", "search_record", query="trail")])
              for i in range(ask.MAX_TOOL_ROUNDS)]
    script.append(lambda m: ("end_turn", [_text("Done.")]))
    fake = _install(monkeypatch, script)
    assert ask.run_ask(db, "trail?")["answer"] == "Done."
    assert fake.calls[-1]["tool_choice"] == {"type": "none"}


def test_failed_tool_comes_back_as_an_error_result(client, db, monkeypatch):
    _seed(db)

    def call(messages):
        return "tool_use", [_tool("t1", "no_such_tool")]

    def answer(messages):
        assert messages[-1]["content"][0]["is_error"] is True
        return "end_turn", [_text("Not in the record.")]

    _install(monkeypatch, [call, answer])
    assert ask.run_ask(db, "anything")["answer"] == "Not in the record."


def test_stream_sends_steps_then_the_answer(client, db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(ask, "get_session", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    _install(monkeypatch, [
        lambda m: ("tool_use", [_tool("t1", "list_members")]),
        lambda m: ("end_turn", [_text("Answer.")]),
    ])
    resp = client.post("/ask/stream", json={"question": "Who is on the council?"})
    assert resp.status_code == 200
    events = [json.loads(line) for line in resp.text.splitlines() if line]
    assert [e["type"] for e in events] == ["step", "answer"]
    assert events[0]["label"] == "Checking the roster and election dates"
    assert events[-1]["answer"] == "Answer."


# ---------------------------------------------------------------- tools

def test_compare_members_head_to_head(db):
    _seed_members(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.compare_members(db, sources, ["Mayor Read", "Hall"])
    assert header.startswith("Comparing Catherine Read, Stacy Hall")
    text = "\n\n".join(sources.block(n) for n in nums)
    assert "voted the same way on 0 of 1 shared roll calls" in text
    # the one contested roll call where they split comes along as a vote source
    splits = [sources.get(n) for n in nums if sources.get(n)["kind"] == "vote"]
    assert len(splits) == 1 and "Adopt the appropriation" in splits[0]["text"]
    # each member's seat, from the pinned City schedule
    term = next(sources.get(n) for n in nums if sources.get(n)["kind"] == "term"
                and "Catherine Read" in sources.get(n)["title"])
    assert "Not on the ballot" in term["text"] and "2026-11-03" in term["text"]


def test_get_member_and_ambiguity(db):
    _seed_members(db)
    sources = ask_tools.Sources()
    nums, header, eid = ask_tools.get_member(db, sources, "Councilmember Hall")
    kinds = [sources.get(n)["kind"] for n in nums]
    assert kinds[0] == "member" and "term" in kinds
    assert "On the ballot" in sources.get(nums[kinds.index("term")])["text"]
    nums, header, eid = ask_tools.get_member(db, sources, "Nobody Atall")
    assert nums == [] and eid is None


def test_list_members_carries_the_ballot(db):
    _seed_members(db)
    sources = ask_tools.Sources()
    nums = ask_tools.list_members(db, sources, "city_council")
    text = sources.get(nums[0])["text"]
    assert "Catherine Read (Mayor; term ends 2026-12-31; not on the ballot)" in text
    assert "Official candidate list" in text and "Kirsten Sides Lockhart (Mayor)" in text


def test_sources_are_numbered_once(db):
    _seed(db)
    sources = ask_tools.Sources()
    first = ask_tools.search_record(db, sources, "trail design contract")
    again = ask_tools.search_record(db, sources, "trail design contract")
    assert first == again and len(sources.items) == len(first)


def test_member_routes_carry_the_term(client, db):
    _seed_members(db)
    read = client.get("/members/catherine-read").json()
    assert read["term"]["next_election"] == "2026-11-03"
    assert read["term"]["on_ballot"] is False
    listing = {m["slug"]: m for m in client.get("/members/").json()}
    assert listing["stacy-hall"]["term"]["on_ballot"] is True
