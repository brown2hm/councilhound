"""Jurisdiction config loading + fail-loudly rate discipline (no heavy deps)."""
import pytest

from councilhound.impact import jurisdiction as jur
from councilhound.impact.jurisdiction import (
    JurisdictionConfig,
    MissingRateError,
    require_rate,
    require_source,
)

MINIMAL_YAML = """
name: Testville
fips: {state: "51", county: "600"}
crs_projected: "EPSG:2283"
projects_index_url: https://example.gov/projects
tax:
  real_estate_rate_per_100: {value: 1.01, source: "https://example.gov/budget", fy: "FY2026"}
  meals_tax_rate: {value: null, source: null, fy: null}
"""


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(jur, "JURISDICTIONS_DIR", tmp_path)
    (tmp_path / "testville.yaml").write_text(MINIMAL_YAML)
    return JurisdictionConfig.load("testville")


def test_load_and_defaults(cfg):
    assert cfg.name == "Testville"
    assert cfg.fips.county == "600"
    assert cfg.transit_feeds == []
    assert cfg.boundary_source is None


def test_require_rate_returns_pinned(cfg):
    pinned = require_rate(cfg, "tax.real_estate_rate_per_100")
    assert pinned.value == 1.01
    assert pinned.fy == "FY2026"


def test_require_rate_fails_loudly_on_null(cfg):
    with pytest.raises(MissingRateError, match="impact-setup-jurisdiction"):
        require_rate(cfg, "tax.meals_tax_rate")
    with pytest.raises(MissingRateError, match="impact-setup-jurisdiction"):
        require_rate(cfg, "budget.general_fund_expenditure")


def test_require_source_fails_loudly(cfg):
    with pytest.raises(MissingRateError):
        require_source(cfg, "parcels_source")


def test_save_round_trips_pinned_values(cfg):
    cfg.tax.meals_tax_rate.value = 0.04
    cfg.tax.meals_tax_rate.source = "https://example.gov/budget"
    cfg.tax.meals_tax_rate.fy = "FY2026"
    cfg.save()
    again = JurisdictionConfig.load("testville")
    assert again.tax.meals_tax_rate.value == 0.04


def test_missing_config_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(jur, "JURISDICTIONS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        JurisdictionConfig.load("nowhere")


def test_fairfax_config_parses():
    # the real checked-in config must always stay loadable
    cfg = JurisdictionConfig.load("fairfax_city_va")
    assert cfg.fips.state == "51"
    assert cfg.crs_projected == "EPSG:2283"
    assert cfg.development_review_map_source
