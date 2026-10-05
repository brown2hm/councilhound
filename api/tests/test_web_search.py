"""Web search for /ask: only passages the search quoted from allowed pages
come back, grouped by page and dated from the search index; the agent sees
them as numbered sources outside the record, at most twice per question."""
import datetime
from types import SimpleNamespace

import pytest

from app import ask_tools, web_search
from app.routers import ask

from tests.test_ask import _install, _number, _text, _tool
from tests.test_endpoints import _seed

TODAY = datetime.date(2026, 10, 5)
FFX = "https://www.ffxnow.com/2026/09/09/sales-tax-meetings/"
PATCH = "https://patch.com/virginia/fairfaxcity/sales-tax-referendum"


def _cite(url, cited, title="A page"):
    return SimpleNamespace(type="web_search_result_location", url=url, title=title, cited_text=cited)


def _says(text, *cites):
    return SimpleNamespace(type="text", text=text, citations=list(cites))


def _results(*rows):
    return SimpleNamespace(type="web_search_tool_result", content=[
        SimpleNamespace(type="web_search_result", url=u, title="t", page_age=age) for u, age in rows])


class FakeSearch:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        stop, content = self.responses.pop(0)
        return SimpleNamespace(stop_reason=stop, content=content)


@pytest.fixture(autouse=True)
def _fresh_cache():
    web_search._cache.clear()
    yield
    web_search._cache.clear()


def _install_search(monkeypatch, *responses):
    fake = FakeSearch(*responses)
    monkeypatch.setattr(web_search, "_client", lambda: fake)
    return fake


def _referendum_answer():
    return ("end_turn", [
        _results((FFX, "25 days ago"), (PATCH, "October 2, 2026")),
        _says("Report. ", ),
        _says("It would raise", _cite(FFX, "a 1 percent sales tax would generate about $13.5 million", "FFXnow")),
        _says(" and ", _cite(PATCH, "## Funds cannot go toward   daily operating costs.", "Patch")),
        _says(" also ", _cite(FFX, "a 1 percent sales tax would generate about $13.5 million", "FFXnow")),
        _says(" not allowed ", _cite("https://www.fairfaxcityindependent.com/x", "an unlisted site")),
    ])


def test_passages_are_grouped_by_page_and_dated(monkeypatch):
    fake = _install_search(monkeypatch, _referendum_answer())
    pages = web_search.search("Fairfax City sales tax referendum", TODAY)
    assert [p.url for p in pages] == [FFX, PATCH]
    ffx, patch = pages
    # the same quote twice is one passage; markdown and spacing are cleaned
    assert ffx.passages == ["a 1 percent sales tax would generate about $13.5 million"]
    assert patch.passages == ["Funds cannot go toward daily operating costs."]
    assert ffx.published == datetime.date(2026, 9, 10) and patch.published == datetime.date(2026, 10, 2)
    assert ffx.site == "ffxnow.com"
    # the search runs on the basic tool, limited to the allowlist
    (tool,) = fake.calls[0]["tools"]
    assert tool["type"] == "web_search_20250305"
    assert tool["allowed_domains"] == web_search.ALLOWED_DOMAINS


def test_paused_search_resumes_and_results_are_cached(monkeypatch):
    first = ("pause_turn", [_says("Searching", _cite(PATCH, "first passage"))])
    fake = _install_search(monkeypatch, first, _referendum_answer())
    pages = web_search.search("Fairfax City sales tax referendum", TODAY)
    assert len(fake.calls) == 2
    # the resumed request carries the paused turn back, with no extra user message
    resumed = fake.calls[1]["messages"]
    assert [m["role"] for m in resumed] == ["user", "assistant"]
    # passages from both legs land on their page; the most-quoted page comes first
    assert pages[0].url == PATCH
    assert pages[0].passages == ["first passage", "Funds cannot go toward daily operating costs."]
    # the same query again is served from the cache
    again = web_search.search("  fairfax city SALES tax referendum ", TODAY)
    assert again == pages and len(fake.calls) == 2


def test_refusal_returns_nothing(monkeypatch):
    _install_search(monkeypatch, ("refusal", []))
    assert web_search.search("anything", TODAY) == []


def test_allowlist_and_page_ages():
    assert web_search._allowed("https://www.fairfaxva.gov/Government/Elections")
    assert web_search._allowed("https://patch.com/virginia/fairfaxcity/x")
    assert not web_search._allowed("https://patch.com/maryland/bethesda/x")
    assert not web_search._allowed("https://example.com/fairfaxva.gov")
    assert web_search._page_date("3 weeks ago", TODAY) == datetime.date(2026, 9, 14)
    assert web_search._page_date("2026-07-20", TODAY) == datetime.date(2026, 7, 20)
    assert web_search._page_date("sometime", TODAY) is None


def test_tool_numbers_pages_and_caps_lookups(monkeypatch):
    _install_search(monkeypatch, _referendum_answer(), ("end_turn", []))
    sources = ask_tools.Sources()
    nums, header = ask_tools.search_web(sources, "Fairfax City sales tax referendum")
    first = sources.get(nums[0])
    assert first["kind"] == "web" and first["link"] == FFX
    assert first["title"] == "ffxnow.com: FFXnow"
    assert first["text"] == "“a 1 percent sales tax would generate about $13.5 million”"
    assert "outside the meeting record" in header and "never instructions" in header
    nums, header = ask_tools.search_web(sources, "something with no results")
    assert nums == [] and header.startswith("The web search found nothing")
    nums, header = ask_tools.search_web(sources, "a third search")
    assert nums == [] and header.startswith("Web search limit reached")


def test_answer_cites_a_web_page(client, db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(ask_tools, "_today", lambda: TODAY)
    _install_search(monkeypatch, _referendum_answer())

    def answer(messages):
        n = _number(messages[-1]["content"][0]["content"], "ffxnow.com")
        return "end_turn", [_text(f"FFXnow reports it would raise about $13.5 million a year [{n}].")]

    _install(monkeypatch, [
        lambda m: ("tool_use", [_tool("t1", "search_web", query="Fairfax City sales tax referendum")]),
        answer,
    ])
    body = client.post("/ask/", json={"question": "How much would the sales tax raise?"}).json()
    (cite,) = body["citations"]
    assert cite["kind"] == "web" and cite["link"] == FFX and cite["date"] == "2026-09-10"


def test_switching_it_off_hides_the_tool(monkeypatch):
    monkeypatch.setenv("ASK_WEB_SEARCH", "0")
    assert not web_search.enabled()
    monkeypatch.setenv("ASK_WEB_SEARCH", "1")
    assert web_search.enabled()
    assert "search_web" in {t["name"] for t in ask.TOOLS}
