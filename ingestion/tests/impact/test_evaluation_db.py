"""ProjectEvaluation lifecycle round-trip against the scratch Postgres."""
from councilhound.db.models import CityProject, ProjectEvaluation


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
