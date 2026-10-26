"""Candidate forums: the pinned transcripts name only candidates on the
ballot, every quote links to its moment in the video, search_forums puts
every candidate's answer to a question side by side in ballot order, and
the election page and get_candidate say who spoke and who did not."""
from app import ask_tools, candidates, forums


def _ballot_index() -> dict[str, int]:
    return {c.ballot_name: i for i, c in enumerate(candidates.CANDIDATES)}


# ---------------------------------------------------------------- the data

def test_turns_are_candidates_in_the_forums_contests():
    order = _ballot_index()
    for f in forums.FORUMS:
        assert f.video.startswith("https://www.youtube.com/watch?v=")
        assert f.turns and f.questions
        running = {c.ballot_name for k in f.contests for c in candidates.in_contest(k)}
        ids = [q.id for q in f.questions]
        assert len(set(ids)) == len(ids), f.key
        last = -1
        for t in f.turns:
            assert t.speaker in running, (f.key, t.speaker)
            assert t.question in ids, (f.key, t.start)
            assert t.start >= last and t.end > t.start, (f.key, t.start)
            last = t.start
            assert t.parts and all(text.strip() == text and text for _, text in t.parts), (f.key, t.start)
            assert [s for s, _ in t.parts] == sorted(s for s, _ in t.parts), (f.key, t.start)
            assert t.parts[0][0] >= t.start - 1 and t.parts[-1][0] <= t.end, (f.key, t.start)
        for name, note in f.absent:
            assert name in running and name not in {t.speaker for t in f.turns} and note
        assert set(f.speakers()) | {n for n, _ in f.absent} <= running
        assert all(order[a] < order[b] for a, b in zip(f.speakers(), f.speakers()[1:]))


def test_candidates_night_has_every_mayor_and_council_candidate_but_kim():
    night = next(f for f in forums.FORUMS if f.key == "candidates_night_2026_09_30")
    running = [c.ballot_name for k in ("mayor", "city_council") for c in candidates.in_contest(k)]
    assert night.speakers() == [n for n in running if n != "Stephen S. Kim"]
    assert [n for n, _ in night.absent] == ["Stephen S. Kim"]
    # one opening statement each
    assert sorted(t.speaker for t in night.turns) == sorted(night.speakers())


def test_mayoral_forum_answers_alternate_between_the_two():
    f = next(f for f in forums.FORUMS if f.key == "mayoral_forum_2026_10_07")
    assert f.speakers() == ["Kirsten Sides Lockhart", 'Thomas D. "Tom" Peterson']
    for q in f.questions:
        if q.asked:  # every moderator question was put to both
            assert {t.speaker for t in f.turns if t.question == q.id} == set(f.speakers()), q.id


def test_links_point_at_the_moment():
    f = forums.FORUMS[0]
    assert f.link(754) == f.video + "&t=754s"
    assert f.link(-3).endswith("&t=0s")


def test_passages_are_consecutive_whole_sentences():
    for f in forums.FORUMS:
        for t in f.turns:
            ps = forums.passages(t, f)
            assert " ".join(p.text for p in ps) == t.text
            assert ps[0].start == t.parts[0][0]


# ---------------------------------------------------------------- Ask

def test_a_forum_question_brings_both_answers_in_ballot_order():
    sources = ask_tools.Sources()
    nums, header = ask_tools.search_forums(sources, "taxes and revenue", contest="mayor")
    got = [sources.get(n) for n in nums]
    mayoral = [s for s in got if "Mayoral Candidate Forum" in s["title"]]
    speakers = [s["title"].split(" at the ")[0] for s in mayoral]
    assert set(speakers) == {"Kirsten Sides Lockhart", 'Thomas D. "Tom" Peterson'}
    assert speakers == sorted(speakers, key=_ballot_index().get)
    for s in got:
        assert s["kind"] == "forum" and "&t=" in s["link"] and s["start_seconds"] is not None
        assert s["text"].startswith("“") and "(automatic transcript)" in s["text"]
    assert "every answer to the question on" in header
    assert forums.TRANSCRIPT_NOTE in header


def test_quotes_are_the_transcript_words():
    sources = ask_tools.Sources()
    nums, _ = ask_tools.search_forums(sources, "tree canopy", candidate="Peterson")
    assert nums
    f = next(f for f in forums.FORUMS if f.key == "mayoral_forum_2026_10_07")
    said = " ".join(t.text for t in f.turns)
    for n in nums:
        s = sources.get(n)
        quoted = s["text"][1:s["text"].index("” (automatic transcript)")]
        assert quoted.rstrip(" …") in said
        assert s["title"].startswith('Thomas D. "Tom" Peterson at the ')


def test_a_candidate_alone_gets_opening_statements():
    sources = ask_tools.Sources()
    nums, header = ask_tools.search_forums(sources, candidate="Lough")
    assert [sources.get(n)["title"].split(",")[0] for n in nums] == ["Jessica L. Lough at the Candidates Night"]
    assert "opening statements" in header


def test_an_absent_candidate_is_said_so():
    nums, header = ask_tools.search_forums(ask_tools.Sources(), "taxes", candidate="Stephen Kim")
    assert nums == [] and "not able to attend" in header


def test_get_candidate_says_where_they_spoke():
    sources = ask_tools.Sources()
    nums, _ = ask_tools.get_candidate(sources, "Lockhart")
    summary = sources.get(nums[0])["text"]
    assert "Spoke at the Candidates Night (2026-09-30" in summary
    assert "Spoke at the Mayoral Candidate Forum (2026-10-07" in summary
    nums, _ = ask_tools.get_candidate(sources, "Stephen Kim")
    assert "Did not speak at the Candidates Night (2026-09-30): The emcee said" in sources.get(nums[0])["text"]


# ---------------------------------------------------------------- the page

def test_election_page_carries_each_contests_forums(client):
    e = client.get("/election/").json()
    by_key = {c["key"]: c for c in e["contests"]}
    assert [f["key"] for f in by_key["mayor"]["forums"]] == ["mayoral_forum_2026_10_07",
                                                             "candidates_night_2026_09_30"]
    assert by_key["school_board"]["forums"] == []
    council = by_key["city_council"]["forums"][0]
    assert council["absent"] == [{"candidate": "Stephen S. Kim",
                                  "note": "The emcee said Stephen Kim was not able to attend."}]
    assert council["silent"] == []
    (opening,) = council["questions"]
    names = [a["candidate"] for a in opening["answers"]]
    assert names == [c.ballot_name for c in candidates.in_contest("city_council") if c.ballot_name != "Stephen S. Kim"]
    # the mayor's tab of Candidates Night shows only the mayoral candidates
    night = by_key["mayor"]["forums"][1]
    assert [a["candidate"] for a in night["questions"][0]["answers"]] == [
        "Kirsten Sides Lockhart", 'Thomas D. "Tom" Peterson']
    turn = opening["answers"][0]["turns"][0]
    assert turn["link"].endswith(f"&t={turn['start']}s") and turn["text"]
