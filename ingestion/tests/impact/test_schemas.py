"""Schema round-trips + invariants (no heavy deps — runs in base CI)."""
import pytest
from pydantic import ValidationError

from councilhound.impact.schemas import (
    Assumption,
    EvaluationBundle,
    MetricValue,
    ModuleResult,
    ProjectSpec,
    Provenance,
)


def _prov(name="ACS 2023 B25010", vintage="2023"):
    return Provenance(source_name=name, url="https://api.census.gov", vintage=vintage)


def test_assumption_requires_bounds():
    with pytest.raises(ValidationError):
        Assumption(key="occupancy", value=0.95, basis="x", rationale="r")  # no low/high


def test_assumption_bounds_ordering_enforced():
    with pytest.raises(ValidationError):
        Assumption(key="occupancy", value=0.95, low=0.97, high=0.90, basis="x", rationale="r")


def test_module_result_accepts_all_five_module_names():
    # the M5-M7 seam: the schema already knows the follow-up modules
    for name in ("economic", "fiscal", "connectivity", "environmental", "comparables"):
        ModuleResult(module=name, metrics=[])


def test_project_spec_round_trip():
    spec = ProjectSpec(
        name="Circle Gateway",
        jurisdiction="fairfax_city_va",
        city_project_slug="circle-gateway",
        source_url="https://www.fairfaxva.gov/x",
        project_type="mixed_use",
        status="Under Review",
        proposed={"units": 261, "retail_sqft": 16530, "stories": 11, "acres": 1.64},
        extraction_confidence={"proposed.units": "high"},
        extraction_quotes={"proposed.units": "up to 261 multifamily dwelling units"},
        documents=[_prov("Staff report", "2026-05")],
    )
    again = ProjectSpec.model_validate(spec.model_dump())
    assert again.proposed.units == 261
    assert again.proposed.retail_sqft == 16530


def test_bundle_dedupes_assumptions_and_sources():
    shared = Assumption(key="occupancy_rate", value=0.95, low=0.90, high=0.97,
                        basis="industry norm", rationale="stabilized occupancy")
    p = _prov()
    m = MetricValue(name="new_households", value=248.0, unit="households",
                    provenance=[p], assumptions=["occupancy_rate"], method="units*occ")
    bundle = EvaluationBundle(
        spec=ProjectSpec(
            name="X", jurisdiction="j", city_project_slug="x", source_url="u",
            project_type="mixed_use", status="s", documents=[p],
        ),
        results=[
            ModuleResult(module="economic", metrics=[m], assumptions=[shared]),
            ModuleResult(module="fiscal", metrics=[m], assumptions=[shared]),
        ],
    )
    assert len(bundle.all_assumptions()) == 1
    assert len(bundle.all_sources()) == 1  # same (source_name, vintage) deduped
    assert len(bundle.all_metrics()) == 2
