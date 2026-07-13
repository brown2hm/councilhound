"""Entity resolution rules — the dedup logic that keeps 'Mayor Read',
'Catherine S. Read', and 'the George Snyder Trail' from becoming separate
entities. Regressions here silently split topic timelines."""
from councilhound.entities import add_alias, display_name, resolve_entity, slugify


def test_slugify_normalization():
    assert slugify("Catherine S. Read") == "catherine-read"
    assert slugify("D. Thomas Ross") == "thomas-ross"
    assert slugify("Jon R. Stehle, Jr.") == "jon-stehle-jr"
    assert slugify("Stacey D. Hardy-Chandler") == "stacey-hardy-chandler"
    # leading articles don't identify anything
    assert slugify("the George Snyder Trail") == slugify("George Snyder Trail")
    assert slugify("An Urban Forest Master Plan") == slugify("Urban Forest Master Plan")
    # numbers survive (ordinances, case numbers)
    assert slugify("Ordinance 2026-04") == "ordinance-2026-04"


def test_display_name():
    assert display_name("Catherine S. Read") == "Catherine Read"
    assert display_name("D. Thomas Ross") == "Thomas Ross"
    assert display_name("Jon R. Stehle, Jr.") == "Jon Stehle Jr"


def test_resolution_slug_then_alias_then_create(db_session):
    s = db_session
    mayor = resolve_entity(s, "person", "Catherine S. Read")
    add_alias(s, mayor, "Mayor Read")

    # exact slug (different surface form, same slug)
    assert resolve_entity(s, "person", "Catherine Read").id == mayor.id
    # alias hit
    assert resolve_entity(s, "person", "Mayor Read").id == mayor.id
    # miss with create=False
    assert resolve_entity(s, "person", "Someone Unknown", create=False) is None
    # miss with create -> new entity + self-aliases
    other = resolve_entity(s, "person", "Billy M. Bates")
    assert other.id != mayor.id
    assert other.canonical_slug == "billy-bates"


def test_alias_collision_is_skipped(db_session):
    """An alias already owned by another entity must not be reassigned —
    ambiguous names must resolve to nobody rather than the wrong one."""
    s = db_session
    a = resolve_entity(s, "person", "Stacy R. Hall")
    b = resolve_entity(s, "person", "Robert Hall")
    add_alias(s, a, "Hall")
    add_alias(s, b, "Hall")  # collision: must be ignored, not stolen
    assert resolve_entity(s, "person", "Hall", create=False).id == a.id
