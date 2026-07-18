"""Project-document ingestion for spec extraction.

The source is the existing CityProject row — the directory scraper already
collected the Plans-section document links, description, requests, and
official timeline, so there is no second scraper here. PDFs land under
RAW_DATA_DIR/impact/projects/<slug>/ (http.download skips already-fetched
files); text extraction reuses extraction.pdf_text. The directory record
itself rides along as a pseudo-document so the extractor sees status,
requests, and address even when a project has no PDFs yet.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from councilhound import http
from councilhound.db.models import CityProject
from councilhound.extraction.pdf_text import pdf_to_text
from councilhound.impact.cache import raw_path
from councilhound.impact.provenance import prov
from councilhound.impact.schemas import Provenance

log = logging.getLogger(__name__)

DIRECTORY_RECORD_LABEL = "City project directory record"


@dataclass
class ProjectDocument:
    label: str
    url: str
    text: str
    provenance: Provenance


def _safe_filename(url: str) -> str:
    name = urlparse(url).path.rstrip("/").split("/")[-1] or "document"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def _directory_record_text(project: CityProject) -> str:
    lines = [
        f"Project: {project.name}",
        f"Type: {project.project_type or 'unknown'}",
        f"Official status: {project.official_status or 'unknown'}",
        f"Address: {project.address or 'unknown'}",
        f"Applicant: {project.applicant or 'unknown'}",
    ]
    if project.description:
        lines += ["", "Background:", project.description]
    if project.requests:
        lines += ["", "Requests:", project.requests]
    if project.official_timeline:
        lines += ["", "Official timeline:"] + [f"- {t}" for t in project.official_timeline]
    return "\n".join(lines)


def gather_documents(project: CityProject) -> list[ProjectDocument]:
    """Download + extract every linked PDF, newest-listed first, plus the
    directory-record pseudo-document. Unfetchable or unextractable documents
    are skipped with a warning — extraction quality degrades, silently
    fabricating text does not happen."""
    docs: list[ProjectDocument] = [ProjectDocument(
        label=DIRECTORY_RECORD_LABEL,
        url=project.detail_url,
        text=_directory_record_text(project),
        provenance=prov(DIRECTORY_RECORD_LABEL, project.detail_url,
                        project.synced_at.date().isoformat() if project.synced_at else "current"),
    )]
    for entry in project.documents or []:
        url, label = entry.get("url"), entry.get("label") or "document"
        if not url or not url.lower().endswith(".pdf"):
            if url:
                log.info("skipping non-PDF document link: %s", url)
            continue
        dest = raw_path("projects", project.external_slug, _safe_filename(url))
        try:
            if not (dest.exists() and dest.stat().st_size > 0):
                from councilhound.scraper.fairfax_projects import FAIRFAX_HEADERS
                # fairfaxva.gov WAF rejects non-browser requests; per-request
                # headers via http.get (project PDFs are small enough to buffer)
                resp = http.get(url, headers=FAIRFAX_HEADERS, timeout=120)
                from councilhound.impact.cache import atomic_write_bytes
                atomic_write_bytes(dest, resp.content)
        except Exception as exc:
            log.warning("document download failed (%s): %s", url, exc)
            continue
        try:
            text = pdf_to_text(str(dest))
        except Exception as exc:
            log.warning("PDF text extraction failed (%s): %s", dest.name, exc)
            continue
        if not text:
            log.warning("document %s extracted empty (scanned/garbled) — skipped", dest.name)
            continue
        docs.append(ProjectDocument(
            label=label, url=url, text=text,
            provenance=prov(f"Project document: {label}", url, "current"),
        ))
    log.info("gathered %d documents for %s (%d with text)",
             len(project.documents or []) + 1, project.external_slug, len(docs))
    return docs
