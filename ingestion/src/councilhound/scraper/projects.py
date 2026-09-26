"""Official development-project sources, one adapter per jurisdiction kind.

`sync_projects` asks `get_source()` for the jurisdiction's adapter and calls
`list_projects(fetch_details)`, which returns `(records, complete)`:
`complete` says whether the list is the whole official directory (so
records that disappeared can be pruned) or a partial refresh.

Adapters (projects.adapter in the jurisdiction YAML):
  fairfaxva_opencities  the City's OpenCities index + ArcGIS "Major
                        Developments" layer (councilhound.scraper.fairfax_projects)
  arcgis_feature_layer  any ArcGIS FeatureServer layer of cases/projects,
                        mapped by a field table in projects.params
                        (councilhound.scraper.arcgis_projects)
  none                  no official directory
"""
from __future__ import annotations

from typing import Protocol

from councilhound.jurisdiction import JurisdictionConfig
from councilhound.scraper.fairfax_projects import DiscoveredProject

ProjectRecord = DiscoveredProject


class ProjectsSource(Protocol):
    def list_projects(self, fetch_details: bool = True) -> tuple[list[ProjectRecord], bool]: ...


class OpenCitiesSource:
    """The City of Fairfax directory; delegates at call time so tests that
    patch `fairfax_projects.list_projects` keep working."""

    def list_projects(self, fetch_details: bool = True) -> tuple[list[ProjectRecord], bool]:
        from councilhound.scraper import fairfax_projects
        return fairfax_projects.list_projects(fetch_details=fetch_details)


class ArcGISSource:
    def __init__(self, params: dict):
        self.params = params

    def list_projects(self, fetch_details: bool = True) -> tuple[list[ProjectRecord], bool]:
        from councilhound.scraper.arcgis_projects import list_projects
        return list_projects(self.params)


ADAPTERS = {
    "fairfaxva_opencities": lambda params: OpenCitiesSource(),
    "arcgis_feature_layer": ArcGISSource,
}


def get_source(cfg: JurisdictionConfig) -> ProjectsSource | None:
    """The jurisdiction's projects adapter, or None when it has no official
    directory (projects.adapter 'none' or features.projects off)."""
    if not cfg.features.projects or cfg.projects.adapter in ("none", "", None):
        return None
    try:
        factory = ADAPTERS[cfg.projects.adapter]
    except KeyError as exc:
        raise ValueError(
            f"unknown projects adapter {cfg.projects.adapter!r}; known: {sorted(ADAPTERS)}") from exc
    return factory(cfg.projects.params)
