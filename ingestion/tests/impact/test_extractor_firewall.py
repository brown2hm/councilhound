"""The LLM firewall: numbers survive only with a verifiable verbatim quote.

These tests never touch the network — enforce_firewall is pure, and the
doctored-document test mocks the anthropic call entirely (brief §8's
'LLM firewall test').
"""
from councilhound.impact.intake import extractor
from councilhound.impact.intake.documents import ProjectDocument
from councilhound.impact.provenance import prov

CORPUS = """\
Staff Report, May 2026.
The applicant proposes up to 261 multifamily dwelling units above
approximately 16,530 square feet of ground floor commercial space in an
11-story building on a 1.64 acre site at Fairfax Circle.
"""


def _entry(value, quote, confidence="high"):
    return {"value": value, "confidence": confidence, "source_quote": quote}


def _raw(**overrides):
    base = {f.replace(".", "_"): _entry(None, None, "low") for f in extractor.NUMERIC_FIELDS}
    base.update(overrides)
    return base


def test_verbatim_quote_passes():
    raw = _raw(proposed_units=_entry(261, "up to 261 multifamily dwelling units"))
    cleaned, notes = extractor.enforce_firewall(raw, CORPUS)
    assert cleaned["proposed.units"]["value"] == 261
    assert notes == []


def test_missing_quote_demotes():
    raw = _raw(proposed_units=_entry(261, None))
    cleaned, notes = extractor.enforce_firewall(raw, CORPUS)
    assert cleaned["proposed.units"]["value"] is None
    assert cleaned["proposed.units"]["confidence"] == "low"
    assert any("no source quote" in n for n in notes)


def test_fabricated_quote_demotes():
    raw = _raw(proposed_parking_spaces=_entry(400, "400 structured parking spaces provided"))
    cleaned, notes = extractor.enforce_firewall(raw, CORPUS)
    assert cleaned["proposed.parking_spaces"]["value"] is None
    assert any("not found verbatim" in n for n in notes)


def test_overlong_quote_demotes():
    long_quote = " ".join(["word"] * 16)
    raw = _raw(proposed_units=_entry(261, long_quote))
    cleaned, notes = extractor.enforce_firewall(raw, CORPUS)
    assert cleaned["proposed.units"]["value"] is None
    assert any("longer than 15 words" in n for n in notes)


def test_quote_matching_is_punctuation_tolerant():
    raw = _raw(proposed_retail_sqft=_entry(
        16530, "approximately 16,530 square feet of ground floor commercial"))
    cleaned, notes = extractor.enforce_firewall(raw, CORPUS)
    assert cleaned["proposed.retail_sqft"]["value"] == 16530
    assert notes == []


def test_doctored_document_missing_units_yields_null(monkeypatch):
    """Brief §8: feed a staff report with the unit count removed -> the field
    must come back null/low, never a plausible number."""
    doctored = CORPUS.replace("up to 261 multifamily dwelling units above\n", "")

    def fake_claude(prompt):
        # a 'helpful' model inventing the number it remembers from elsewhere,
        # with a quote that is not in the doctored text
        return _raw(
            proposed_units=_entry(261, "up to 261 multifamily dwelling units"),
            proposed_stories=_entry(11, "an\n11-story building".replace("\n", " ")),
        )

    monkeypatch.setattr(extractor, "_call_claude", fake_claude)
    docs = [ProjectDocument(label="Staff report", url="u", text=doctored,
                            provenance=prov("Staff report", "u", "2026-05"))]
    result = extractor.extract_spec_fields(docs)
    assert result["fields"]["proposed.units"]["value"] is None
    assert result["fields"]["proposed.units"]["confidence"] == "low"
    # the legitimately-present fact survives
    assert result["fields"]["proposed.stories"]["value"] == 11


def test_unverifiable_pins_dropped(monkeypatch):
    def fake_claude(prompt):
        raw = _raw()
        raw["parcel_pins"] = ["57 4 02 015", "99 9 99 999"]
        return raw

    monkeypatch.setattr(extractor, "_call_claude", fake_claude)
    docs = [ProjectDocument(label="d", url="u", text="Tax Map Parcel 57 4 02 015.",
                            provenance=prov("d", "u", "x"))]
    result = extractor.extract_spec_fields(docs)
    assert result["parcel_pins"] == ["57 4 02 015"]
    assert any("99 9 99 999" in n for n in result["notes"])


CORRIDOR_CORPUS = """\
Staff Report, June 2026. The project constructs a protected bike lane on
Main Street between University Drive and Chain Bridge Road, approximately
2,600 feet of new facility.
"""


def test_string_firewall_verbatim_street_names_pass():
    raw = {"corridor_street_name": "Main Street",
           "corridor_from_street": "University Drive",
           "corridor_to_street": "Chain Bridge Road"}
    cleaned, notes = extractor.enforce_string_firewall(raw, CORRIDOR_CORPUS)
    assert cleaned["corridor.street_name"] == "Main Street"
    assert cleaned["corridor.from_street"] == "University Drive"
    assert cleaned["corridor.to_street"] == "Chain Bridge Road"
    assert notes == []


def test_string_firewall_invented_street_nulled():
    raw = {"corridor_street_name": "Oak Avenue",  # not in the documents
           "corridor_from_street": None, "corridor_to_street": None}
    cleaned, notes = extractor.enforce_string_firewall(raw, CORRIDOR_CORPUS)
    assert cleaned["corridor.street_name"] is None
    assert any("not found verbatim" in n for n in notes)


def test_string_firewall_non_string_nulled():
    raw = {"corridor_street_name": 42,
           "corridor_from_street": None, "corridor_to_street": None}
    cleaned, notes = extractor.enforce_string_firewall(raw, CORRIDOR_CORPUS)
    assert cleaned["corridor.street_name"] is None
    assert any("non-string" in n for n in notes)


def test_unverifiable_facilities_dropped(monkeypatch):
    def fake_claude(prompt):
        raw = _raw()
        raw["corridor_street_name"] = "Main Street"
        raw["corridor_facilities"] = ["protected bike lane", "cycle superhighway"]
        return raw

    monkeypatch.setattr(extractor, "_call_claude", fake_claude)
    docs = [ProjectDocument(label="d", url="u", text=CORRIDOR_CORPUS,
                            provenance=prov("d", "u", "x"))]
    result = extractor.extract_spec_fields(docs)
    assert result["corridor_facilities"] == ["protected bike lane"]
    assert result["strings"]["corridor.street_name"] == "Main Street"
    assert any("cycle superhighway" in n for n in result["notes"])
