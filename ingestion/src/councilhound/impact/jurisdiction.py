"""Jurisdiction config (YAML) + lazily-built JurisdictionContext.

All jurisdiction-specific values — FIPS codes, CRS, data-source URLs, tax and
budget rates — live in ingestion/jurisdictions/<name>.yaml, never in module
logic. Rates start as null placeholders; `impact-setup-jurisdiction` pins
them with provenance (source URL + fiscal year). Anything still null when a
module needs it fails loudly via require_rate() — a guessed rate is worse
than no rate.

JurisdictionContext wraps the config plus the cached context layers. Layer
accessors import the heavy geo stack lazily so this module stays importable
in the base (cloud) environment.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

JURISDICTIONS_DIR = Path(__file__).resolve().parents[3] / "jurisdictions"


class PinnedValue(BaseModel):
    """A config value that must carry its source. value=None means 'not yet
    pinned' — usable only after impact-setup-jurisdiction fills it in."""
    value: float | None = None
    source: str | None = None  # URL it was read from
    fy: str | None = None  # fiscal year / vintage


class TaxRates(BaseModel):
    real_estate_rate_per_100: PinnedValue = Field(default_factory=PinnedValue)
    meals_tax_rate: PinnedValue = Field(default_factory=PinnedValue)
    sales_tax_local_share: PinnedValue = Field(default_factory=PinnedValue)
    personal_property_per_household: PinnedValue = Field(default_factory=PinnedValue)


class BudgetFacts(BaseModel):
    general_fund_expenditure: PinnedValue = Field(default_factory=PinnedValue)
    population_basis: PinnedValue = Field(default_factory=PinnedValue)


class Fips(BaseModel):
    state: str
    county: str


class JurisdictionConfig(BaseModel):
    name: str
    slug: str  # file stem, e.g. "fairfax_city_va"
    fips: Fips
    crs_projected: str  # e.g. "EPSG:2283" — all distance math happens here
    projects_index_url: str
    boundary_source: str | None = None  # ArcGIS layer URL — discovered, then pinned
    parcels_source: str | None = None
    zoning_source: str | None = None
    assessment_source: str | None = None
    development_review_map_source: str | None = None
    geohub_portal_url: str | None = None
    tax: TaxRates = Field(default_factory=TaxRates)
    budget: BudgetFacts = Field(default_factory=BudgetFacts)
    transit_feeds: list[str] = Field(default_factory=list)
    fringe_reference_blockgroup: str | None = None  # environmental module (M6 seam)
    calibration_counts: dict | None = None  # optional pedestrian counts

    @classmethod
    def load(cls, slug: str) -> "JurisdictionConfig":
        path = JURISDICTIONS_DIR / f"{slug}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"no jurisdiction config at {path}")
        data = yaml.safe_load(path.read_text()) or {}
        data["slug"] = slug
        return cls.model_validate(data)

    def save(self) -> Path:
        """Write the config back (used by setup to pin discovered values)."""
        path = JURISDICTIONS_DIR / f"{self.slug}.yaml"
        data = self.model_dump(exclude={"slug"}, exclude_none=False)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        return path


class MissingRateError(RuntimeError):
    pass


def require_rate(cfg: JurisdictionConfig, dotted: str) -> PinnedValue:
    """Fetch e.g. "tax.meals_tax_rate"; raise with remediation if unpinned."""
    obj: Any = cfg
    for part in dotted.split("."):
        obj = getattr(obj, part)
    if not isinstance(obj, PinnedValue) or obj.value is None:
        raise MissingRateError(
            f"jurisdiction '{cfg.slug}' has no pinned value for '{dotted}' — "
            "run `python -m councilhound.cli impact-setup-jurisdiction` to "
            "discover and pin it with provenance"
        )
    return obj


def require_source(cfg: JurisdictionConfig, attr: str) -> str:
    value = getattr(cfg, attr)
    if not value:
        raise MissingRateError(
            f"jurisdiction '{cfg.slug}' has no pinned '{attr}' URL — run "
            "`python -m councilhound.cli impact-setup-jurisdiction` (or "
            "impact-context, which pins discoverable layer URLs) first"
        )
    return value


class JurisdictionContext:
    """Config + lazily-loaded cached context layers. Each accessor delegates
    to a context/ builder that builds-if-missing and reads from disk cache,
    so a warm context loads in seconds. Heavy imports live in the builders."""

    def __init__(self, slug: str):
        self.cfg = JurisdictionConfig.load(slug)
        from councilhound.impact.cache import Manifest  # light
        self.manifest = Manifest(slug)

    @functools.cached_property
    def boundary(self):
        from councilhound.impact.context import geohub
        return geohub.load_boundary(self)

    @functools.cached_property
    def walk_graph(self):
        from councilhound.impact.context import networks
        return networks.load_graph(self, "walk")

    @functools.cached_property
    def drive_graph(self):
        from councilhound.impact.context import networks
        return networks.load_graph(self, "drive")

    @functools.cached_property
    def node_weights(self):
        from councilhound.impact.context import networks
        return networks.load_node_weights(self)

    @functools.cached_property
    def census_bg(self):
        from councilhound.impact.context import census
        return census.load_blockgroups(self)

    @functools.cached_property
    def lodes(self):
        from councilhound.impact.context import census
        return census.load_lodes(self)

    @functools.cached_property
    def pois(self):
        from councilhound.impact.context import pois
        return pois.load_pois(self)

    @functools.cached_property
    def transit_stops(self):
        from councilhound.impact.context import transit
        return transit.load_stops(self)

    @functools.cached_property
    def parcels(self):
        from councilhound.impact.context import parcels
        return parcels.load_parcels(self)

    def transformer(self):
        """pyproj transformer EPSG:4326 -> the jurisdiction's projected CRS."""
        import pyproj
        return pyproj.Transformer.from_crs("EPSG:4326", self.cfg.crs_projected, always_xy=True)
