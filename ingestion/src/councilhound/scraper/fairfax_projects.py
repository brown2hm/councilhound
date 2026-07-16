"""Scrape City of Fairfax development-project records.

The public directory is OpenCities HTML. Its list page is paginated by
WebForms postback, but each rendered page has stable project-card markup.
The companion ArcGIS Experience Builder app exposes a FeatureServer with
structured status + point geometry for major private developments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from councilhound import http
from councilhound.config import FAIRFAX_PROJECTS_ARCGIS_URL, FAIRFAX_PROJECTS_URL

BASE = "https://www.fairfaxva.gov"
FAIRFAX_HEADERS = {
    "User-Agent": "CouncilHound/0.1 (+https://councilhound.net)",
    "Referer": BASE + "/",
}

STATUS_LABELS = {
    0: "Pre-Application",
    1: "Under Review",
    2: "Approved",
    3: "Under Construction",
}


@dataclass
class DiscoveredProject:
    external_slug: str
    name: str
    detail_url: str
    project_type: str | None = None
    division: str | None = None
    official_status: str | None = None
    status_code: int | None = None
    description: str | None = None
    requests: str | None = None
    address: str | None = None
    applicant: str | None = None
    planner_name: str | None = None
    planner_phone: str | None = None
    planner_email: str | None = None
    image_url: str | None = None
    documents: list[dict] = field(default_factory=list)
    official_timeline: list[str] = field(default_factory=list)
    lat: float | None = None
    lng: float | None = None


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _slug_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def _project_name_key(name: str | None) -> str:
    if not name:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return re.sub(r"^\d+\s+", "", normalized)


def _absolute(url: str | None) -> str | None:
    return urljoin(BASE, url) if url else None


def _fairfax_get(url: str):
    return http.get(url, headers=FAIRFAX_HEADERS)


def _fairfax_post(url: str, **kwargs):
    return http.post(url, headers=FAIRFAX_HEADERS, **kwargs)


def parse_project_list(html: str) -> list[DiscoveredProject]:
    soup = BeautifulSoup(html, "lxml")
    projects: list[DiscoveredProject] = []
    for item in soup.select(".list-item-container article a[href*='/Development/Projects/']"):
        href = _absolute(item.get("href"))
        title = item.select_one(".list-item-title")
        if not href or not title:
            continue
        icon = title.select_one("img")
        icon_hint = " ".join([icon.get("alt") or "", icon.get("src") or ""]) if icon else ""
        project_type = "City Project" if "city-project" in icon_hint.lower() else "Private Development"
        for img in title.select("img"):
            img.decompose()
        desc = item.find("p")
        projects.append(DiscoveredProject(
            external_slug=_slug_from_url(href),
            name=_text(title),
            detail_url=href,
            project_type=project_type,
            description=_text(desc) if desc else None,
        ))
    return projects


def _pagination_form(html: str) -> tuple[dict[str, str], str | None, str | None, int]:
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form")
    if not form:
        return {}, None, None, 1
    data = {}
    for field in form.find_all(["input", "select", "textarea"]):
        name = field.get("name")
        if not name:
            continue
        if field.name == "select":
            selected = field.find("option", selected=True) or field.find("option")
            data[name] = selected.get("value", "") if selected else ""
        elif field.get("type") not in ("submit", "button", "image"):
            data[name] = field.get("value", "")
    pager = soup.select_one(".seamless-pagination select")
    page_field = pager.get("name") if pager else None
    go = soup.select_one(".seamless-pagination input[type='submit'][value='Go']")
    go_field = go.get("name") if go else None
    page_count = 1
    if pager:
        values = [int(o.get("value")) for o in pager.find_all("option") if (o.get("value") or "").isdigit()]
        page_count = max(values) if values else 1
    return data, page_field, go_field, page_count


def _fetch_project_list_pages() -> list[str]:
    first = _fairfax_get(FAIRFAX_PROJECTS_URL).text
    data, page_field, go_field, page_count = _pagination_form(first)
    pages = [first]
    if not page_field or not go_field:
        return pages
    for page in range(2, page_count + 1):
        payload = dict(data)
        payload[page_field] = str(page)
        payload[go_field] = "Go"
        pages.append(_fairfax_post(FAIRFAX_PROJECTS_URL, data=payload).text)
    return pages


def _sections(soup: BeautifulSoup) -> dict[str, list]:
    sections: dict[str, list] = {}
    for heading in soup.find_all(["h2", "h3"]):
        label = _text(heading).lower()
        nodes = []
        for sib in heading.find_next_siblings():
            if sib.name in ("h2", "h3"):
                break
            nodes.append(sib)
        sections[label] = nodes
    return sections


def _section_text(sections: dict[str, list], label: str) -> str | None:
    nodes = sections.get(label.lower())
    if not nodes:
        return None
    text = re.sub(r"\s+", " ", " ".join(_text(n) for n in nodes)).strip()
    return text or None


def _section_links(sections: dict[str, list], label: str) -> list[dict]:
    out = []
    for node in sections.get(label.lower(), []):
        for link in node.find_all("a", href=True):
            out.append({"label": _text(link), "url": _absolute(link.get("href"))})
    return out


def parse_project_detail(html: str, fallback: DiscoveredProject) -> DiscoveredProject:
    soup = BeautifulSoup(html, "lxml")
    project = DiscoveredProject(**fallback.__dict__)

    facts = [_text(li) for li in soup.select("main li, .content-main li")]
    for fact in facts:
        if fact.startswith("Project type "):
            project.project_type = fact.removeprefix("Project type ").strip()
        elif fact.startswith("Project division "):
            project.division = fact.removeprefix("Project division ").strip()
        elif fact.startswith("Project schedule "):
            project.official_status = fact.removeprefix("Project schedule ").strip()

    sections = _sections(soup)
    timeline = []
    for node in sections.get("project", []):
        timeline.extend(_text(li) for li in node.find_all("li"))
    project.official_timeline = [t for t in timeline if t]
    project.description = _section_text(sections, "background") or project.description
    project.requests = _section_text(sections, "requests")
    project.documents = _section_links(sections, "plans")

    location_text = _section_text(sections, "location")
    if location_text:
        coord = re.search(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", location_text)
        if coord:
            project.lat = float(coord.group(1))
            project.lng = float(coord.group(2))
            location_text = location_text[:coord.start()].strip()
        project.address = re.sub(r"\s*View Map.*$", "", location_text).strip() or project.address

    contact = [line for line in (_text(n) for n in sections.get("contact details", [])) if line]
    contact_text = " ".join(contact)
    email = re.search(r"[\w.+-]+@fairfaxva\.gov", contact_text)
    phone = re.search(r"\(\d{3}\)\s*\d{3}-\d{4}", contact_text)
    if email:
        project.planner_email = email.group(0)
    if phone:
        project.planner_phone = phone.group(0)
    if contact_text:
        project.planner_name = contact_text
        for part in (project.planner_email, project.planner_phone):
            if part:
                project.planner_name = project.planner_name.replace(part, "")
        project.planner_name = project.planner_name.strip(" ,") or None

    applicant = _section_text(sections, "applicant")
    if applicant:
        project.applicant = applicant.replace("Applicant's Representative:", "").strip()

    image = soup.select_one("main img[src], .content-main img[src]")
    if image:
        project.image_url = _absolute(image.get("src"))
    return project


def fetch_project_detail(project: DiscoveredProject) -> DiscoveredProject:
    return parse_project_detail(_fairfax_get(project.detail_url).text, project)


def fetch_arcgis_projects() -> dict[str, dict]:
    resp = http.get(FAIRFAX_PROJECTS_ARCGIS_URL, params={
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "orderByFields": "Name ASC",
    }, timeout=60)
    out: dict[str, dict] = {}
    for feature in resp.json().get("features", []):
        attrs = feature.get("attributes") or {}
        url = attrs.get("ProjectURL")
        name = attrs.get("Name")
        key = _slug_from_url(url) if url else None
        if not key and name:
            key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not key:
            continue
        code = attrs.get("DevStatus")
        code = int(code) if code is not None else None
        geom = feature.get("geometry") or {}
        out[key] = {
            "name": name,
            "address": attrs.get("Location"),
            "description": attrs.get("ProjDescription"),
            "applicant": attrs.get("Applicant"),
            "status_code": code,
            "official_status": STATUS_LABELS.get(code),
            "detail_url": url,
            "image_url": attrs.get("PictureURL") or attrs.get("ThumbnailURL2"),
            "lat": geom.get("y"),
            "lng": geom.get("x"),
        }
    return out


def list_projects(fetch_details: bool = True) -> list[DiscoveredProject]:
    projects = []
    for html in _fetch_project_list_pages():
        projects.extend(parse_project_list(html))
    arcgis = fetch_arcgis_projects()
    by_slug = {p.external_slug: p for p in projects}
    by_name: dict[str, list[DiscoveredProject]] = {}
    for project in projects:
        by_name.setdefault(_project_name_key(project.name), []).append(project)

    for slug, data in arcgis.items():
        project = by_slug.get(slug)
        if project is None:
            candidates = by_name.get(_project_name_key(data.get("name")), [])
            if len(candidates) == 1:
                project = candidates[0]
        existing = project is not None
        if project is None:
            project = DiscoveredProject(
                external_slug=slug,
                name=data.get("name") or slug.replace("-", " ").title(),
                detail_url=data.get("detail_url") or f"{FAIRFAX_PROJECTS_URL}/{slug}",
            )
            by_slug[slug] = project
        for key, value in data.items():
            if existing and key in {"name", "detail_url"}:
                continue
            if value not in (None, ""):
                setattr(project, key, value)

    merged = list(by_slug.values())
    if fetch_details:
        detailed = []
        for project in merged:
            try:
                detailed.append(fetch_project_detail(project))
            except Exception:
                detailed.append(project)
        merged = detailed
    return sorted(merged, key=lambda p: p.name.lower())
