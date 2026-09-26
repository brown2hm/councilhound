"""The County registry's self-reference stoplist: the County and its
boards are actors, its schools and its neighbour city stay topics."""
from councilhound.bodies import Registry
from councilhound.jurisdiction import JurisdictionConfig


def test_county_self_reference():
    reg = Registry.from_config(JurisdictionConfig.load("fairfax_county_va"))
    for name in ("Fairfax County", "the County", "Board of Supervisors", "Fairfax County Board of Supervisors",
                 "Planning Commission", "BZA", "Fairfax County Park Authority", "Land Use Policy Committee"):
        assert reg.is_self_reference(name), name
    for name in ("Fairfax County Public Schools", "FCPS", "City of Fairfax", "Tysons", "Reston Town Center",
                 "Fairfax County Parkway", "Sully District", None):
        assert not reg.is_self_reference(name), name
