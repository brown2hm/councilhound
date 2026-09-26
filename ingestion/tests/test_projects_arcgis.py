"""The generic ArcGIS feature-layer projects adapter and the adapter registry."""
import json

from councilhound import pipeline
from councilhound.jurisdiction import JurisdictionConfig
from councilhound.scraper import arcgis_projects
from councilhound.scraper.projects import ArcGISSource, OpenCitiesSource, get_source

PARAMS = {
    "layer_url": "https://example.arcgis.com/rest/services/Cases/FeatureServer/0",
    "where": "STATUS = 'Open'",
    "fields": {"external_slug": "RECORDID", "name": "RECORDID", "project_type": "APPTYPE",
               "official_status": "STATUS", "description": "DESC", "applicant": "APPLICANT",
               "detail_url": "LINK"},
    "status_labels": {"BOS Action": "Before the Board"},
    "division_from_id": {"regex": "-([A-Z]{2})-", "codes": {"PR": "Providence"}},
}

PAGE1 = {"features": [
    {"attributes": {"RECORDID": "RZ-2025-PR-00001", "APPTYPE": "Rezoning", "STATUS": "BOS Action",
                    "DESC": "  156 townhouses \n on Prosperity ", "APPLICANT": "PM Homes", "LINK": "https://plus/x"},
     "centroid": {"x": -77.22, "y": 38.87}},
    {"attributes": {"RECORDID": "SE-2026-SU-00011", "APPTYPE": "Special Exception", "STATUS": "In Review",
                    "DESC": None, "APPLICANT": "", "LINK": None},
     "geometry": {"x": -77.44, "y": 38.90}},
    {"attributes": {"RECORDID": "", "APPTYPE": "x", "STATUS": "x", "DESC": "", "APPLICANT": "", "LINK": ""}},
], "exceededTransferLimit": True}
PAGE2 = {"features": [
    {"attributes": {"RECORDID": "RZ-2025-PR-00001", "APPTYPE": "Rezoning", "STATUS": "BOS Action",
                    "DESC": "dup", "APPLICANT": "", "LINK": ""}, "centroid": {"x": 0, "y": 0}},
]}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_list_projects_maps_pages_and_centroids(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=0):
        calls.append(params)
        return _Resp(PAGE1 if params["resultOffset"] == "0" else PAGE2)
    monkeypatch.setattr(arcgis_projects.http, "get", fake_get)
    records, complete = arcgis_projects.list_projects(PARAMS)
    assert complete is True
    assert [r.external_slug for r in records] == ["rz-2025-pr-00001", "se-2026-su-00011"]
    r = records[0]
    assert r.name == "RZ-2025-PR-00001" and r.project_type == "Rezoning"
    assert r.official_status == "Before the Board"  # relabelled
    assert r.description == "156 townhouses on Prosperity" and r.applicant == "PM Homes"
    assert r.division == "Providence" and r.detail_url == "https://plus/x"
    assert (r.lat, r.lng) == (38.87, -77.22)
    assert records[1].official_status == "In Review" and records[1].division == "SU"
    assert (records[1].lat, records[1].lng) == (38.90, -77.44)
    assert records[1].detail_url == PARAMS["layer_url"]  # no link: fall back to the layer
    assert calls[0]["where"] == "STATUS = 'Open'" and calls[0]["returnCentroid"] == "true"
    assert calls[1]["resultOffset"] == "3"  # paged past the first batch
    assert "RECORDID" in calls[0]["outFields"] and "*" not in calls[0]["outFields"]


def test_registry_picks_the_adapter():
    city = JurisdictionConfig.load("fairfax_city_va")
    county = JurisdictionConfig.load("fairfax_county_va")
    assert isinstance(get_source(city), OpenCitiesSource)
    src = get_source(county)
    assert isinstance(src, ArcGISSource) and src.params["layer_url"].endswith("/FeatureServer/0")
    off = county.model_copy(deep=True)
    off.features.projects = False
    assert get_source(off) is None
    none = county.model_copy(deep=True)
    none.projects.adapter = "none"
    assert get_source(none) is None


def test_sync_projects_skips_without_an_adapter(db_session, monkeypatch):
    county = JurisdictionConfig.load("fairfax_county_va")
    county.projects.adapter = "none"
    monkeypatch.setattr(pipeline, "JURISDICTION", county)
    assert pipeline.sync_projects(db_session) == {"skipped": "no projects adapter"}


def test_sync_projects_uses_an_injected_source(db_session):
    from councilhound.db.models import CityProject
    from councilhound.scraper.fairfax_projects import DiscoveredProject

    class Src:
        def list_projects(self, fetch_details=True):
            return [DiscoveredProject(external_slug="rz-1", name="RZ-1", detail_url="https://plus/1",
                                      lat=38.9, lng=-77.3)], True
    result = pipeline.sync_projects(db_session, source=Src())
    assert result["projects"] == 1 and result["created"] == 1 and result["geocoded"] == 1
    assert db_session.query(CityProject).filter_by(external_slug="rz-1").one().name == "RZ-1"


def test_describe_layer_reports_fields_and_count(monkeypatch):
    def fake_get(url, params=None, timeout=0):
        if url.endswith("/query"):
            if params.get("returnCountOnly"):
                return _Resp({"count": 7})
            return _Resp({"features": [{"attributes": {"RECORDID": "A"}}]})
        return _Resp({"name": "Cases", "geometryType": "esriGeometryPolygon",
                      "fields": [{"name": "RECORDID", "type": "esriFieldTypeString"}]})
    monkeypatch.setattr(arcgis_projects.http, "get", fake_get)
    d = arcgis_projects.describe_layer("https://x/FeatureServer/0")
    assert d["count"] == 7 and d["fields"] == [("RECORDID", "esriFieldTypeString")]
    assert d["sample"] == [{"RECORDID": "A"}]
    assert json.dumps(d)
