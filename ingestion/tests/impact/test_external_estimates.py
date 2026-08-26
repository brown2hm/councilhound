"""External-estimates extraction must see fiscal text wherever it sits.

Regression for the head-truncation miss: Davies-Property's staff fiscal
sentence sat at char ~108k of a 211k hearing packet and
Fairfax-Presbyterian-Church's at ~144k of 226k — `text[:MAX_DOC_CHARS]`
silently dropped both, and the figures had to be hand-transcribed at the
confirm gate (2026-08-22). The prompt is now built from verbatim windows
around EXTERNAL_DOC_PATTERN matches. No test here touches the network.
"""
from councilhound.impact.intake import extractor
from councilhound.impact.intake.documents import ProjectDocument
from councilhound.impact.provenance import prov

FISCAL_SENTENCE = ("Fiscal Impact: Staff estimates a net annual fiscal impact "
                   "of approximately $310,000 to the City.")
FILLER = "The submitted plat sheets describe the parcel boundary in detail. "


def _deep_doc_text(offset_chars: int = 100_000, tail_chars: int = 100_000) -> str:
    """A synthetic hearing packet whose only fiscal sentence sits past the
    per-document cap."""
    head = FILLER * (offset_chars // len(FILLER))
    tail = FILLER * (tail_chars // len(FILLER))
    return head + FISCAL_SENTENCE + tail


# --- _pattern_windows -------------------------------------------------------

def test_windows_short_document_passes_through_unchanged():
    text = "Public hearing notice. " + FILLER * 10
    assert extractor._pattern_windows(text, extractor.EXTERNAL_DOC_PATTERN) == text


def test_windows_keep_fiscal_sentence_past_the_cap():
    text = _deep_doc_text()
    assert text.index(FISCAL_SENTENCE) > extractor.MAX_DOC_CHARS  # the old slice lost it
    excerpt = extractor._pattern_windows(text, extractor.EXTERNAL_DOC_PATTERN)
    assert FISCAL_SENTENCE in excerpt
    assert "chars omitted" in excerpt
    # still bounded: windows + markers stay near the per-document cap
    assert len(excerpt) < extractor.MAX_DOC_CHARS + 2_000
    # the head anchor (project identity lives up front) is included
    assert excerpt.startswith(FILLER[:40])


def test_windows_merge_overlapping_matches_without_duplication():
    gap = FILLER * (2_000 // len(FILLER))
    text = (_deep_doc_text(offset_chars=80_000, tail_chars=0)
            + gap + "The net fiscal result is positive." + FILLER * 2_000)
    excerpt = extractor._pattern_windows(text, extractor.EXTERNAL_DOC_PATTERN)
    # the two matches are 2k apart with ±5k windows: one merged window, so
    # each sentence appears exactly once
    assert excerpt.count(FISCAL_SENTENCE) == 1
    assert excerpt.count("The net fiscal result is positive.") == 1


def test_windows_fall_back_to_head_when_label_only_selected():
    """A doc selected by label alone can have zero in-text matches; keep the
    old head slice rather than sending nothing."""
    text = FILLER * 3_000
    assert len(text) > extractor.MAX_DOC_CHARS
    excerpt = extractor._pattern_windows(text, extractor.EXTERNAL_DOC_PATTERN)
    assert excerpt.startswith(text[:1_000])
    assert "chars omitted" in excerpt
    assert len(excerpt) <= extractor.MAX_DOC_CHARS + 100


def test_windows_respect_cap_with_many_scattered_matches():
    block = FILLER * (4_000 // len(FILLER)) + "public hearing item continued. "
    text = block * 80
    assert len(text) > extractor.MAX_DOC_CHARS
    excerpt = extractor._pattern_windows(text, extractor.EXTERNAL_DOC_PATTERN)
    assert len(excerpt) < extractor.MAX_DOC_CHARS + 5_000


# --- extract_external_estimates end-to-end (mocked model) -------------------

def _honest_model(prompt: str) -> dict:
    """A model that can only quote text it was actually shown."""
    quote = "Staff estimates a net annual fiscal impact of approximately $310,000"
    if quote in prompt:
        return {"estimates": [{"source": "PC Hearing Packet", "kind": "staff_report",
                               "net_annual_low": 310000, "quote": quote}]}
    return {"estimates": []}


def _hearing_doc(text: str) -> ProjectDocument:
    label = "June 23 2025 Planning Commission Public Hearing Packet"
    return ProjectDocument(label=label, url="https://example.gov/packet.pdf",
                           text=text, provenance=prov(label, "u", "2025-06-23"))


def test_fiscal_sentence_past_cap_is_extracted(monkeypatch):
    monkeypatch.setattr(extractor, "_call_external", _honest_model)
    out, notes = extractor.extract_external_estimates(
        [_hearing_doc(_deep_doc_text())], project_name="Davies Property")
    assert len(out) == 1
    assert out[0]["net_annual_low"] == 310000
    assert out[0]["kind"] == "staff_report"
    assert any("Recorded 1 external" in n for n in notes)


def test_hallucinated_quote_still_dropped(monkeypatch):
    def liar(prompt):
        return {"estimates": [{"source": "PC Hearing Packet", "kind": "staff_report",
                               "net_annual_low": 310000,
                               "quote": "a net surplus of $9,999,999 per year"}]}
    monkeypatch.setattr(extractor, "_call_external", liar)
    out, notes = extractor.extract_external_estimates([_hearing_doc(_deep_doc_text())])
    assert out == []
    assert any("not found verbatim" in n for n in notes)
