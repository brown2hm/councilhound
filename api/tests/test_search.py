"""Hybrid search: exact-phrase keyword hits + pgvector semantic hits, with
watch links and dedupe between the two paths."""
from tests.test_endpoints import _seed


def test_keyword_and_semantic_search(client, db, monkeypatch):
    _seed(db)
    # identical vector to the seeded embeddings -> distance 0, passes the cutoff
    monkeypatch.setattr("app.routers.search.embed_query", lambda q: [0.1] * 768)

    data = client.get("/search/", params={"q": "design contract"}).json()
    kinds = {(r["kind"], r["match"]) for r in data["results"]}
    # agenda item title matches by keyword; the transcript chunk matches by
    # keyword too and must NOT be duplicated by the semantic pass
    assert ("agenda_item", "keyword") in kinds
    assert ("transcript", "keyword") in kinds
    transcript_hits = [r for r in data["results"] if r["kind"] == "transcript"]
    assert len(transcript_hits) == 1
    assert transcript_hits[0]["watch_url"].endswith("starttime=120&entrytime=120")

    # a query with no exact match still gets the semantic transcript hit
    data = client.get("/search/", params={"q": "walking path agreement"}).json()
    assert [r["match"] for r in data["results"]] == ["semantic"]

    # body filter excludes the council meeting entirely
    data = client.get("/search/", params={"q": "design contract",
                                          "body": "planning_commission"}).json()
    assert data["results"] == []


def test_search_query_validation(client, db):
    _seed(db)
    assert client.get("/search/", params={"q": "a"}).status_code == 422
