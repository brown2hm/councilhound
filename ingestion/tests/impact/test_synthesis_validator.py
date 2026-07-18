"""Report number-validation: drafts may only state traceable numbers."""
import pytest

from councilhound.impact.schemas import (
    Assumption, EvaluationBundle, MetricValue, ModuleResult, ProjectSpec, Provenance,
)
from councilhound.impact.synthesis import report as report_mod
from councilhound.impact.synthesis.validate import extract_numbers, validate_report


def _bundle():
    p = Provenance(source_name="test", url="u", vintage="2026")
    return EvaluationBundle(
        spec=ProjectSpec(
            name="Circle Gateway", jurisdiction="fairfax_city_va",
            city_project_slug="circle-gateway", source_url="u",
            project_type="mixed_use", status="Under Review",
            proposed={"units": 261, "retail_sqft": 16530, "stories": 11, "acres": 1.64},
        ),
        results=[ModuleResult(
            module="economic",
            metrics=[
                MetricValue(name="New households", value=247.95, unit="households",
                            low=234.9, high=253.17, provenance=[p],
                            assumptions=["occupancy_rate"], method="m"),
                MetricValue(name="In-city capture share: food_away", value=0.72,
                            unit="fraction", low=0.6, high=0.85, provenance=[p], method="m"),
            ],
            assumptions=[Assumption(key="occupancy_rate", value=0.95, low=0.90, high=0.97,
                                    basis="b", rationale="r")],
        )],
    )


def test_traceable_numbers_pass():
    draft = ("The project proposes 261 units over 16,530 sq ft of retail in an "
             "11-story building on 1.64 acres, yielding roughly 248 new households "
             "(234.9-253.2 range) at 95% occupancy. About 72% of dining spend stays "
             "in the city.")
    assert validate_report(draft, _bundle()) == []


def test_invented_number_flagged():
    draft = "The project will generate $4,250,000 in new annual tax revenue."
    violations = validate_report(draft, _bundle())
    assert len(violations) == 1
    assert "4250000" in violations[0].replace(",", "").replace(".0", "")


def test_magnitude_suffixes_extracted():
    numbers = dict((v, c) for v, c in extract_numbers("costs $1.2 million and 30k more"))
    assert 1_200_000.0 in numbers
    assert 30_000.0 in numbers


def test_regeneration_path(monkeypatch):
    bundle = _bundle()
    calls = []

    def fake_claude(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "An invented $9,999,123 figure appears here beside the 261 units."
        return "The 261 units yield roughly 248 new households."

    monkeypatch.setattr(report_mod, "_call_claude", fake_claude)
    markdown, model, version = report_mod.synthesize_report(bundle)
    assert len(calls) == 2
    assert "REJECTED" in calls[1]
    assert "9,999,123" not in markdown


def test_hard_fail_after_second_violation(monkeypatch):
    monkeypatch.setattr(report_mod, "_call_claude",
                        lambda prompt: "Still claiming $9,999,123 in revenue.")
    with pytest.raises(RuntimeError, match="untraceable"):
        report_mod.synthesize_report(_bundle())
