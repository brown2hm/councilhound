"""Impact-side view of the jurisdiction config + lazily-built JurisdictionContext.

All jurisdiction-specific values — FIPS codes, CRS, data-source URLs, tax and
budget rates — live in ingestion/jurisdictions/<name>.yaml (models in
councilhound.jurisdiction), never in module logic. Rates start as null placeholders; `impact-setup-jurisdiction` pins
them with provenance (source URL + fiscal year). Anything still null when a
module needs it fails loudly via require_rate() — a guessed rate is worse
than no rate.

JurisdictionContext wraps the config plus the cached context layers. Layer
accessors import the heavy geo stack lazily so this module stays importable
in the base (cloud) environment.
"""
from __future__ import annotations

import functools
from typing import Any

# The models and loader live in councilhound.jurisdiction (core); this module
# keeps the impact-specific helpers and re-exports the names impact code and
# tests import from here.
from councilhound.jurisdiction import (  # noqa: F401
    JURISDICTIONS_DIR,
    BudgetFacts,
    Fips,
    JurisdictionConfig,
    PinnedValue,
    TaxRates,
)


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
    def bike_graph(self):
        from councilhound.impact.context import networks
        return networks.load_graph(self, "bike")

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
    def blocks(self):
        from councilhound.impact.context import census
        return census.load_blocks(self)

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

    @functools.cached_property
    def commercial_retail_zones(self):
        from councilhound.impact.context import geohub
        return geohub.load_commercial_retail_zones(self)

    def transformer(self):
        """pyproj transformer EPSG:4326 -> the jurisdiction's projected CRS."""
        import pyproj
        return pyproj.Transformer.from_crs("EPSG:4326", self.cfg.crs_projected, always_xy=True)
