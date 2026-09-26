"""County roster parsing: last names + districts on the annotated agenda,
resolved against the pinned roster."""
from councilhound.bodies import Registry
from councilhound.jurisdiction import JurisdictionConfig
from councilhound.seed import parse_roster, surname_forms

AGENDA = """FAIRFAX COUNTY
BOARD OF SUPERVISORS
August 25, 2026
AGENDA
10:00
Done
Matters Presented by Board Members
1.
Done
Chairman McKay
2.
Done
Supervisor Smith, Sully District
3.
Done
Supervisor Sizemore Heizer, Braddock District
4.
Done
Supervisor Bierman, Dranesville District
5.
Done
Supervisor Nobody, Nowhere District
"""


def county_body():
    cfg = JurisdictionConfig.load("fairfax_county_va")
    return Registry.from_config(cfg).bodies["board_of_supervisors"]


def test_bos_lines_resolve_against_static_roster():
    body = county_body()
    roster = parse_roster(AGENDA, body)
    assert roster["chairman"] == ["Jeffrey C. McKay"]
    assert roster["supervisor"] == ["Kathy L. Smith", "Rachna Sizemore Heizer", "James N. Bierman, Jr."]


def test_bos_falls_back_to_the_static_roster_when_nothing_parses():
    body = county_body()
    roster = parse_roster("Agenda with no member block", body)
    assert roster["chairman"] == ["Jeffrey C. McKay"] and len(roster["supervisor"]) == 9


def test_surname_forms_handle_two_word_surnames_and_suffixes():
    assert surname_forms("Rachna Sizemore Heizer") == ["Heizer", "Sizemore Heizer"]
    assert surname_forms("James N. Bierman, Jr.") == ["Bierman"]
    assert surname_forms("Pat Herrity") == ["Herrity"]
    assert surname_forms("Catherine S. Read") == ["Read"]


def test_seed_titles_for_county_roles():
    body = county_body()
    assert body.seed_titles("chairman") == ["Chairman", "Chair"]
    assert body.seed_titles("supervisor") == ["Supervisor"]
