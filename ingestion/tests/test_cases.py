"""Compound case-number names: split into the cases they list, so each links
to its official record (the County's PLUS zoning cases)."""
import datetime

import pytest

from councilhound.cases import case_parent_pairs, split_case_name
from councilhound.db.models import CityProject, Document, Entity, EntityAlias, EntityUpdate, Extraction, Meeting
from councilhound.jurisdiction import CaseNumbers
from councilhound.extraction import llm_structure as ls

RZPA = ["RZPA"]


@pytest.mark.parametrize("name, primaries, parents", [
    ("RZ-2017-HM-020 (RZPA-2025-HM-00031)", ["RZ-2017-HM-020"], ["RZPA-2025-HM-00031"]),
    ("PCA-84-L-020-29/CDPA-84-L-020-10", ["PCA-84-L-020-29", "CDPA-84-L-020-10"], []),
    ("PCA/CDPA-2018-HM-020", ["PCA-2018-HM-020", "CDPA-2018-HM-020"], []),
    ("SE 2025-FR-00037", ["SE-2025-FR-00037"], []),
    ("RZPA-2025-FR-00035", [], ["RZPA-2025-FR-00035"]),
    ("CPA-86-C-121-14-02 (RZPA-2025-HM-00032)", ["CPA-86-C-121-14-02"], ["RZPA-2025-HM-00032"]),
    # real County agenda titles: stray spaces, "Con. W/", a cut-off parenthesis
    ("RZ/FDP-2025-HM-00002 & PCA-79-C-090-03 Con. W/ PCA-77-C-019-03 (RZPA-2025-HM-00010)",
     ["RZ-2025-HM-00002", "FDP-2025-HM-00002", "PCA-79-C-090-03", "PCA-77-C-019-03"], ["RZPA-2025-HM-00010"]),
    ("PCA 77-C-098-06 (RZPA-2025- DR-00046)/ RZ/FDP-2025- DR-00017 / PCA 80-C-028- 09 (RZPA-2025- DR-00049",
     ["PCA-77-C-098-06", "RZ-2025-DR-00017", "FDP-2025-DR-00017", "PCA-80-C-028-09"],
     ["RZPA-2025-DR-00046", "RZPA-2025-DR-00049"]),
])
def test_split_case_name(name, primaries, parents):
    ref = split_case_name(name, RZPA)
    assert ref.primaries == primaries and ref.parents == parents


@pytest.mark.parametrize("name", [
    "SSPA 2023-I-1A Gallows Road Annandale Planning District",  # a plan with a name
    "Ordinance 2026-04", "FY 2026 Carryover Review", "Route 7 Widening", "I-66 Express Lanes",
    "", None,
])
def test_names_that_are_not_case_lists_are_left_alone(name):
    assert split_case_name(name, RZPA) is None


def _meeting(session, clip, date=datetime.date(2026, 9, 15)):
    m = Meeting(granicus_clip_id=clip, granicus_view_id="7", body="board_of_supervisors",
                meeting_type="bos_meeting", meeting_date=date, title="Board", status="fetched")
    session.add(m)
    session.flush()
    session.add(Document(meeting_id=m.id, doc_type="minutes", source_url=f"https://x/{clip}",
                         raw_text="minutes"))
    session.flush()
    return m


def _official(session, case):
    from councilhound.entities import resolve_entity
    e = resolve_entity(session, "project", case)
    session.add(CityProject(external_slug=case.lower(), name=case, detail_url="https://plus/x",
                            entity_id=e.id))
    session.flush()
    return e


def _data(*names):
    return {"summary": "s", "agenda_items": [{
        "label": "1", "title": "Public hearing", "outcome": "Approved",
        "entities": [{"entity_type": "case_number", "name": n, "update_text": f"{n} approved.",
                      "status_after": "approved"} for n in names]}]}


@pytest.fixture
def county_cases(monkeypatch):
    monkeypatch.setattr(ls, "CASE_NUMBERS", CaseNumbers(parent_prefixes=["RZPA"]))


def _updates(session, entity):
    return session.query(EntityUpdate).filter_by(entity_id=entity.id).count()


def test_compound_names_attach_to_each_official_case(db_session, county_cases):
    s = db_session
    rz = _official(s, "RZ-2017-HM-020")
    pca = _official(s, "PCA-84-L-020-29")
    cdpa = _official(s, "CDPA-84-L-020-10")
    m = _meeting(s, "1")
    ls.apply_extraction(s, m, _data("RZ-2017-HM-020 (RZPA-2025-HM-00031)",
                                    "PCA-84-L-020-29/CDPA-84-L-020-10"))
    assert (_updates(s, rz), _updates(s, pca), _updates(s, cdpa)) == (1, 1, 1)
    # no stray entities under the compound spellings
    assert not s.query(Entity).filter(Entity.name.like("%(%")).count()
    assert not s.query(Entity).filter(Entity.name.like("%/%")).count()
    # the umbrella number and the compound spelling now find the case
    aliases = {a.alias for a in s.query(EntityAlias).filter_by(entity_id=rz.id)}
    assert {"RZPA-2025-HM-00031", "RZ-2017-HM-020 (RZPA-2025-HM-00031)"} <= aliases


def test_a_bare_umbrella_number_later_resolves_to_its_case(db_session, county_cases):
    s = db_session
    rz = _official(s, "RZ-2017-HM-020")
    ls.apply_extraction(s, _meeting(s, "1"), _data("RZ-2017-HM-020 (RZPA-2025-HM-00031)"))
    ls.apply_extraction(s, _meeting(s, "2", datetime.date(2026, 9, 22)), _data("RZPA-2025-HM-00031"))
    assert _updates(s, rz) == 2


def test_a_bare_umbrella_number_seen_first_is_folded_in(db_session, county_cases):
    """The bare number arrived first (its own entity); a later meeting
    prints it with its case, and the stray folds into the case."""
    s = db_session
    rz = _official(s, "RZ-2017-HM-020")
    ls.apply_extraction(s, _meeting(s, "1"), _data("RZPA-2025-HM-00031"))
    assert s.query(Entity).filter_by(canonical_slug="rzpa-2025-hm-00031").count() == 1
    ls.apply_extraction(s, _meeting(s, "2", datetime.date(2026, 9, 22)),
                        _data("RZ-2017-HM-020 (RZPA-2025-HM-00031)"))
    assert s.query(Entity).filter_by(canonical_slug="rzpa-2025-hm-00031").count() == 0
    assert _updates(s, rz) == 2


def test_without_a_grammar_names_resolve_verbatim(db_session, monkeypatch):
    monkeypatch.setattr(ls, "CASE_NUMBERS", None)
    s = db_session
    ls.apply_extraction(s, _meeting(s, "1"), _data("PCA-84-L-020-29/CDPA-84-L-020-10"))
    assert s.query(Entity).filter_by(name="PCA-84-L-020-29/CDPA-84-L-020-10").count() == 1


def test_normalize_case_entities_repairs_existing_rows(db_session, monkeypatch):
    """Rows made before splitting: compound entities merge into their first
    case, stored extractions re-apply so each listed case gets its update,
    and old slugs stay as aliases."""
    from councilhound.dedupe import normalize_case_entities

    s = db_session
    monkeypatch.setattr(ls, "CASE_NUMBERS", None)  # the old behavior
    m = _meeting(s, "1")
    data = _data("RZ-2017-HM-020 (RZPA-2025-HM-00031)", "PCA-84-L-020-29/CDPA-84-L-020-10")
    ls.apply_extraction(s, m, data)
    s.add(Extraction(meeting_id=m.id, prompt_version=ls.PROMPT_VERSION, raw_json=data))
    rz = _official(s, "RZ-2017-HM-020")
    cdpa = _official(s, "CDPA-84-L-020-10")
    s.commit()

    monkeypatch.setattr(ls, "CASE_NUMBERS", CaseNumbers(parent_prefixes=["RZPA"]))
    dry = normalize_case_entities(s, apply=False)
    from councilhound.entities import slugify
    assert {d["source"] for d in dry["merges"]} == {
        slugify("RZ-2017-HM-020 (RZPA-2025-HM-00031)"), slugify("PCA-84-L-020-29/CDPA-84-L-020-10")}
    assert dry["meetings_reapplied"] == 0

    done = normalize_case_entities(s, apply=True)
    assert done["meetings_reapplied"] == 1
    assert _updates(s, rz) == 1 and _updates(s, cdpa) == 1
    pca = s.query(Entity).filter_by(canonical_slug="pca-84-l-020-29").one()
    assert _updates(s, pca) == 1
    assert not s.query(Entity).filter(Entity.canonical_slug.like("%rzpa%")).count()
    old = s.query(EntityAlias).filter_by(alias="rz-2017-hm-020-rzpa-2025-hm-00031").one()
    assert old.entity_id == rz.id  # the old URL still resolves


def test_normalize_is_a_no_op_without_a_grammar(db_session, monkeypatch):
    from councilhound.dedupe import normalize_case_entities
    monkeypatch.setattr(ls, "CASE_NUMBERS", None)
    assert "skipped" in normalize_case_entities(db_session, apply=True)


@pytest.mark.parametrize("title, pairs", [
    ("Public Hearing on PCA-2023-PR-00010 (RZPA-2026-PR-00013) (Tri Pointe Homes DC Metro, Inc.) (Providence District)",
     [(["PCA-2023-PR-00010"], "RZPA-2026-PR-00013")]),
    ("Public Hearing on PCA/CDPA-2018-HM-020 (RZPA-2025-HM-00055) (Tri Pointe Homes DC Metro, Inc.)",
     [(["PCA-2018-HM-020", "CDPA-2018-HM-020"], "RZPA-2025-HM-00055")]),
    ("Public Hearing on RZ-2025-DR-00012 (CPA Coppermine 3 Lender, LLC) (Dranesville District) "
     "(Concurrent with PCA-85-C-008-04 (RZPA-2025-DR-00087))",
     [(["PCA-85-C-008-04"], "RZPA-2025-DR-00087")]),
    ("Public Hearing on PCA-84-L-020-29/CDPA-84-L-020-10 (RZPA-2025-FR- 00035) – BP Kingstowne",
     [(["PCA-84-L-020-29", "CDPA-84-L-020-10"], "RZPA-2025-FR-00035")]),
    ("Public Hearing on SE-2026-PR-00019 (DICK'S Sporting Goods, Inc.) (Providence District)", []),
    ("(RZPA-2025-HM-00031) with no case before it", []),
    (None, []),
])
def test_case_parent_pairs_in_item_titles(title, pairs):
    assert case_parent_pairs(title, ["RZPA"]) == pairs


def test_item_titles_fold_a_bare_umbrella_number(db_session, county_cases):
    """The extractor named only the umbrella number; the item title pairs it
    with its case, so the mention lands on the case."""
    s = db_session
    pca = _official(s, "PCA-2023-PR-00010")
    data = _data("RZPA-2026-PR-00013")
    data["agenda_items"][0]["title"] = ("Public Hearing on PCA-2023-PR-00010 (RZPA-2026-PR-00013) "
                                        "(Tri Pointe Homes DC Metro, Inc.) (Providence District)")
    ls.apply_extraction(s, _meeting(s, "1"), data)
    assert _updates(s, pca) == 1
    assert not s.query(Entity).filter_by(canonical_slug="rzpa-2026-pr-00013").count()
