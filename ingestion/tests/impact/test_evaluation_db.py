"""ProjectEvaluation lifecycle round-trip against the scratch Postgres."""
import copy

from councilhound.db.models import CityProject, ProjectEvaluation
from councilhound.impact import evaluate
from councilhound.impact.schemas import ExternalEstimate, ProjectSpec


def test_evaluation_lifecycle_round_trip(db_session):
    project = CityProject(external_slug="circle-gateway", name="Circle Gateway",
                          detail_url="https://example.gov/circle-gateway")
    db_session.add(project)
    db_session.flush()

    evaluation = ProjectEvaluation(
        city_project_id=project.id,
        status="extracted",
        spec={"name": "Circle Gateway", "proposed": {"units": 261}},
        extraction_model="claude-sonnet-4-6",
        extraction_prompt_version="v1",
    )
    db_session.add(evaluation)
    db_session.commit()

    row = db_session.query(ProjectEvaluation).one()
    assert row.status == "extracted"
    assert row.spec["proposed"]["units"] == 261
    assert row.created_at is not None

    row.status = "synthesized"
    row.module_results = [{"module": "economic", "metrics": []}]
    row.map_layers = {"site": {"type": "FeatureCollection", "features": []}}
    row.assumptions = [{"key": "occupancy_rate", "value": 0.95}]
    row.report_markdown = "# Report"
    db_session.commit()

    again = db_session.query(ProjectEvaluation).one()
    assert again.map_layers["site"]["type"] == "FeatureCollection"
    assert again.report_markdown.startswith("# Report")

    # cascade: deleting the project removes its evaluation
    db_session.delete(project)
    db_session.commit()
    assert db_session.query(ProjectEvaluation).count() == 0


# --- enrich: status demotion only on an actual spec change ------------------

ESTIMATE = {"source": "Staff Report June 2025", "kind": "staff_report",
            "net_annual_low": 310000.0, "net_annual_high": None,
            "revenue_total": None, "expenditure_total": None,
            "assessed_value": None, "construction_cost": None, "fy": None,
            "quote": "net annual fiscal impact of approximately $310,000",
            "url": "https://example.gov/staff.pdf"}


def _seed_synthesized(db_session, slug="circle-gateway"):
    project = CityProject(external_slug=slug, name="Circle Gateway",
                          detail_url=f"https://example.gov/{slug}")
    db_session.add(project)
    db_session.flush()
    spec = ProjectSpec(name="Circle Gateway", jurisdiction="fairfax_city_va",
                       city_project_slug=slug,
                       source_url=f"https://example.gov/{slug}",
                       project_type="mixed_use", status="approved",
                       external_estimates=[ExternalEstimate(**ESTIMATE)])
    evaluation = ProjectEvaluation(city_project_id=project.id, status="synthesized",
                                   spec=spec.model_dump(mode="json"),
                                   extraction_model="claude-sonnet-4-6",
                                   extraction_prompt_version="v3")
    db_session.add(evaluation)
    db_session.commit()
    return evaluation


def _patch_enrich_io(monkeypatch, tmp_path, estimates):
    monkeypatch.setattr("councilhound.impact.intake.documents.gather_documents",
                        lambda project, session=None: [])
    monkeypatch.setattr(
        "councilhound.impact.intake.extractor.extract_external_estimates",
        lambda docs, project_name=None: (estimates, ["Recorded some estimate(s)"]))
    monkeypatch.setattr(evaluate, "_spec_yaml_path",
                        lambda slug: tmp_path / f"{slug}.yaml")


def test_enrich_noop_keeps_synthesized_status(db_session, monkeypatch, tmp_path):
    """Re-running the backfill when the extraction lands on the same estimates
    must not demote synthesized->confirmed (forcing a needless re-confirm and
    re-evaluate) nor pile duplicate notes onto the spec."""
    evaluation = _seed_synthesized(db_session)
    before_spec = copy.deepcopy(evaluation.spec)
    _patch_enrich_io(monkeypatch, tmp_path, [dict(ESTIMATE)])

    out = evaluate.enrich(db_session, "circle-gateway", external=True)

    assert "no changes" in out
    row = db_session.query(ProjectEvaluation).one()
    assert row.status == "synthesized"
    assert row.spec == before_spec  # no note buildup on a no-op run
    assert not (tmp_path / "circle-gateway.yaml").exists()


def test_enrich_change_reopens_confirm_gate(db_session, monkeypatch, tmp_path):
    evaluation = _seed_synthesized(db_session)
    revised = dict(ESTIMATE, net_annual_low=280000.0,
                   quote="a revised net annual fiscal impact of $280,000")
    _patch_enrich_io(monkeypatch, tmp_path, [revised])

    out = evaluate.enrich(db_session, "circle-gateway", external=True)

    assert "impact-confirm" in out
    row = db_session.query(ProjectEvaluation).one()
    assert row.status == "confirmed"
    assert row.spec["external_estimates"][0]["net_annual_low"] == 280000.0
    assert (tmp_path / "circle-gateway.yaml").exists()
