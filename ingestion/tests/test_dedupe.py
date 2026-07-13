"""Dedup: slug normalization, resolve-time base matching, and entity merges.
The July 2026 audit found phrasing drift splitting topic threads
(courthouse-plaza x5, acronym twins like ...-prab); these pin the fixes."""
import pytest

from councilhound.db.models import (
    Entity, EntityAlias, EntityMention, EntityUpdate, Meeting,
)
from councilhound.dedupe import (
    dedupe_pass, find_normalized_base, merge_entities, normalize_slug,
)
from councilhound.entities import resolve_entity


def test_normalize_slug_strips_project_and_acronyms():
    assert normalize_slug("george-snyder-trail-project") == "george-snyder-trail"
    assert normalize_slug("urban-forest-master-plan-ufmp") == "urban-forest-master-plan"
    # acronym skips connector words: p(arks) r(ecreation) a(dvisory) b(oard)
    assert normalize_slug("parks-and-recreation-advisory-board-prab") == \
        "parks-and-recreation-advisory-board"
    assert normalize_slug("board-of-architectural-review-bar") == "board-of-architectural-review"


def test_normalize_slug_keeps_integral_words():
    # 'project' as one of only two tokens is identity, not a suffix
    assert normalize_slug("trail-project") == "trail-project"
    # wider suffixes (development, review) are NOT stripped context-free
    assert normalize_slug("economic-development") == "economic-development"
    assert normalize_slug("board-of-architectural-review") == "board-of-architectural-review"
    assert normalize_slug("courthouse-plaza-redevelopment") == "courthouse-plaza-redevelopment"


def test_find_normalized_base_requires_existing_same_type(db_session):
    s = db_session
    plaza = resolve_entity(s, "project", "Courthouse Plaza")
    # suffix strips only land on an entity that already exists...
    assert find_normalized_base(s, "project", "courthouse-plaza-redevelopment").id == plaza.id
    # ...of the same type
    assert find_normalized_base(s, "topic", "courthouse-plaza-redevelopment") is None
    # and never truncate a name whose base doesn't exist
    assert find_normalized_base(s, "topic", "economic-development-strategy") is None


def test_resolve_entity_folds_variants(db_session):
    s = db_session
    trail = resolve_entity(s, "project", "George Snyder Trail")
    # create-time normalization: 'X Project' canonicalizes to X's slug
    assert resolve_entity(s, "project", "George Snyder Trail Project").id == trail.id
    # resolve-time fallback: wider suffix hits an existing base and aliases it
    plaza = resolve_entity(s, "project", "Courthouse Plaza")
    variant = resolve_entity(s, "project", "Courthouse Plaza Redevelopment")
    assert variant.id == plaza.id
    # the drifted name is now an alias, so later hits resolve directly
    assert resolve_entity(s, "project", "Courthouse Plaza Redevelopment").id == plaza.id


def _meeting(s, day):
    m = Meeting(granicus_view_id="13", granicus_clip_id=f"c{day}", body="city_council",
                meeting_type="council_meeting", title="City Council Meeting",
                meeting_date=f"2026-01-{day:02d}")
    s.add(m)
    s.flush()
    return m


def test_merge_entities_moves_history_and_leaves_redirect(db_session):
    s = db_session
    m1, m2 = _meeting(s, 1), _meeting(s, 2)
    target = resolve_entity(s, "project", "George Snyder Trail", first_seen_meeting_id=m2.id)
    source = Entity(entity_type="project", name="George Snyder Trail Proj",
                    canonical_slug="george-snyder-trail-proj", first_seen_meeting_id=m1.id)
    s.add(source)
    s.flush()

    s.add(EntityUpdate(entity_id=target.id, meeting_id=m1.id, update_text="t@m1"))
    s.add(EntityUpdate(entity_id=source.id, meeting_id=m1.id, update_text="s@m1"))  # conflict
    s.add(EntityUpdate(entity_id=source.id, meeting_id=m2.id, update_text="s@m2",
                       status_after="canceled"))
    s.add(EntityMention(entity_id=source.id, meeting_id=m2.id, role="discussed"))
    s.flush()

    moved = merge_entities(s, "george-snyder-trail-proj", "george-snyder-trail")
    s.commit()

    assert moved["updates"] == 1  # the m1 conflict was dropped, m2 moved
    assert moved["mentions"] == 1
    assert s.query(Entity).filter_by(canonical_slug="george-snyder-trail-proj").first() is None
    # status recomputed from the merged (latest) update
    assert target.current_status == "canceled"
    # earliest first-seen wins
    assert target.first_seen_meeting_id == m1.id
    # old slug redirects: it's now an alias of the survivor
    alias = s.query(EntityAlias).filter_by(alias="george-snyder-trail-proj").one()
    assert alias.entity_id == target.id


def test_merge_refuses_cross_type_unless_forced(db_session):
    s = db_session
    resolve_entity(s, "location", "Old Town")
    resolve_entity(s, "topic", "Old Town Hall")
    with pytest.raises(ValueError, match="type mismatch"):
        merge_entities(s, "old-town-hall", "old-town")
    merge_entities(s, "old-town-hall", "old-town", force_cross_type=True)


def test_dedupe_pass_dry_run_then_apply(db_session):
    s = db_session
    resolve_entity(s, "project", "Courthouse Plaza")
    # pre-existing drift, inserted directly as older data would be
    s.add(Entity(entity_type="project", name="Courthouse Plaza Redevelopment",
                 canonical_slug="courthouse-plaza-redevelopment"))
    s.add(Entity(entity_type="topic", name="Economic Development",
                 canonical_slug="economic-development"))  # must survive
    s.flush()

    proposals = dedupe_pass(s, apply=False)
    assert [(p["source"], p["target"]) for p in proposals] == \
        [("courthouse-plaza-redevelopment", "courthouse-plaza")]
    # dry run changed nothing
    assert s.query(Entity).filter_by(canonical_slug="courthouse-plaza-redevelopment").first()

    dedupe_pass(s, apply=True)
    assert s.query(Entity).filter_by(canonical_slug="courthouse-plaza-redevelopment").first() is None
    assert s.query(Entity).filter_by(canonical_slug="economic-development").first()
