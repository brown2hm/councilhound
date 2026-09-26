"""Official cases/projects from an ArcGIS FeatureServer layer.

Fairfax County publishes its zoning applications (rezonings, special
exceptions, plan amendments, agricultural districts) as a PLUS feature layer;
many jurisdictions expose something similar. The adapter is a paged
`/query` plus a field map, so a new jurisdiction is a YAML entry:

  projects:
    adapter: arcgis_feature_layer
    params:
      layer_url: https://.../FeatureServer/0
      where: "RECORD_STATUS IN ('In Review', ...)"     # which records are the directory
      fields:                                          # ProjectRecord field -> layer attribute
        external_slug: RECORDID
        name: RECORDID
        project_type: APPTYPEALIAS
        official_status: RECORD_STATUS
        description: WORK_DESCRIPTION
        applicant: APPLICANT
        planner_name: STAFF_MEMBER
        detail_url: LINK_URL
      name_template: "{APPTYPEALIAS} {RECORDID}"       # optional, overrides fields.name
      status_labels: {"BOS Action": "Before the Board"} # optional raw -> display
      division_from_id: {regex: "-([A-Z]{2})-", codes: {PR: Providence, ...}}  # optional
      order_by: RECORD_STATUS_DATE DESC                 # optional

Polygon layers are asked for centroids (returnCentroid) so every record
gets a map pin; point layers use the point.
"""
from __future__ import annotations

import logging
import re

from councilhound import http
from councilhound.scraper.fairfax_projects import DiscoveredProject

log = logging.getLogger(__name__)

PAGE_SIZE = 1000


def _clean(value) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _query(layer_url: str, params: dict) -> dict:
    resp = http.get(f"{layer_url.rstrip('/')}/query", params=params, timeout=120)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"ArcGIS query failed: {data['error']}")
    return data


def fetch_features(layer_url: str, where: str, out_fields: list[str] | None = None,
                   order_by: str | None = None) -> list[dict]:
    """Every feature matching `where`, paged by resultOffset, each as
    {'attributes': {...}, 'lat': ..., 'lng': ...} in WGS84."""
    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": where or "1=1",
            "outFields": ",".join(out_fields) if out_fields else "*",
            "returnGeometry": "true",
            "returnCentroid": "true",
            "outSR": "4326",
            "resultOffset": str(offset),
            "resultRecordCount": str(PAGE_SIZE),
            "f": "json",
        }
        if order_by:
            params["orderByFields"] = order_by
        data = _query(layer_url, params)
        batch = data.get("features", [])
        for f in batch:
            lat = lng = None
            centroid = f.get("centroid")
            geom = f.get("geometry") or {}
            if centroid and "x" in centroid:
                lng, lat = centroid["x"], centroid["y"]
            elif "x" in geom and "y" in geom:
                lng, lat = geom["x"], geom["y"]
            features.append({"attributes": f.get("attributes", {}), "lat": lat, "lng": lng})
        if not batch or not data.get("exceededTransferLimit") and len(batch) < PAGE_SIZE:
            break
        offset += len(batch)
    return features


def to_record(attrs: dict, lat, lng, params: dict) -> DiscoveredProject | None:
    fields: dict[str, str] = params.get("fields", {})
    get = lambda key: _clean(attrs.get(fields[key])) if key in fields else None  # noqa: E731
    raw_id = get("external_slug")
    if not raw_id:
        return None
    name = None
    if params.get("name_template"):
        try:
            name = _clean(params["name_template"].format(**{k: (v or "") for k, v in attrs.items()}))
        except KeyError:
            name = None
    name = name or get("name") or raw_id
    status_raw = get("official_status")
    status = (params.get("status_labels") or {}).get(status_raw, status_raw)
    division = get("division")
    rule = params.get("division_from_id")
    if division is None and rule and rule.get("regex"):
        m = re.search(rule["regex"], raw_id)
        if m:
            division = (rule.get("codes") or {}).get(m.group(1), m.group(1))
    detail_url = get("detail_url")
    if not detail_url and params.get("detail_url_template"):
        detail_url = params["detail_url_template"].format(external_slug=raw_id, **attrs)
    return DiscoveredProject(
        external_slug=_slug(raw_id),
        name=name,
        detail_url=detail_url or params.get("layer_url", ""),
        project_type=get("project_type"),
        division=division,
        official_status=status,
        description=get("description"),
        requests=get("requests"),
        address=get("address"),
        applicant=get("applicant"),
        planner_name=get("planner_name"),
        planner_phone=get("planner_phone"),
        planner_email=get("planner_email"),
        image_url=get("image_url"),
        lat=lat,
        lng=lng,
    )


def list_projects(params: dict) -> tuple[list[DiscoveredProject], bool]:
    """(records, complete=True): the layer + where clause IS the directory,
    so records that no longer match are pruned by the caller."""
    layer_url = params.get("layer_url")
    if not layer_url:
        raise ValueError("projects.params.layer_url is not pinned — run `projects-discover`")
    fields = params.get("fields", {})
    out_fields = sorted({*fields.values(), *re.findall(r"\{(\w+)\}", params.get("name_template", ""))}) or None
    features = fetch_features(layer_url, params.get("where", "1=1"), out_fields, params.get("order_by"))
    records: list[DiscoveredProject] = []
    seen: set[str] = set()
    for f in features:
        rec = to_record(f["attributes"], f["lat"], f["lng"], params)
        if rec is None or rec.external_slug in seen:
            continue
        seen.add(rec.external_slug)
        records.append(rec)
    log.info("arcgis projects: %d records from %s", len(records), layer_url)
    return records, True


def describe_layer(url: str) -> dict:
    """Metadata for `projects-discover`: a service's layers, or one layer's
    fields, record count and a few sample rows."""
    meta = http.get(url, params={"f": "json"}, timeout=60).json()
    if "layers" in meta:  # a service
        return {"service": url, "layers": [{"id": l["id"], "name": l["name"]} for l in meta["layers"]]}
    out = {"layer": url, "name": meta.get("name"), "geometryType": meta.get("geometryType"),
           "fields": [(f["name"], f["type"]) for f in meta.get("fields", [])]}
    out["count"] = _query(url, {"where": "1=1", "returnCountOnly": "true", "f": "json"}).get("count")
    sample = _query(url, {"where": "1=1", "outFields": "*", "returnGeometry": "false",
                          "resultRecordCount": "3", "f": "json"})
    out["sample"] = [f["attributes"] for f in sample.get("features", [])]
    return out
