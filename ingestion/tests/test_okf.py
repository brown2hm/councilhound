"""OKF knowledge bundle: file primitives, seed/refresh determinism, lint
conformance, push idempotency, and the curator's edit contract (Claude
mocked — no network)."""
import datetime
import os
import subprocess

import pytest

from councilhound.config import SITE_BASE_URL
from councilhound.db.models import (
    AgendaItem,
    CityProject,
    Entity,
    EntityAlias,
    EntityProfile,
    EntityUpdate,
    Meeting,
    ProjectEvaluation,
    Vote,
    WikiPage,
)
from councilhound.okf import bundle as B
from councilhound.okf import curate
from councilhound.okf import sync
from councilhound.okf.export import refresh_bundle, seed_bundle, wiki_candidates
from councilhound.okf.lint import lint_bundle
from councilhound.okf.push import push_bundle


# --- pure file primitives --------------------------------------------------

def test_page_round_trip():
    fm = {"type": "development-project", "title": "Circle Gateway",
          "tags": ["rezoning"], "timestamp": "2026-06-09"}
    text = B.render_page(fm, "Body **here**.\n")
    parsed_fm, body = B.parse_page(text)
    assert parsed_fm == fm
    assert body == "Body **here**.\n"


def test_parse_page_without_frontmatter():
    fm, body = B.parse_page("# Just markdown\n")
    assert fm is None
    assert body == "# Just markdown\n"


def test_slugify():
    assert B.slugify("Net fiscal impact ($/yr)") == "net-fiscal-impact-yr"
    assert B.slugify("New households") == "new-households"


def test_markers_and_links():
    body = ("See {{metric:new-households}} and {{map:site}}, plus "
            "[history](/projects/x/history.md) and [ext](https://e.gov/a).")
    assert B.markers(body) == [("metric", "new-households"), ("map", "site")]
    assert B.bundle_links(body) == ["/projects/x/history.md"]


def test_append_log_merges_same_day(tmp_path):
    day = datetime.date(2026, 7, 19)
    B.append_log(str(tmp_path), "", ["First."], on=day)
    B.append_log(str(tmp_path), "", ["Second."], on=day)
    B.append_log(str(tmp_path), "", ["Later."], on=datetime.date(2026, 7, 20))
    text = (tmp_path / "log.md").read_text()
    assert text.count("## 2026-07-19") == 1
    assert text.index("First.") < text.index("Second.") < text.index("## 2026-07-20")


def test_write_text_reports_changes(tmp_path):
    assert B.write_text(str(tmp_path), "a.md", "one\n") is True
    assert B.write_text(str(tmp_path), "a.md", "one\n") is False
    assert B.write_text(str(tmp_path), "a.md", "two\n") is True


# --- DB-backed fixtures ----------------------------------------------------

@pytest.fixture
def project(db_session):
    entity = Entity(entity_type="project", name="Circle Gateway",
                    canonical_slug="circle-gateway", current_status="under review")
    db_session.add(entity)
    db_session.flush()
    meetings = []
    for i, day in enumerate([datetime.date(2026, 5, 12), datetime.date(2026, 6, 9)]):
        m = Meeting(granicus_clip_id=f"c{i}", granicus_view_id="13",
                    body="city_council", meeting_type="council_regular",
                    meeting_date=day, title="City Council Regular Meeting")
        db_session.add(m)
        db_session.flush()
        meetings.append(m)
    item = AgendaItem(meeting_id=meetings[1].id, label="7a",
                      title="Circle Gateway rezoning", outcome="approved 5-1",
                      start_seconds=1200)
    db_session.add(item)
    db_session.flush()
    db_session.add(Vote(meeting_id=meetings[1].id, agenda_item_id=item.id,
                        description="Motion to approve", motion_result="passed",
                        vote_breakdown={"Bates": "aye", "Hall": "nay"}))
    db_session.add_all([
        EntityUpdate(entity_id=entity.id, meeting_id=meetings[0].id,
                     update_text="Public hearing scheduled."),
        EntityUpdate(entity_id=entity.id, meeting_id=meetings[1].id,
                     agenda_item_id=item.id,
                     update_text="Rezoning approved with proffers.",
                     status_after="approved"),
    ])
    db_session.add(EntityProfile(
        entity_id=entity.id,
        summary="Circle Gateway is a mixed-use redevelopment. Council approved "
                "the rezoning on June 9.",
        open_questions=["Final site plan review"],
        member_commentary=[{"member": "Bates", "slug": None,
                            "summary": "Supported the proffer package."}],
        through_meeting_id=meetings[1].id))
    city = CityProject(external_slug="circle-gateway-official", entity_id=entity.id,
                       name="Circle Gateway", project_type="Rezoning",
                       division="Community Development", official_status="Under Review",
                       description="Official description.", address="123 Main St",
                       detail_url="https://example.gov/circle-gateway")
    db_session.add(city)
    db_session.flush()
    db_session.add(ProjectEvaluation(
        city_project_id=city.id, status="synthesized",
        module_results=[{
            "module": "economic",
            "metrics": [{"name": "New households", "value": 248.0,
                         "unit": "households", "low": 235.0, "high": 253.0,
                         "provenance": [], "assumptions": [],
                         "method": "units x occupancy", "headline": True}],
            "narrative_notes": ["screening estimate"],
        }],
        synthesized_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)))
    db_session.commit()
    return entity


def _read(bundle_dir, rel):
    return B.read_page(os.path.join(str(bundle_dir), rel))


# --- seed / refresh --------------------------------------------------------

def test_wiki_candidates_needs_record_or_timeline(db_session, project):
    thin = Entity(entity_type="project", name="One-off Mention",
                  canonical_slug="one-off-mention")
    db_session.add(thin)
    db_session.commit()
    slugs = [e.canonical_slug for e in wiki_candidates(db_session)]
    assert "circle-gateway" in slugs
    assert "one-off-mention" not in slugs


def test_seed_creates_conformant_wiki(db_session, project, tmp_path):
    result = seed_bundle(db_session, str(tmp_path))
    assert result["seeded"] == 1

    fm, body = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert fm["type"] == "development-project"
    assert fm["title"] == "Circle Gateway"
    assert fm["resource"].endswith("/development/circle-gateway-official")
    assert fm["status"] == "under review"
    assert "Official record" in body

    fm, body = _read(tmp_path, "projects/circle-gateway/history.md")
    assert fm["type"] == "project-history"
    assert fm["timestamp"] == "2026-06-09"
    assert "watch the moment" in body and "starttime=1200" in body
    assert "Vote (passed): Motion to approve — Bates: aye, Hall: nay" in body

    _, body = _read(tmp_path, "projects/circle-gateway/impact.md")
    assert "{{metric:new-households}}" in body
    assert "248" not in body  # numbers never live in prose

    _, positions = _read(tmp_path, "projects/circle-gateway/positions.md")
    assert "Final site plan review" in positions
    assert "Bates" in positions

    assert os.path.exists(tmp_path / "index.md")
    assert os.path.exists(tmp_path / "projects/index.md")
    assert os.path.exists(tmp_path / "projects/circle-gateway/index.md")
    assert "Seeded" in (tmp_path / "projects/circle-gateway/log.md").read_text()

    assert lint_bundle(str(tmp_path), db_session) == []


def test_seed_record_only_project_lints_clean(db_session, tmp_path):
    """Official record, no meeting timeline yet — no history.md, and the
    overview must not link to one (the bug the first live lint caught)."""
    entity = Entity(entity_type="project", name="Record Only",
                    canonical_slug="record-only")
    db_session.add(entity)
    db_session.flush()
    db_session.add(CityProject(external_slug="record-only-official",
                               entity_id=entity.id, name="Record Only",
                               detail_url="https://example.gov/record-only"))
    db_session.commit()
    assert seed_bundle(db_session, str(tmp_path))["seeded"] == 1
    assert not os.path.exists(tmp_path / "projects/record-only/history.md")
    _, body = _read(tmp_path, "projects/record-only/overview.md")
    assert "history.md" not in body
    assert lint_bundle(str(tmp_path), db_session) == []


def test_seed_is_idempotent_and_preserves_edits(db_session, project, tmp_path):
    seed_bundle(db_session, str(tmp_path))
    overview = tmp_path / "projects/circle-gateway/overview.md"
    edited = overview.read_text().replace(
        "mixed-use redevelopment", "mixed-use redevelopment (human note)")
    overview.write_text(edited)
    result = seed_bundle(db_session, str(tmp_path))
    assert result["seeded"] == 0 and result["skipped_existing"] == 1
    assert "(human note)" in overview.read_text()


def test_refresh_regenerates_pipeline_pages_only(db_session, project, tmp_path):
    seed_bundle(db_session, str(tmp_path))
    assert refresh_bundle(db_session, str(tmp_path)) == {
        "refreshed": 0, "unchanged": 1, "orphaned": 0}

    # a new meeting lands -> history regenerates, status frontmatter follows,
    # curated body survives
    overview = tmp_path / "projects/circle-gateway/overview.md"
    overview.write_text(overview.read_text().replace(
        "mixed-use redevelopment", "mixed-use redevelopment (human note)"))
    m = Meeting(granicus_clip_id="c9", granicus_view_id="13", body="city_council",
                meeting_type="council_regular",
                meeting_date=datetime.date(2026, 7, 14), title="City Council")
    db_session.add(m)
    db_session.flush()
    db_session.add(EntityUpdate(entity_id=project.id, meeting_id=m.id,
                                update_text="Site plan submitted.",
                                status_after="site plan review"))
    project.current_status = "site plan review"
    db_session.commit()

    result = refresh_bundle(db_session, str(tmp_path))
    assert result["refreshed"] == 1
    fm, body = _read(tmp_path, "projects/circle-gateway/history.md")
    assert fm["timestamp"] == "2026-07-14" and "Site plan submitted." in body
    fm, body = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert fm["status"] == "site plan review"
    assert "(human note)" in body
    assert "through 2026-07-14" in (
        tmp_path / "projects/circle-gateway/log.md").read_text()


# --- lint ------------------------------------------------------------------

def test_lint_catches_violations(db_session, project, tmp_path):
    seed_bundle(db_session, str(tmp_path))
    bad_dir = tmp_path / "projects/circle-gateway"
    (bad_dir / "notes.md").write_text("no frontmatter here\n")
    (bad_dir / "overview.md").write_text(
        (bad_dir / "overview.md").read_text().replace(
            "(/projects/circle-gateway/history.md)",
            "(/projects/circle-gateway/missing.md)"))
    (bad_dir / "impact.md").write_text(
        (bad_dir / "impact.md").read_text().replace(
            "{{metric:new-households}}", "{{metric:not-a-metric}}"))
    problems = "\n".join(lint_bundle(str(tmp_path), db_session))
    assert "notes.md: missing YAML frontmatter" in problems
    assert "/projects/circle-gateway/missing.md does not resolve" in problems
    assert "'not-a-metric' does not match" in problems


def test_lint_catches_invented_member_slug(db_session, project, tmp_path):
    """The curator writes member links from vote breakdowns, which carry only
    surnames — so it can invent a slug that 404s. /members resolves on
    canonical_slug alone, so an alias is a broken link there even though the
    same slug resolves through /entities."""
    seed_bundle(db_session, str(tmp_path))
    member = Entity(entity_type="person", name="Catherine Read",
                    canonical_slug="catherine-read")
    db_session.add(member)
    db_session.flush()
    db_session.add(EntityAlias(entity_id=member.id, alias="read"))
    db_session.commit()

    positions = tmp_path / "projects/circle-gateway/positions.md"
    positions.write_text(positions.read_text() + (
        f"\n- [Read]({SITE_BASE_URL}/members/read) — voted yes.\n"
        f"- [Read]({SITE_BASE_URL}/members/catherine-read) — voted yes.\n"))

    problems = "\n".join(lint_bundle(str(tmp_path), db_session))
    assert "/members/read is not a valid members page" in problems
    assert "catherine-read" not in problems


def test_lint_accepts_alias_on_topics_but_not_members(db_session, project,
                                                      tmp_path):
    """/topics goes through the alias-following _resolve_entity, so the same
    alias that is broken under /members is legitimate under /topics. A linter
    that treats every route the same gets one of these two wrong."""
    seed_bundle(db_session, str(tmp_path))
    db_session.add(EntityAlias(entity_id=project.id, alias="circle-gw"))
    db_session.commit()

    overview = tmp_path / "projects/circle-gateway/overview.md"
    overview.write_text(overview.read_text() + (
        f"\nSee [the topic]({SITE_BASE_URL}/topics/circle-gw), "
        f"[methods]({SITE_BASE_URL}/development/methods), and "
        f"[nope]({SITE_BASE_URL}/development/not-a-project).\n"))

    problems = "\n".join(lint_bundle(str(tmp_path), db_session))
    assert "circle-gw" not in problems           # alias is valid on /topics
    assert "methods" not in problems             # static route, not a slug
    assert "/development/not-a-project is not a valid development page" in problems


# --- push ------------------------------------------------------------------

def test_push_upserts_and_deletes(db_session, project, tmp_path):
    seed_bundle(db_session, str(tmp_path))
    first = push_bundle(db_session, str(tmp_path))
    assert first["created"] > 0 and first["updated"] == 0

    again = push_bundle(db_session, str(tmp_path))
    assert again["created"] == 0 and again["updated"] == 0
    assert again["unchanged"] == first["created"]

    overview = db_session.query(WikiPage).filter_by(
        path="projects/circle-gateway/overview.md").one()
    assert overview.entity_id == project.id
    assert overview.kind == "concept" and overview.page == "overview"
    assert overview.frontmatter["type"] == "development-project"
    root_index = db_session.query(WikiPage).filter_by(path="index.md").one()
    assert root_index.kind == "index" and root_index.entity_id is None

    os.remove(tmp_path / "projects/circle-gateway/impact.md")
    (tmp_path / "projects/circle-gateway/overview.md").write_text(
        B.render_page({"type": "development-project", "title": "Circle Gateway"},
                      "Edited.\n"))
    result = push_bundle(db_session, str(tmp_path))
    assert result["deleted"] == 1 and result["updated"] == 1
    assert db_session.query(WikiPage).filter_by(
        path="projects/circle-gateway/impact.md").first() is None


def test_push_resolves_renamed_slug_through_alias(db_session, project, tmp_path):
    """dedupe leaves the old slug behind as an alias when it renames an
    entity; a bundle seeded before the rename must still land."""
    seed_bundle(db_session, str(tmp_path))
    os.rename(tmp_path / "projects/circle-gateway",
              tmp_path / "projects/circle-gateway-old")
    db_session.add(EntityAlias(entity_id=project.id, alias="circle-gateway-old"))
    db_session.commit()

    result = push_bundle(db_session, str(tmp_path))
    assert result["orphaned"] == 0
    assert db_session.query(WikiPage).filter_by(
        path="projects/circle-gateway-old/overview.md").one().entity_id == project.id


def test_push_never_deletes_pages_of_an_orphan_directory(db_session, project,
                                                         tmp_path):
    """An unresolvable directory means we don't know whose pages these are —
    which is never a reason to drop a live wiki out from under the API."""
    seed_bundle(db_session, str(tmp_path))
    push_bundle(db_session, str(tmp_path))
    before = {p.path for p in db_session.query(WikiPage)
              if p.path.startswith("projects/circle-gateway/")}
    assert before

    # rename with no alias recorded: the directory now resolves to nothing
    os.rename(tmp_path / "projects/circle-gateway",
              tmp_path / "projects/circle-gateway-renamed")
    result = push_bundle(db_session, str(tmp_path))

    assert result["orphaned"] > 0
    assert result["deleted"] == 0
    assert result["retained"] == len(before)
    still_there = {p.path for p in db_session.query(WikiPage)
                   if p.path.startswith("projects/circle-gateway/")}
    assert still_there == before


# --- curator ---------------------------------------------------------------

def test_material_carries_member_links_for_vote_surnames(db_session, project):
    """Vote breakdowns key members by surname, so without this block the
    curator has to build a link itself — and what it builds 404s. Whole URLs,
    not slugs: given only a slug it produced a root-relative /members/<slug>,
    which the bundle reserves for its own pages."""
    db_session.add_all([
        Entity(entity_type="person", name="Billy Bates",
               canonical_slug="billy-bates"),
        Entity(entity_type="person", name="Stacy Hall",
               canonical_slug="stacy-hall"),
    ])
    db_session.commit()

    material, _ = curate._new_material(db_session, project,
                                       datetime.date(2026, 5, 1))
    assert "=== COUNCIL MEMBER LINKS ===" in material
    assert f"Bates -> Billy Bates | {SITE_BASE_URL}/members/billy-bates" in material
    assert f"Hall -> Stacy Hall | {SITE_BASE_URL}/members/stacy-hall" in material


def test_material_marks_unknown_and_ambiguous_members(db_session, project):
    """An unmerged spelling variant collides on surname; the seated member is
    the one carrying a title alias. Without that tiebreak the curator is told
    not to link a member it could link correctly."""
    real = Entity(entity_type="person", name="Stacey Bates",
                  canonical_slug="stacey-bates")
    dupe = Entity(entity_type="person", name="Stacy Bates",
                  canonical_slug="stacy-bates")
    db_session.add_all([real, dupe])
    db_session.flush()
    db_session.add(EntityAlias(entity_id=real.id, alias="Councilmember Bates"))
    db_session.commit()

    material, _ = curate._new_material(db_session, project,
                                       datetime.date(2026, 5, 1))
    # Bates resolves to the titled entity despite the surname collision
    assert f"Bates -> Stacey Bates | {SITE_BASE_URL}/members/stacey-bates" in material
    # Hall has no person entity at all
    assert "Hall -> no matching member; do not link" in material

    # drop the title alias and the tie becomes genuinely unresolvable
    db_session.query(EntityAlias).filter_by(entity_id=real.id).delete()
    db_session.commit()
    material, _ = curate._new_material(db_session, project,
                                       datetime.date(2026, 5, 1))
    assert "Bates -> ambiguous (Stacey Bates, Stacy Bates); do not link" in material


def _curator_response(overview_body, positions_body, summary="Noted the approval."):
    return {"overview_body": overview_body, "positions_body": positions_body,
            "edit_summary": summary}


def test_curator_applies_minimal_edit(db_session, project, tmp_path, monkeypatch):
    seed_bundle(db_session, str(tmp_path))
    m = Meeting(granicus_clip_id="c9", granicus_view_id="13", body="city_council",
                meeting_type="council_regular",
                meeting_date=datetime.date(2026, 7, 14), title="City Council")
    db_session.add(m)
    db_session.flush()
    db_session.add(EntityUpdate(entity_id=project.id, meeting_id=m.id,
                                update_text="Site plan submitted."))
    db_session.commit()

    captured = {}

    def fake_claude(prompt):
        captured["prompt"] = prompt
        _, overview_body = _read(tmp_path, "projects/circle-gateway/overview.md")
        _, positions_body = _read(tmp_path, "projects/circle-gateway/positions.md")
        return _curator_response(
            overview_body + "\nThe site plan was submitted (2026-07-14 City Council).",
            positions_body)

    monkeypatch.setattr(curate, "_call_claude", fake_claude)
    result = curate.curate_pending(db_session, str(tmp_path))
    assert result == {"updated": 1, "fresh": 0, "rejected": 0, "failed": 0}
    assert "Site plan submitted." in captured["prompt"]
    assert "Public hearing scheduled." not in captured["prompt"]  # only NEW material
    fm, body = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert "site plan was submitted" in body
    assert fm["timestamp"] == "2026-07-14"
    assert "Noted the approval." in (
        tmp_path / "projects/circle-gateway/log.md").read_text()

    # second run: nothing new since 2026-07-14 -> fresh, no LLM call needed
    monkeypatch.setattr(curate, "_call_claude",
                        lambda prompt: pytest.fail("should not be called"))
    assert curate.curate_pending(db_session, str(tmp_path))["fresh"] == 1


def test_curator_rejects_protected_region_edits(db_session, project, tmp_path,
                                                monkeypatch):
    seed_bundle(db_session, str(tmp_path))
    overview = tmp_path / "projects/circle-gateway/overview.md"
    fm, body = B.parse_page(overview.read_text())
    body += "\n<!-- curator:off -->Editor's note.<!-- /curator:off -->\n"
    overview.write_text(B.render_page(fm, body))

    m = Meeting(granicus_clip_id="c9", granicus_view_id="13", body="city_council",
                meeting_type="council_regular",
                meeting_date=datetime.date(2026, 7, 14), title="City Council")
    db_session.add(m)
    db_session.flush()
    db_session.add(EntityUpdate(entity_id=project.id, meeting_id=m.id,
                                update_text="Site plan submitted."))
    db_session.commit()

    def tampering_claude(prompt):
        _, positions_body = _read(tmp_path, "projects/circle-gateway/positions.md")
        return _curator_response(
            body.replace("Editor's note.", "Rewritten."), positions_body)

    monkeypatch.setattr(curate, "_call_claude", tampering_claude)
    result = curate.curate_pending(db_session, str(tmp_path))
    assert result["rejected"] == 1
    assert "Editor's note." in overview.read_text()  # page untouched


def test_seeded_nav_section_is_curator_protected(db_session, project, tmp_path):
    """The nav block is derived from which pages exist, so it is pipeline-owned
    even though it sits on a curator-owned page."""
    seed_bundle(db_session, str(tmp_path))
    _, body = _read(tmp_path, "projects/circle-gateway/overview.md")
    protected = B.CURATOR_OFF_RE.findall(body)
    assert len(protected) == 1
    assert "## In this wiki" in protected[0]
    assert "/projects/circle-gateway/history.md" in protected[0]


def test_refresh_backfills_markers_and_tracks_new_pages(db_session, project,
                                                        tmp_path):
    """Pages seeded before markers existed carry an unmarked nav section;
    refresh re-marks it in place and keeps its links honest as pages appear."""
    seed_bundle(db_session, str(tmp_path))
    overview = tmp_path / "projects/circle-gateway/overview.md"
    impact = tmp_path / "projects/circle-gateway/impact.md"

    # rewind to the pre-marker shape, and drop a page the nav points at
    fm, body = B.parse_page(overview.read_text())
    body = body.replace(B.CURATOR_OFF_OPEN + "\n\n", "").replace(
        "\n" + B.CURATOR_OFF_CLOSE, "")
    body = body.replace(
        "- [Impact analysis](/projects/circle-gateway/impact.md) — screening "
        "estimates with assumptions and ranges\n", "")
    overview.write_text(B.render_page(fm, body))
    assert B.CURATOR_OFF_RE.findall(body) == []

    refresh_bundle(db_session, str(tmp_path))
    _, body = _read(tmp_path, "projects/circle-gateway/overview.md")
    protected = B.CURATOR_OFF_RE.findall(body)
    assert len(protected) == 1                      # markers backfilled
    assert body.count("## In this wiki") == 1       # not duplicated
    assert impact.exists() and "/impact.md" in protected[0]   # page picked up
    assert lint_bundle(str(tmp_path), db_session) == []


def test_curator_deleting_the_nav_section_is_rejected(db_session, project,
                                                      tmp_path, monkeypatch):
    """The regression this protects against: the curator dropped the whole nav
    section while correctly editing the prose above it, and nothing caught it.
    Lint cannot — removing links creates no broken links."""
    seed_bundle(db_session, str(tmp_path))
    overview = tmp_path / "projects/circle-gateway/overview.md"
    _, before = B.parse_page(overview.read_text())

    m = Meeting(granicus_clip_id="c9", granicus_view_id="13", body="city_council",
                meeting_type="council_regular",
                meeting_date=datetime.date(2026, 7, 14), title="City Council")
    db_session.add(m)
    db_session.flush()
    db_session.add(EntityUpdate(entity_id=project.id, meeting_id=m.id,
                                update_text="Site plan submitted."))
    db_session.commit()

    def drops_the_nav(prompt):
        _, positions_body = _read(tmp_path, "projects/circle-gateway/positions.md")
        stripped = B.CURATOR_OFF_RE.sub("", before) + "\n\nNew paragraph."
        return _curator_response(stripped, positions_body)

    monkeypatch.setattr(curate, "_call_claude", drops_the_nav)
    result = curate.curate_pending(db_session, str(tmp_path))

    assert result["rejected"] == 1 and result["updated"] == 0
    _, after = B.parse_page(overview.read_text())
    assert after == before                      # nothing landed
    assert "## In this wiki" in after
    assert "New paragraph." not in after        # good prose lost with the bad


def test_refresh_recomputes_a_stale_resource_uri(db_session, project, tmp_path):
    """`resource` is derived from whether the entity still has a CityProject.
    The city dropped a project from its directory, the sync removed the row,
    and the wiki kept pointing at a page that now 404s — so refresh has to
    recompute it, on the sibling pages too."""
    seed_bundle(db_session, str(tmp_path))
    fm, _ = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert fm["resource"].endswith("/development/circle-gateway-official")

    # deleting the CityProject cascades the evaluation away, so impact.md is
    # no longer generated for this project either
    os.remove(tmp_path / "projects/circle-gateway/impact.md")
    db_session.query(CityProject).delete()
    db_session.commit()
    refresh_bundle(db_session, str(tmp_path))

    for page in ("overview", "positions"):
        fm, _ = _read(tmp_path, f"projects/circle-gateway/{page}.md")
        assert fm["resource"].endswith("/topics/circle-gateway"), page
    assert lint_bundle(str(tmp_path), db_session) == []


def test_refresh_backfills_impact_for_a_later_synthesis(db_session, project,
                                                        tmp_path):
    """seed skips directories that already exist, so an evaluation that
    synthesizes after the wiki was seeded would otherwise never get an impact
    page. Five of twenty synthesized evaluations were stranded this way."""
    db_session.query(ProjectEvaluation).delete()
    db_session.commit()
    seed_bundle(db_session, str(tmp_path))
    impact = tmp_path / "projects/circle-gateway/impact.md"
    assert not impact.exists()
    _, overview = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert "/impact.md" not in overview

    city = db_session.query(CityProject).one()
    db_session.add(ProjectEvaluation(
        city_project_id=city.id, status="synthesized",
        module_results=[{"module": "economic", "metrics": [
            {"name": "New households", "value": 248.0, "unit": "households",
             "low": 235.0, "high": 253.0, "provenance": [], "assumptions": [],
             "method": "units x occupancy", "headline": True}],
            "narrative_notes": []}],
        # midday UTC: synthesized_at.date() renders in the session's local
        # timezone, so a midnight stamp lands on the previous day west of UTC
        synthesized_at=datetime.datetime(2026, 7, 20, 12,
                                         tzinfo=datetime.timezone.utc)))
    db_session.commit()

    result = refresh_bundle(db_session, str(tmp_path))
    assert result["refreshed"] == 1
    fm, body = _read(tmp_path, "projects/circle-gateway/impact.md")
    assert fm["type"] == "project-impact"
    assert fm["timestamp"] == "2026-07-20"
    assert "{{metric:new-households}}" in body and "248" not in body
    # the nav rebuild runs after the write, so the page links itself
    _, overview = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert "/projects/circle-gateway/impact.md" in overview
    assert "Added impact analysis" in (
        tmp_path / "projects/circle-gateway/log.md").read_text()
    assert lint_bundle(str(tmp_path), db_session) == []

    # curator-owned once it exists: a second pass must not overwrite edits
    impact.write_text(impact.read_text() + "\nHand-written caveat.\n")
    refresh_bundle(db_session, str(tmp_path))
    assert "Hand-written caveat." in impact.read_text()


def test_documents_page_is_pipeline_owned_and_stable(db_session, project,
                                                     tmp_path):
    """483 documents across 31 projects live only in CityProject.documents;
    nothing else in the product indexes them."""
    city = db_session.query(CityProject).one()
    city.documents = [
        {"label": "February 15, 2022 Master Development Plan (PDF, 25MB)",
         "url": "https://example.gov/files/mdp.pdf"},
        {"label": "Traffic Impact Study [revised] (PDF, 9MB)",
         "url": "https://example.gov/files/tis.pdf"},
        {"label": "", "url": "https://example.gov/files/unlabelled.pdf"},
        {"label": "Broken entry with no url", "url": ""},
    ]
    db_session.commit()
    seed_bundle(db_session, str(tmp_path))

    fm, body = _read(tmp_path, "projects/circle-gateway/documents.md")
    assert fm["type"] == "project-documents"
    assert "Pipeline-owned" in body
    assert "[February 15, 2022 Master Development Plan (PDF, 25MB)](https://example.gov/files/mdp.pdf)" in body
    assert "\\[revised\\]" in body          # brackets escaped, link intact
    assert "unlabelled.pdf](https://example.gov/files/unlabelled.pdf)" in body
    assert "Broken entry" not in body        # no url, no entry
    assert "/projects/circle-gateway/documents.md" in _read(
        tmp_path, "projects/circle-gateway/overview.md")[1]
    assert lint_bundle(str(tmp_path), db_session) == []

    # timestamp must not churn, or refresh is permanently dirty and the sync
    # loop loses its no-op
    stamped = fm["timestamp"]
    assert refresh_bundle(db_session, str(tmp_path))["refreshed"] == 0
    assert _read(tmp_path, "projects/circle-gateway/documents.md")[0][
        "timestamp"] == stamped

    # pipeline-owned: a hand edit is regenerated away, unlike impact.md
    doc = tmp_path / "projects/circle-gateway/documents.md"
    doc.write_text(doc.read_text().replace("Traffic Impact Study", "Tampered"))
    assert refresh_bundle(db_session, str(tmp_path))["refreshed"] == 1
    assert "Tampered" not in doc.read_text()

    # a newly published document re-dates the page
    city.documents = city.documents + [
        {"label": "Staff Report (PDF, 1MB)", "url": "https://example.gov/sr.pdf"}]
    db_session.commit()
    refresh_bundle(db_session, str(tmp_path))
    fm, body = _read(tmp_path, "projects/circle-gateway/documents.md")
    assert "Staff Report" in body
    assert fm["description"].startswith("5 document")


def test_no_documents_means_no_page(db_session, project, tmp_path):
    city = db_session.query(CityProject).one()
    city.documents = []
    db_session.commit()
    seed_bundle(db_session, str(tmp_path))
    assert not os.path.exists(tmp_path / "projects/circle-gateway/documents.md")
    _, overview = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert "/documents.md" not in overview


def test_facts_table_renders_only_populated_fields(db_session, project,
                                                   tmp_path):
    """Confidence is only meaningful on fields that have a value: in prod all
    110 `low` grades sit on null fields, meaning "could not find it". Render a
    null row and the column fills with noise."""
    ev = db_session.query(ProjectEvaluation).one()
    ev.spec = {
        "existing": {"use": "Two commercial buildings", "units": 0,
                     "sqft": 12000.0, "assessed_value": None},
        "proposed": {"units": 261, "retail_sqft": 16530.0, "stories": 11,
                     "acres": 1.64, "office_sqft": None,
                     "parking_spaces": None, "affordable_units": 16},
        "parcels": ["48 3 08    002 B"],
        "extraction_confidence": {"existing.units": "medium",
                                  "proposed.units": "high",
                                  "proposed.office_sqft": "low",
                                  "existing.assessed_value": "low"},
        "extraction_quotes": {
            "existing.units": "two existing commercial buildings",
            "proposed.units": "There are 261 multifamily homes"},
    }
    db_session.commit()
    seed_bundle(db_session, str(tmp_path))
    _, body = _read(tmp_path, "projects/circle-gateway/overview.md")

    assert "## Proposal at a glance" in body
    assert "| Dwelling units | 0 _(medium confidence)_ | 261 |" in body
    assert "| Retail | — | 16,530 sq ft |" in body
    assert "| Site area | — | 1.64 acres |" in body
    assert "Office" not in body          # null on both sides: no row
    assert "Parking spaces" not in body
    assert "assessed" not in body
    # high is the norm and goes unannotated; only weaker grades are marked,
    # which the Dwelling units row above shows on the existing side alone
    assert body.count("confidence)_") == 1
    assert "48 3 08 002 B" in body       # internal whitespace collapsed

    # a row can carry a quote on each side; unlabelled they read as
    # contradicting one another
    assert '- **Dwelling units** (existing) — "two existing commercial buildings"' in body
    assert '- **Dwelling units** (proposed) — "There are 261 multifamily homes"' in body

    # sits above the official record, and is protected like the nav
    assert body.index("## Proposal at a glance") < body.index("## Official record")
    protected = B.CURATOR_OFF_RE.findall(body)
    assert len(protected) == 2
    assert any("Proposal at a glance" in r for r in protected)
    assert lint_bundle(str(tmp_path), db_session) == []


def test_facts_table_is_refreshed_in_place(db_session, project, tmp_path):
    """Pipeline-owned: a revised submission updates the table without
    disturbing the curator's prose, and a curator deleting it is rejected."""
    ev = db_session.query(ProjectEvaluation).one()
    ev.spec = {"proposed": {"units": 261}, "extraction_confidence": {}}
    db_session.commit()
    seed_bundle(db_session, str(tmp_path))

    overview = tmp_path / "projects/circle-gateway/overview.md"
    fm, body = B.parse_page(overview.read_text())
    overview.write_text(B.render_page(fm, body + "\n\nCurator paragraph.\n"))

    ev.spec = {"proposed": {"units": 240, "stories": 11},
               "extraction_confidence": {}}
    db_session.commit()
    assert refresh_bundle(db_session, str(tmp_path))["refreshed"] == 1

    _, body = B.parse_page(overview.read_text())
    assert "| Dwelling units | — | 240 |" in body
    assert "| Stories | — | 11 |" in body
    assert "261" not in body
    assert "Curator paragraph." in body        # prose untouched
    assert len(B.CURATOR_OFF_RE.findall(body)) == 2
    assert refresh_bundle(db_session, str(tmp_path))["refreshed"] == 0   # no-op


def test_no_spec_means_no_facts_table(db_session, project, tmp_path):
    db_session.query(ProjectEvaluation).delete()
    db_session.commit()
    seed_bundle(db_session, str(tmp_path))
    _, body = _read(tmp_path, "projects/circle-gateway/overview.md")
    assert "Proposal at a glance" not in body
    assert len(B.CURATOR_OFF_RE.findall(body)) == 1   # nav only


# --- sync loop -------------------------------------------------------------

def _init_repo(tmp_path):
    """A throwaway repo so the loop's git steps act on nothing real."""
    root = tmp_path / "repo"
    (root / "knowledge").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / ".gitkeep").write_text("")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root, str(root / "knowledge")


def test_sync_commits_and_pushes(db_session, project, tmp_path, monkeypatch):
    root, bundle = _init_repo(tmp_path)
    seed_bundle(db_session, bundle)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)
    monkeypatch.setattr(sync, "curate_pending",
                        lambda *a, **k: {"updated": 0, "fresh": 1,
                                         "rejected": 0, "failed": 0})

    result = sync.sync_bundle(db_session, bundle)
    assert result["ok"] and result["aborted"] is None
    assert result["pushed"]["created"] > 0
    assert db_session.query(WikiPage).count() > 0


def test_sync_lint_failure_blocks_commit_and_push(db_session, project, tmp_path,
                                                  monkeypatch):
    """Lint is the only automated check between an LLM edit and a live page,
    so a failing bundle must reach neither git nor prod."""
    root, bundle = _init_repo(tmp_path)
    seed_bundle(db_session, bundle)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    def _break_a_page(session, bundle_dir, limit=None):
        page = os.path.join(bundle_dir, "projects/circle-gateway/positions.md")
        with open(page, "a") as f:
            f.write(f"\n- [Ghost]({SITE_BASE_URL}/members/not-a-member)\n")
        return {"updated": 1, "fresh": 0, "rejected": 0, "failed": 0}

    monkeypatch.setattr(sync, "curate_pending", _break_a_page)
    result = sync.sync_bundle(db_session, bundle)

    assert result["ok"] is False
    assert "lint problem" in result["aborted"]
    assert "not-a-member" in "\n".join(result["lint_problems"])
    assert "commit" not in result
    assert "pushed" not in result
    assert db_session.query(WikiPage).count() == 0
    # HEAD untouched, and the bad edit is still on disk to inspect
    now = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    assert now == head
    assert "not-a-member" in open(
        os.path.join(bundle, "projects/circle-gateway/positions.md")).read()


def test_sync_refuses_a_dirty_bundle(db_session, project, tmp_path):
    """The commit must contain only what this run produced."""
    root, bundle = _init_repo(tmp_path)
    seed_bundle(db_session, bundle)  # left uncommitted
    result = sync.sync_bundle(db_session, bundle)
    assert result["ok"] is False
    assert "uncommitted changes" in result["aborted"]
    assert "refreshed" not in result  # bailed before touching anything


def test_sync_reports_candidates_without_a_wiki(db_session, project, tmp_path,
                                                monkeypatch):
    """New projects never appear on their own — refresh only walks existing
    directories — so the loop has to say so rather than silently stagnate."""
    root, bundle = _init_repo(tmp_path)
    seed_bundle(db_session, bundle)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)
    monkeypatch.setattr(sync, "curate_pending", lambda *a, **k: {"updated": 0})

    newcomer = Entity(entity_type="project", name="Newcomer",
                      canonical_slug="newcomer")
    db_session.add(newcomer)
    db_session.flush()
    meeting = db_session.query(Meeting).first()
    db_session.add(CityProject(external_slug="newcomer-official",
                               entity_id=newcomer.id, name="Newcomer",
                               detail_url="https://example.gov/newcomer"))
    db_session.commit()

    result = sync.sync_bundle(db_session, bundle, push=False)
    assert result["ok"]
    assert result["unseeded_candidates"] == ["newcomer"]
    assert not os.path.exists(os.path.join(bundle, "projects/newcomer"))

    result = sync.sync_bundle(db_session, bundle, seed=True, push=False)
    assert result["seeded"]["seeded"] == 1
    assert os.path.exists(os.path.join(bundle, "projects/newcomer/overview.md"))
