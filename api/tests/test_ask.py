"""/ask: the agent loop with Claude scripted, the knowledge tools against
seeded rows, and the term schedule read from the jurisdiction config.
Exercises retrieval SQL, source numbering and citation wiring, not the
models."""
import json
import re
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
    assert ("Catherine Read (Mayor; term ends 2026-12-31; not on the ballot; "
            "Not seeking a third term as Mayor)") in text
    assert "Stacy Hall (Councilmember; term ends 2026-12-31; on the ballot; Running for reelection to Council)" in text
    # each contest names its own candidates, so council and mayoral runs never blur
    assert "On the official ballot for Mayor (vote for one): Kirsten Sides Lockhart, " in text
    assert "On the official ballot for City Council (vote for not more than six): Stacy R. Hall, " in text


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


# ---------------------------------------------------------------- across bodies

def _seed_candidates(db):
    """A commissioner and a councilmember (both running for Mayor) who never
    voted together but both acted on one rezoning: she recommended denial,
    he voted against approval."""
    import datetime

    from councilhound.db.models import (
        AgendaItem, Document, Entity, EntityAlias, EntityMention, EntityProfile, Meeting, Vote,
    )

    pc = Meeting(granicus_clip_id="400", granicus_view_id="13", body="planning_commission",
                 meeting_type="planning_commission", meeting_date=datetime.date(2025, 6, 23),
                 title="Planning Commission Regular Meeting", status="extracted")
    cc = Meeting(granicus_clip_id="401", granicus_view_id="13", body="city_council",
                 meeting_type="council_regular", meeting_date=datetime.date(2025, 7, 22),
                 title="City Council Meeting", status="extracted")
    db.add_all([pc, cc])
    db.flush()
    pc_item = AgendaItem(meeting_id=pc.id, label="5a", title="Public hearing: rezoning of 4131 Chain Bridge Road")
    cc_item = AgendaItem(meeting_id=cc.id, label="9a", title="Rezoning and GDP, 4131 Chain Bridge Road")
    db.add_all([pc_item, cc_item])
    db.flush()
    db.add_all([
        Document(meeting_id=cc.id, doc_type="agenda", source_url="cc-agenda",
                 raw_text="City of Fairfax\nMayor\nCatherine S. Read\nCity Council\nThomas D. Peterson\n"),
        Document(meeting_id=pc.id, doc_type="agenda", source_url="pc-agenda",
                 raw_text="Planning Commission\nJames Feather, Chair\nKirsten Lockhart, Vice-Chair\n"),
        Vote(meeting_id=pc.id, agenda_item_id=pc_item.id, description="Recommend denial of the rezoning",
             motion_result="passed", vote_breakdown={"Lockhart": "yes", "Feather": "yes", "Rice": "no"}),
        Vote(meeting_id=cc.id, agenda_item_id=cc_item.id, description="Approve the rezoning and GDP",
             motion_result="failed", vote_breakdown={"Peterson": "no", "Read": "yes", "Hall": "no"}),
    ])
    lockhart = Entity(entity_type="person", name="Kirsten Lockhart", canonical_slug="kirsten-lockhart")
    peterson = Entity(entity_type="person", name="Thomas Peterson", canonical_slug="thomas-peterson")
    site = Entity(entity_type="project", name="4131 Chain Bridge Road", canonical_slug="4131-chain-bridge-road")
    alias_topic = Entity(entity_type="project", name="Davies Property", canonical_slug="davies-property")
    db.add_all([lockhart, peterson, site, alias_topic])
    db.flush()
    db.add_all([
        EntityAlias(entity_id=lockhart.id, alias="Vice-Chair Lockhart"),
        EntityAlias(entity_id=lockhart.id, alias="Commissioner Lockhart"),
        EntityAlias(entity_id=peterson.id, alias="Councilmember Peterson"),
        EntityMention(entity_id=site.id, meeting_id=pc.id, agenda_item_id=pc_item.id, role="subject"),
        EntityMention(entity_id=site.id, meeting_id=cc.id, agenda_item_id=cc_item.id, role="subject"),
        # the same application under its other name: one matter, not two
        EntityMention(entity_id=alias_topic.id, meeting_id=pc.id, agenda_item_id=pc_item.id, role="subject"),
        EntityMention(entity_id=alias_topic.id, meeting_id=cc.id, agenda_item_id=cc_item.id, role="subject"),
        EntityProfile(entity_id=site.id, summary="s", member_commentary=[
            {"member": "Vice-Chair Lockhart", "slug": "kirsten-lockhart",
             "summary": "Found the proposal out of conformance with the Comprehensive Plan."},
            {"member": "Councilmember Peterson", "slug": "thomas-peterson",
             "summary": "Voted against all three approval motions."}]),
    ])
    db.flush()
    # what each said, as the speaker-naming stage leaves it: a public name
    # in meeting_speakers and the roster link on that label's chunks
    from councilhound.db.models import MeetingSpeaker, TranscriptChunk
    db.add_all([
        MeetingSpeaker(meeting_id=pc.id, speaker_label="SPEAKER_03", name="Kirsten Lockhart",
                       entity_id=lockhart.id, role="member", confidence="high"),
        MeetingSpeaker(meeting_id=cc.id, speaker_label="SPEAKER_07", name="Thomas Peterson",
                       entity_id=peterson.id, role="member", confidence="high"),
        TranscriptChunk(meeting_id=pc.id, start_seconds=3600, end_seconds=3660, speaker_label="SPEAKER_03",
                        speaker_entity_id=lockhart.id, embedding=[0.1] * 768,
                        text="I cannot find this rezoning in conformance with the Comprehensive Plan; "
                             "the density is well beyond what the Old Town transition calls for."),
        TranscriptChunk(meeting_id=pc.id, start_seconds=3700, end_seconds=3702, speaker_label="SPEAKER_03",
                        speaker_entity_id=lockhart.id, embedding=[0.1] * 768, text="Second."),
        TranscriptChunk(meeting_id=cc.id, start_seconds=5400, end_seconds=5460, speaker_label="SPEAKER_07",
                        speaker_entity_id=peterson.id, embedding=[0.1] * 768,
                        text="My concern with this rezoning is the traffic on Chain Bridge Road and the "
                             "scale next to the historic district, so I will not support it tonight."),
        # an unidentified speaker saying much the same is never attributed
        TranscriptChunk(meeting_id=cc.id, start_seconds=5500, end_seconds=5560, speaker_label="SPEAKER_09",
                        embedding=[0.1] * 768,
                        text="I also have concerns with this rezoning and the Comprehensive Plan, and "
                             "would ask the applicant to come back with a smaller building."),
    ])
    db.commit()


def test_statements_are_the_members_own_identified_words(db):
    _seed_candidates(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.get_statements(db, sources, "Kristen Lockhart", "rezoning")
    texts = [sources.get(n)["text"] for n in nums]
    assert texts and all(t.startswith("Kirsten Lockhart: ") for t in texts)
    assert any("conformance with the Comprehensive Plan" in t for t in texts)
    assert not any(t.endswith("Second.") for t in texts)  # too short to be a statement
    assert not any("smaller building" in t for t in texts)  # unidentified speaker
    assert sources.get(nums[0])["link"].endswith("starttime=3600&entrytime=3600")
    # coverage is stated, so silence is not read as "never said"
    assert "Speakers have been named in all 1 Planning Commission meetings with transcripts." in header

    nums, header = ask_tools.get_statements(db, sources, "Peterson")  # no topic: most recent
    assert [sources.get(n)["text"][:30] for n in nums] == ["Thomas Peterson: My concern wi"]


def test_shared_matters_quote_each_member(db):
    _seed_candidates(db)
    sources = ask_tools.Sources()
    nums, _ = ask_tools.compare_members(db, sources, ["Tom Peterson", "Kristen Lockhart"])
    shared = next(sources.get(n) for n in nums if sources.get(n)["kind"] == "shared_topic")
    quoted = {}
    for line in shared["text"].splitlines():
        if "'s own words on it: sources" in line:
            who = line.split("'s own words")[0]
            quoted[who] = [int(x) for x in re.findall(r"\[(\d+)\]", line)]
    assert set(quoted) == {"Thomas Peterson", "Kirsten Lockhart"}
    assert "traffic on Chain Bridge Road" in sources.get(quoted["Thomas Peterson"][0])["text"]
    assert "Comprehensive Plan" in sources.get(quoted["Kirsten Lockhart"][0])["text"]
    # the quoted passages come back as citable transcript sources too
    assert all(n in nums for ns in quoted.values() for n in ns)


def test_nicknames_and_misspellings_find_the_member(db):
    _seed_candidates(db)
    for name, slug in [("tom peterson", "thomas-peterson"), ("Kristen Lockhart", "kirsten-lockhart"),
                       ("Councilmember Tom Peterson", "thomas-peterson")]:
        person, _others = ask_tools.match_member(db, name)
        assert person and person["entity"].canonical_slug == slug, name
    assert ask_tools.match_member(db, "Zed Nobody") == (None, [])


def test_members_of_different_bodies_compare_on_shared_matters(db):
    _seed_candidates(db)
    sources = ask_tools.Sources()
    nums, header = ask_tools.compare_members(db, sources, ["Tom Peterson", "Kristen Lockhart"])
    assert header.startswith("Comparing Thomas Peterson, Kirsten Lockhart")
    by_kind = {}
    for n in nums:
        by_kind.setdefault(sources.get(n)["kind"], []).append(sources.get(n))
    comparison = by_kind["comparison"][0]["text"]
    assert "compared on the matters both acted on" in comparison
    assert "both acted on 1 matter(s)" in comparison
    assert len(by_kind["shared_topic"]) == 1
    shared = by_kind["shared_topic"][0]
    assert shared["title"] in ("Thomas Peterson and Kirsten Lockhart on 4131 Chain Bridge Road / Davies Property",
                               "Thomas Peterson and Kirsten Lockhart on Davies Property / 4131 Chain Bridge Road")
    # each one's vote at their own stage, and what each said
    assert "Thomas Peterson (City Council, 2025-07-22, item 9a): voted no on 'Approve the rezoning and GDP'; failed 1-2." in shared["text"]
    assert "Kirsten Lockhart (Planning Commission, 2025-06-23, item 5a): voted yes on 'Recommend denial of the rezoning'; passed 2-1." in shared["text"]
    assert "out of conformance with the Comprehensive Plan" in shared["text"]
    # and both seats: one elected, one appointed and running for Mayor
    terms_ = " ".join(t["text"] for t in by_kind["term"])
    assert "Running for Mayor rather than reelection to Council." in terms_
    assert "Also a candidate for Mayor on November 3 2026." in terms_


def test_tendencies_read_the_same_on_either_body(db):
    _seed_candidates(db)
    sources = ask_tools.Sources()
    ask_tools.compare_members(db, sources, ["Peterson", "Lockhart"])
    records = {s["title"].split(":")[0]: s["text"] for s in sources.items if s["kind"] == "member"}
    # a yes on a denial motion opposes the application, as a no on an approval does
    assert "opposed 1 of 1 roll calls where they took a side (as recommendations; " in records["Kirsten Lockhart"]
    assert "Land-use applications" in records["Thomas Peterson"] and "opposed 1 of 1" in records["Thomas Peterson"]
    assert "Absent for 0 of 1 roll calls (0%)." in records["Thomas Peterson"]


def test_quoted_member_gets_the_card_not_the_meetings_topics(client, db, monkeypatch):
    _seed_candidates(db)

    def call(messages):
        return "tool_use", [_tool("t1", "get_statements", name="Lockhart", topic="rezoning")]

    def answer(messages):
        n = _number(messages[-1]["content"][0]["content"], "Planning Commission Regular Meeting")
        return "end_turn", [_text(f"She found it out of conformance [{n}].")]

    _install(monkeypatch, [call, answer])
    result = ask.run_ask(db, "What has Lockhart said about the rezoning?")
    assert [m["slug"] for m in result["members"]] == ["kirsten-lockhart"]
    assert result["topics"] == []


def test_coverage_says_when_naming_is_partial(db):
    import datetime

    from councilhound.db.models import Meeting, TranscriptChunk
    _seed_candidates(db)
    later = Meeting(granicus_clip_id="402", granicus_view_id="13", body="planning_commission",
                    meeting_type="planning_commission", meeting_date=datetime.date(2025, 9, 8),
                    title="Planning Commission Regular Meeting", status="extracted")
    db.add(later)
    db.flush()
    db.add(TranscriptChunk(meeting_id=later.id, start_seconds=0, end_seconds=60, speaker_label="SPEAKER_01",
                           text="An unnamed meeting's transcript."))
    db.commit()
    _nums, header = ask_tools.get_statements(db, ask_tools.Sources(), "Lockhart")
    assert "Speakers have been named in 1 of 2 Planning Commission meetings with transcripts so far." in header
    assert "may simply not be attributed yet" in header


def test_unnamed_caption_turns_are_not_shown_as_speakers(db):
    import datetime

    from councilhound.db.models import Meeting, TranscriptChunk
    m = Meeting(granicus_clip_id="4241", granicus_view_id="7", body="planning_commission",
                meeting_type="planning_commission", meeting_date=datetime.date(2026, 9, 15),
                title="Commission Meeting", status="extracted")
    db.add(m)
    db.flush()
    db.add(TranscriptChunk(meeting_id=m.id, start_seconds=10, end_seconds=20, speaker_label="TURN_0042",
                           text="The stormwater easement needs a second look.", embedding=[0.1] * 768))
    db.commit()
    sources = ask_tools.Sources()
    nums = ask_tools.search_record(db, sources, "stormwater easement")
    assert nums and sources.get(nums[0])["text"] == "The stormwater easement needs a second look."
