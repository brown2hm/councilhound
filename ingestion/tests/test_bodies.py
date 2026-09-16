"""The body registry and the self-reference stoplist derived from it."""
from councilhound.bodies import BODIES, BODY_KEYS, BODY_LABELS, is_self_reference, label


def test_registry_shape():
    assert BODY_KEYS[:2] == ("city_council", "planning_commission")
    assert BODY_LABELS["school_board"] == "School Board"
    assert label("prab") == "Parks and Recreation Advisory Board"
    assert label("electoral_board") == "electoral_board" and label(None) == ""
    assert all(b.archive_section.endswith("Meetings") for b in BODIES.values())


def test_self_reference_matches_the_city_and_its_bodies():
    for name in ("City of Fairfax", "the City of Fairfax", "Fairfax County", "City Council",
                 "Fairfax City Council", "City of Fairfax School Board", "Planning Commission",
                 "PRAB", "Housing and Healthy Communities Advisory Board", "Board of Zoning Appeals",
                 "BZA", "  school board. "):
        assert is_self_reference(name), name


def test_self_reference_leaves_real_topics_alone():
    for name in ("Fairfax High School", "Fairfax County Public Schools", "FCPS Tuition Bill",
                 "City Hall Renovation", "Van Dyck Park", "Council Chambers Audio Upgrade",
                 "School Board Budget", "", None):
        assert not is_self_reference(name), name
