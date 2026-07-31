"""Cross-cutting guarantees about the assumption set itself.

Two ways an assumption can quietly stop working for the reader:
- two modules declare the same key, and bundle dedupe (first module wins)
  silently discards one module's value;
- the pipeline declares a key the frontend has no label for, so the
  assumptions lab shows a raw snake_case key.
"""
import re
from pathlib import Path

import pytest

from councilhound.impact.assumption_util import apply_overrides
from councilhound.impact.modules import fiscal
from councilhound.impact.schemas import Assumption, ProjectSpec

pytest.importorskip("geopandas")  # economic imports the geo stack

from councilhound.impact.modules import economic  # noqa: E402

FRONTEND_LABELS = (Path(__file__).resolve().parents[3]
                   / "frontend" / "lib" / "assumptions.ts")


class _Cfg:
    slug = "testville"


class _Ctx:
    cfg = _Cfg()


def _spec(tenure=None):
    return ProjectSpec.model_validate({
        "name": "T", "jurisdiction": "testville", "city_project_slug": "t",
        "source_url": "u", "project_type": "mixed_use", "status": "Approved",
        "proposed": {"units": 79, "retail_sqft": 7731.0, "office_sqft": 36862.0,
                     "tenure": tenure},
    })


def _fiscal_keys(spec):
    assumptions, _ = fiscal._assumptions(spec, None, [])
    return set(assumptions)


def _economic_keys(spec):
    return set(economic._assumptions(_Ctx(), spec))


def test_module_assumption_keys_are_disjoint():
    """all_assumptions() dedupes by key with first-module-wins, so a shared key
    would let one module's value silently override another's."""
    spec = _spec()
    overlap = _fiscal_keys(spec) & _economic_keys(spec)
    assert overlap == set(), f"modules share assumption keys: {sorted(overlap)}"


def test_tenure_changes_values_not_the_key_set():
    for keys in (_fiscal_keys, _economic_keys):
        assert keys(_spec("rental")) == keys(_spec("for_sale"))


def test_for_sale_defaults_exceed_rental_defaults():
    rental = dict(economic._assumptions(_Ctx(), _spec("rental")))
    for_sale = dict(economic._assumptions(_Ctx(), _spec("for_sale")))
    for key in ("occupancy_rate", "avg_hh_size_multifamily",
                "income_premium_new_construction"):
        assert for_sale[key].value > rental[key].value, key


def test_unknown_and_mixed_tenure_fall_back_to_rental_defaults():
    rental = dict(economic._assumptions(_Ctx(), _spec("rental")))
    for tenure in (None, "unknown", "mixed"):
        other = dict(economic._assumptions(_Ctx(), _spec(tenure)))
        assert other["avg_hh_size_multifamily"].value == rental["avg_hh_size_multifamily"].value


def test_every_declared_assumption_has_a_frontend_label():
    """An unlabeled key falls through to its raw snake_case form in the
    assumptions lab — not a crash, so nothing else catches it."""
    if not FRONTEND_LABELS.exists():
        pytest.skip("frontend not present in this checkout")
    source = FRONTEND_LABELS.read_text()
    labelled = set(re.findall(r"^\s*(\w+):\s*[\"']", source, re.MULTILINE))
    spec = _spec()
    declared = _fiscal_keys(spec) | _economic_keys(spec)
    missing = sorted(declared - labelled)
    assert missing == [], f"assumptions with no frontend label: {missing}"


def test_override_replaces_value_and_records_a_note():
    a = {"students_per_unit": Assumption(
        key="students_per_unit", value=0.10, low=0.05, high=0.15,
        basis="b", rationale="r")}
    spec = ProjectSpec.model_validate({
        "name": "T", "jurisdiction": "t", "city_project_slug": "t", "source_url": "u",
        "project_type": "mixed_use", "status": "s",
        "assumption_overrides": {"students_per_unit": {
            "value": 0.30, "low": 0.20, "high": 0.40, "rationale": "FCPS yield table"}},
    })
    notes = []
    out = apply_overrides(a, spec, notes)
    assert (out["students_per_unit"].value, out["students_per_unit"].low) == (0.30, 0.20)
    assert "FCPS yield table" in notes[0]
    assert "0.1" in notes[0]  # the replaced default is stated


def test_override_of_an_unknown_key_is_left_to_the_owning_module():
    a = {"students_per_unit": Assumption(
        key="students_per_unit", value=0.10, low=0.05, high=0.15,
        basis="b", rationale="r")}
    spec = ProjectSpec.model_validate({
        "name": "T", "jurisdiction": "t", "city_project_slug": "t", "source_url": "u",
        "project_type": "mixed_use", "status": "s",
        "assumption_overrides": {"occupancy_rate": {
            "value": 0.99, "low": 0.98, "high": 1.0}},
    })
    notes = []
    out = apply_overrides(a, spec, notes)
    assert out["students_per_unit"].value == 0.10
    assert notes == []


def test_override_bounds_must_be_ordered():
    with pytest.raises(ValueError):
        ProjectSpec.model_validate({
            "name": "T", "jurisdiction": "t", "city_project_slug": "t",
            "source_url": "u", "project_type": "mixed_use", "status": "s",
            "assumption_overrides": {"students_per_unit": {
                "value": 0.30, "low": 0.40, "high": 0.50}},
        })
