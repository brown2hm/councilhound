"""OKF knowledge bundle: file primitives, seed/refresh determinism, lint
conformance, push idempotency, and the curator's edit contract (Claude
mocked — no network)."""
import datetime
import os

import pytest

from councilhound.db.models import (
    AgendaItem,
    CityProject,
    Entity,
    EntityProfile,
    EntityUpdate,
    Meeting,
    ProjectEvaluation,
    Vote,
    WikiPage,
)
from councilhound.okf import bundle as B
from councilhound.okf import curate
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


# --- curator ---------------------------------------------------------------

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
