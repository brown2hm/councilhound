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

from sqlalchemy import select

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


# document titles/text worth pulling out of a council packet first: the staff
# report and any fiscal analysis carry the city's own numbers
RELEVANCE_KEYWORDS = ("fiscal impact", "staff report", "fiscal analysis",
                      "public hearing", "rezoning", "special use")

MAX_MEETING_DOCS = 8


def gather_meeting_documents(session, project: CityProject,
                            max_docs: int = MAX_MEETING_DOCS,
                            keywords: tuple[str, ...] = RELEVANCE_KEYWORDS,
                            ) -> list[ProjectDocument]:
    """Council-packet PDFs for meetings where this project was discussed.

    The project-directory scraper only collects the applicant's own
    submissions from the project page's plans/documents sections, so the city
    staff report — which carries staff's independent fiscal estimate and the
    program table council actually voted on — never reached the extractor.
    Those PDFs are already ingested by the meeting pipeline as
    doc_type='agenda_item_pdf' with raw_text filled in; nothing read them.

    Candidates come from two directions, unioned:
      (a) packets from meetings where entity_mentions links this project, and
      (b) packets whose text names the project outright.
    (b) matters because the mention-extraction pipeline links entities from
    agendas/minutes/actions reports only — it never reads agenda_item_pdf text
    — so a project can have a staff report in the corpus and no mention rows
    at all. Document.agenda_item_id is likewise never populated, so item-level
    narrowing happens here by matching the Granicus anchor text against the
    mentioned agenda item's title.
    """
    from councilhound.db.models import AgendaItem, Document, EntityMention, Meeting

    if session is None:
        return []

    mentions = []
    if project.entity_id is not None:
        mentions = session.execute(
            select(EntityMention.meeting_id, EntityMention.agenda_item_id)
            .where(EntityMention.entity_id == project.entity_id)
        ).all()
    meeting_ids = {m for m, _ in mentions}
    item_ids = {i for _, i in mentions if i is not None}

    item_titles = []
    if item_ids:
        item_titles = [t for (t,) in session.execute(
            select(AgendaItem.title).where(AgendaItem.id.in_(item_ids))).all() if t]

    base = (select(Document, Meeting.meeting_date)
            .join(Meeting, Meeting.id == Document.meeting_id)
            .where(Document.doc_type == "agenda_item_pdf",
                   Document.raw_text.isnot(None)))
    # LIKE metacharacters in a project name would silently widen the match
    name_pattern = "%" + re.sub(r"([%_\\])", r"\\\1", project.name).strip() + "%"
    conditions = [Document.raw_text.ilike(name_pattern, escape="\\")]
    if meeting_ids:
        conditions.append(Document.meeting_id.in_(meeting_ids))
    from sqlalchemy import or_
    rows = session.execute(base.where(or_(*conditions))).all()
    if not rows:
        return []

    def norm(text):
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

    project_key = norm(project.name)
    address_key = norm((project.address or "").split("-")[0])
    item_keys = [norm(t) for t in item_titles]

    def relevance(doc, meeting_date):
        title_norm = norm(doc.title)
        head = norm(doc.raw_text[:2000])
        score = 0
        if project_key and project_key in norm(doc.raw_text):
            score += 60
        # item-level match: this document IS the packet entry for the agenda
        # item the project was mentioned under
        if any(k and (k in title_norm or title_norm in k) for k in item_keys):
            score += 100
        if project_key and (project_key in title_norm or project_key in head):
            score += 50
        if address_key and len(address_key) > 4 and (address_key in title_norm
                                                    or address_key in head):
            score += 25
        for word in keywords:
            if norm(word) in title_norm:
                score += 10
            elif norm(word) in head:
                score += 4
        return score, meeting_date

    scored = [(relevance(doc, md), doc) for doc, md in rows]
    # keep only documents with some tie to this project, best first, newest
    # first within a score
    scored = [(s, doc) for s, doc in scored if s[0] > 0]
    scored.sort(key=lambda pair: (-pair[0][0], -(pair[0][1].toordinal() if pair[0][1] else 0)))

    docs: list[ProjectDocument] = []
    for (score, meeting_date), doc in scored[:max_docs]:
        label = f"Council packet: {doc.title or 'agenda item'}"
        if meeting_date:
            label += f" ({meeting_date})"
        docs.append(ProjectDocument(
            label=label, url=doc.source_url, text=doc.raw_text,
            provenance=prov(label, doc.source_url,
                            str(meeting_date) if meeting_date else "current"),
        ))
    log.info("gathered %d council-packet document(s) for %s",
             len(docs), project.external_slug)
    return docs


def gather_documents(project: CityProject, session=None,
                     include_meeting_docs: bool = True) -> list[ProjectDocument]:
    """Download + extract every linked PDF, newest-listed first, plus the
    directory-record pseudo-document and (when a session is supplied) the
    council-packet PDFs for meetings where the project was discussed.
    Unfetchable or unextractable documents are skipped with a warning —
    extraction quality degrades, silently fabricating text does not happen."""
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
    if include_meeting_docs:
        docs.extend(gather_meeting_documents(session, project))
    log.info("gathered %d documents for %s (%d with text)",
             len(project.documents or []) + 1, project.external_slug, len(docs))
    return docs
