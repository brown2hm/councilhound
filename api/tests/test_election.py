"""The election page: every contest and candidate in ballot order, member
pages linked only on a full-name match, and questionnaires that put every
candidate in a race on the same footing, agreeing with what the candidate
table says was and wasn't found."""
from councilhound.db.models import Entity, EntityAlias

from app import candidates, questionnaires, terms


def _ballot_order(contest: str) -> list[str]:
    body, label = candidates.CONTESTS[contest]
    return list(dict(terms.TERMS[body].candidates)[label])


# ---------------------------------------------------------------- the data

def test_questionnaires_cover_their_race_alike():
    keys = set()
    for q in questionnaires.QUESTIONNAIRES:
        assert q.key not in keys
        keys.add(q.key)
        assert q.contest in candidates.CONTESTS
        assert q.url.startswith("https://") and q.questions
        asked = [k for k, _ in q.questions]
        assert len(set(asked)) == len(asked), q.key
        in_race = {c.ballot_name for c in candidates.in_contest(q.contest)}
        seen = set()
        for r in q.responses:
            assert r.candidate in in_race, (q.key, r.candidate)
            assert r.candidate not in seen, (q.key, r.candidate)
            seen.add(r.candidate)
            # an answer (or a recorded blank) for every question, nothing else
            assert [k for k, _ in r.answers] == asked, (q.key, r.candidate)
            assert any(a for _, a in r.answers), (q.key, r.candidate)
            for k, a in r.answers:
                if a is not None:
                    assert a.strip() == a and a, (q.key, r.candidate, k)
                    # short paraphrases, comparable across candidates
                    assert len(a) <= 280, (q.key, r.candidate, k, len(a))


def test_questionnaires_agree_with_the_candidate_table():
    """A candidate who answered Vote411 isn't listed as 'not yet responded',
    and one who didn't, is; same for the 2026 Patch questionnaire."""
    answered = {(q.publisher, r.candidate) for q in questionnaires.QUESTIONNAIRES for r in q.responses}
    for q in questionnaires.QUESTIONNAIRES:
        for c in candidates.in_contest(q.contest):
            gaps = " ".join(c.not_found).lower()
            if q.publisher == questionnaires.VOTE411:
                assert ((q.publisher, c.ballot_name) in answered) != (candidates._NO_VOTE411 in c.not_found), \
                    c.ballot_name
            if q.publisher == questionnaires.PATCH:
                assert ((q.publisher, c.ballot_name) in answered) != ("patch candidate questionnaire" in gaps), \
                    c.ballot_name


def test_officeholders_have_an_official_source():
    """Anyone who holds a City seat has the City's own page about them, so
    the card never says 'Official record: none found' for a sitting member."""
    for c in candidates.CANDIDATES:
        if c.incumbent:
            assert any(s.kind == "official" for s in c.sources), c.ballot_name


# ---------------------------------------------------------------- the page

def test_election_lists_every_contest_in_ballot_order(client):
    e = client.get("/election/").json()
    assert [c["key"] for c in e["contests"]] == list(candidates.CONTESTS)
    for c in e["contests"]:
        assert [x["ballot_name"] for x in c["candidates"]] == _ballot_order(c["key"])
        assert c["election_date"] == "2026-11-03"
        for q in c["questionnaires"]:
            # every candidate in the race has a row, respondents or not
            assert [r["candidate"] for r in q["responses"]] == _ballot_order(c["key"])
            for r in q["responses"]:
                if r["responded"]:
                    assert set(r["answers"]) == {x["key"] for x in q["questions"]}
                else:
                    assert r["answers"] == {} and r["url"] == q["url"]
    by_key = {c["key"]: c for c in e["contests"]}
    assert by_key["mayor"]["vote_for"] == 1
    assert by_key["city_council"]["vote_for"] == 6
    assert by_key["school_board"]["vote_for"] == 5
    assert e["voting"]["facts"]


def test_member_pages_link_on_full_name_only(client, db):
    hall = Entity(entity_type="person", name="Stacy R. Hall", canonical_slug="stacy-hall")
    # a different Brown on the roster must not become Sandi Slappey Brown
    brown = Entity(entity_type="person", name="Jon Brown", canonical_slug="jon-brown")
    db.add_all([hall, brown])
    db.flush()
    db.add_all([
        EntityAlias(entity_id=hall.id, alias="Councilmember Hall"),
        EntityAlias(entity_id=brown.id, alias="Commissioner Brown"),
    ])
    db.commit()

    e = client.get("/election/").json()
    cands = {x["ballot_name"]: x for c in e["contests"] for x in c["candidates"]}
    assert cands["Stacy R. Hall"]["member"] == {"slug": "stacy-hall", "roles": ["Councilmember"]}
    assert cands["Sandi W. Slappey Brown"]["member"] is None
    assert cands["Jessica L. Lough"]["member"] is None
