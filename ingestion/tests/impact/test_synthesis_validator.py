"""Report number-validation: drafts may only state traceable numbers."""
import pytest

from councilhound.impact.schemas import (
    Assumption, EvaluationBundle, MetricValue, ModuleResult, ProjectSpec, Provenance,
)
from councilhound.impact.synthesis import report as report_mod
from councilhound.impact.synthesis.validate import (extract_numbers,
                                                    validate_method_claims,
                                                    validate_report)


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


def test_k12_grade_range_not_read_as_magnitude():
    """'K-12' and its en/em-dash variants are a grade range, not a k-suffix:
    '7.9 K-12 students' means 7.9 students, never 7,900."""
    for dash in ("-", "–", "—"):
        values = [v for v, _ in extract_numbers(f"an estimated 7.9 K{dash}12 students")]
        assert 7.9 in values
        assert 7900.0 not in values


def test_comma_grouped_decimal_matches_as_one_number():
    """'70,707.78' is one number, not '70,707' plus an orphan '78'."""
    values = [v for v, _ in extract_numbers("generates $70,707.78 per year")]
    assert 70707.78 in values
    assert 78.0 not in values


def test_parcel_pins_are_quotable():
    """A draft citing a spec parcel PIN must validate — the leading '57' of
    '57 2 18 001 A' is a document-sourced identifier, not an invented number."""
    bundle = _bundle()
    bundle.spec.parcels = ["57 2 18 001 A"]
    draft = "The project is associated with parcel 57 2 18 001 A."
    assert validate_report(draft, bundle) == []


def test_k12_students_draft_passes():
    """A residential draft citing the K-12 student estimate with an en-dash
    grade range must validate (regression: en-dash 'K–12' parsed as 7,900)."""
    bundle = _bundle()
    bundle.results[0].metrics.append(
        MetricValue(name="Estimated K-12 students", value=7.9, unit="students",
                    low=3.9, high=11.8, provenance=bundle.results[0].metrics[0].provenance,
                    assumptions=["occupancy_rate"], method="m"))
    draft = "The project adds an estimated 7.9 K–12 students (range: 3.9–11.8)."
    assert validate_report(draft, bundle) == []


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


# --- method claims: the failure the number validator cannot see -------------


def _claims_bundle(method="units x assessed value per unit + retail sqft x $/sqft",
                   label="Residential value"):
    p = Provenance(source_name="test", url="u", vintage="2026")
    return EvaluationBundle(
        spec=ProjectSpec(
            name="City Centre West", jurisdiction="fairfax_city_va",
            city_project_slug="ccw", source_url="u",
            project_type="mixed_use", status="Approved",
            proposed={"units": 79, "retail_sqft": 7731, "office_sqft": 36862},
        ),
        results=[ModuleResult(
            module="fiscal",
            metrics=[MetricValue(
                name="Projected assessed value", value=1000.0, unit="$",
                provenance=[p], method=method,
                adjust=[{"value": 1000.0, "exps": {}, "label": label}])],
        )],
    )


def test_unsupported_inclusion_claim_is_flagged():
    """The exact sentence that shipped: the fiscal module never read
    proposed.office_sqft, yet the draft said it was accounted for — and the
    number itself was a real spec quantity, so number validation passed."""
    bundle = _claims_bundle()
    draft = ("The proposed 36,862 square feet of office space is accounted for in "
             "the tax value estimate but not converted to an on-site job count.")
    flags = validate_method_claims(draft, bundle)
    assert any("office" in f for f in flags)


def test_inclusion_claim_passes_when_the_method_names_the_input():
    bundle = _claims_bundle(
        method="units x value per unit + retail sqft x $/sqft + office sqft x $/sqft",
        label="Office/non-retail commercial value")
    draft = ("The proposed 36,862 square feet of office space is accounted for in "
             "the tax value estimate.")
    assert validate_method_claims(draft, bundle) == []


def test_plain_description_is_not_flagged():
    bundle = _claims_bundle()
    draft = ("The project proposes 36,862 square feet of office space. Residential "
             "value is estimated from assessment comps.")
    assert validate_method_claims(draft, bundle) == []


def test_claim_grounded_by_a_narrative_note_passes():
    bundle = _claims_bundle()
    bundle.results[0].narrative_notes = [
        "Parking is not counted in any revenue or cost line in this version."]
    draft = "Parking is not counted in the fiscal estimates."
    assert validate_method_claims(draft, bundle) == []


def test_external_estimate_numbers_are_quotable():
    p = Provenance(source_name="test", url="u", vintage="2026")
    bundle = EvaluationBundle(
        spec=ProjectSpec(
            name="City Centre West", jurisdiction="fairfax_city_va",
            city_project_slug="ccw", source_url="u",
            project_type="mixed_use", status="Approved",
            proposed={"units": 79},
            external_estimates=[{
                "source": "July 11 2023 staff report", "kind": "staff_report",
                "net_annual_low": 543000, "net_annual_high": 741000,
                "quote": "ranges from $543,000 and $741,000 annually"}],
        ),
        results=[ModuleResult(module="fiscal", metrics=[MetricValue(
            name="Net annual fiscal impact — marginal framing", value=100887.0,
            unit="$/yr", low=-338898.0, high=607082.0, provenance=[p], method="m")])],
    )
    draft = ("City staff estimated a net annual impact of $543,000 to $741,000; this "
             "analysis puts it at -$338,898 to $607,082.")
    assert validate_report(draft, bundle) == []
