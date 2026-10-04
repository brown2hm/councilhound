"""Speaker naming reads titles from the jurisdiction's roster config, so
the County's supervisors and commissioners are recognized like the
City's councilmembers. Each registry is built straight from its YAML, so
these run under any JURISDICTION."""
import pytest

from councilhound.bodies import Registry
from councilhound.extraction import speaker_names as sn
from councilhound.jurisdiction import JurisdictionConfig


@pytest.fixture(scope="module")
def city():
    return Registry.from_config(JurisdictionConfig.load("fairfax_city_va"))


@pytest.fixture(scope="module")
def county():
    return Registry.from_config(JurisdictionConfig.load("fairfax_county_va"))


def test_city_titles_match_what_the_hand_written_patterns_did(city):
    titles = sn.body_titles(city)
    for alias in ("Mayor Read", "Councilmember Hall", "Council Member Bates", "Councilwoman McQuillen"):
        assert titles["city_council"].match(alias), alias
    assert titles["planning_commission"].match("Commissioner Rice")
    assert titles["school_board"].match("School Board Member Hickman")
    assert not titles["city_council"].match("Commissioner Rice")
    assert not titles["planning_commission"].match("Councilmember Hall")
    anyone = sn.any_title(city)
    for alias in ("Mayor Read", "Chair Feather", "Vice-Chair Lockhart", "Trustee Smith", "Superintendent Jones"):
        assert anyone.match(alias), alias
    assert not anyone.match("Thomas Peterson")
    assert sn.example_title(city) == "Councilmember"


def test_county_titles_cover_supervisors_commissioners_and_districts(county):
    titles = sn.body_titles(county)
    assert set(titles) == {"board_of_supervisors", "planning_commission"}
    bos, pc = titles["board_of_supervisors"], titles["planning_commission"]
    for alias in ("Supervisor Lusk", "Chairman McKay", "Chair McKay", "Sully District Supervisor",
                  "Mount Vernon District Supervisor"):
        assert bos.match(alias) and not pc.match(alias), alias
    for alias in ("Commissioner Cortina", "Commission Chair Niedzielski-Eichner", "Vice Chair Spain",
                  "Braddock District Commissioner"):
        assert pc.match(alias) and not bos.match(alias), alias
    assert not bos.match("Councilmember Hall")
    assert sn.any_title(county).match("Hunter Mill District Supervisor")
    assert sn.example_title(county) == "Supervisor"


def test_county_titles_are_not_mistaken_for_names(county):
    words = sn.honorifics(county)
    assert {"supervisor", "chairman", "commissioner"} <= words
    assert not {"lusk", "mckay"} & words
