"""Index the documents the City lists on each development project's page so
/ask can search them: application narratives, staff reports, statements of
justification, transportation studies.

Runs LOCALLY (fairfaxva.gov blocks cloud IPs). PDFs come from the same
on-disk cache the impact pipeline fills, downloading only what's missing,
and the passages are written to whichever database DATABASE_URL points at
(production through `flyctl proxy`, like okf-sync and impact-push).

Drawing sets, renderings and technical appendices are skipped: by label,
and by measure when a file has too little text per page to be prose. Each
passage keeps the page it starts on, so a citation can open the PDF there."""
import datetime
import logging
import re
from pathlib import Path

import fitz  # pymupdf
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from councilhound import http
from councilhound.db.models import CityProject, ProjectDocumentChunk
from councilhound.embeddings.embed import embed_texts
from councilhound.extraction.pdf_text import _sanitize

log = logging.getLogger(__name__)

PASSAGE_CHARS = 900
MIN_CHARS_PER_PAGE = 400      # below this a file is drawings, not prose
MAX_PASSAGES_PER_DOC = 400
MAX_DOC_BYTES = 60_000_000
EMBED_BATCH = 64

# drawings, maps and data tables: little prose, lots of noise
SKIP_LABEL = re.compile(
    r"plan sheets|\bsheets?\b \d|drawings?|elevations?|renderings?|perspective|\bplats?\b|survey|"
    r"technical appendix|appendix|appendices|exhibits? only|landscape plan|photometric|"
    r"site plan set|architectural|massing|floor plans?", re.I)
_SIZE = re.compile(r"\((?:PDF,\s*)?([\d.]+)\s*(KB|MB|GB)\)", re.I)
_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|"
                   r"November|December)\s+\d{1,2},\s+\d{4}")


def label_date(label: str) -> datetime.date | None:
    m = _DATE.search(label or "")
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(0), "%B %d, %Y").date()
    except ValueError:
        return None


def listed_bytes(label: str) -> int | None:
    m = _SIZE.search(label or "")
    if not m:
        return None
    return int(float(m.group(1)) * {"KB": 1e3, "MB": 1e6, "GB": 1e9}[m.group(2).upper()])


def wanted(entry: dict) -> bool:
    """A listed document worth indexing: a PDF, not a drawing set, not huge."""
    url, label = entry.get("url") or "", entry.get("label") or ""
    if not url.lower().endswith(".pdf") or SKIP_LABEL.search(label):
        return False
    size = listed_bytes(label)
    return size is None or size <= MAX_DOC_BYTES


def _cached_pdf(project: CityProject, url: str) -> Path:
    """The impact pipeline's cache path for this PDF, downloading it if missing."""
    from councilhound.impact.cache import atomic_write_bytes, raw_path
    from councilhound.impact.intake.documents import _safe_filename
    from councilhound.scraper.fairfax_projects import FAIRFAX_HEADERS

    dest = raw_path("projects", project.external_slug, _safe_filename(url))
    if not (dest.exists() and dest.stat().st_size > 0):
        resp = http.get(url, headers=FAIRFAX_HEADERS, timeout=180)
        atomic_write_bytes(dest, resp.content)
    return dest


def passages(path: Path) -> list[tuple[int, str]]:
    """(page, text) passages of up to about PASSAGE_CHARS, or [] when the
    file reads as drawings rather than prose."""
    with fitz.open(str(path)) as doc:
        pages = [_sanitize(p.get_text("text")) for p in doc]
    if not pages or sum(len(p) for p in pages) / len(pages) < MIN_CHARS_PER_PAGE:
        return []
    out: list[tuple[int, str]] = []
    for number, text in enumerate(pages, start=1):
        # PDF lines wrap mid-sentence; paragraphs are blank-line separated
        paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
        cur = ""
        for p in paragraphs:
            if len(p) < 3:
                continue
            if cur and len(cur) + len(p) + 1 > PASSAGE_CHARS:
                out.append((number, cur))
                cur = ""
            cur = f"{cur} {p}".strip()
            while len(cur) > PASSAGE_CHARS * 1.5:   # one long paragraph: cut at a sentence
                cut = cur.rfind(". ", 0, PASSAGE_CHARS) + 1 or PASSAGE_CHARS
                out.append((number, cur[:cut].strip()))
                cur = cur[cut:].strip()
        if cur:
            out.append((number, cur))
    return out[:MAX_PASSAGES_PER_DOC]


def index_project(session: Session, project: CityProject, refresh: bool = False) -> dict:
    """Index every wanted document listed on one project. Already-indexed
    documents are skipped unless refresh; documents no longer listed are
    removed."""
    stats = {"indexed": 0, "skipped": 0, "unchanged": 0, "failed": 0, "passages": 0}
    listed = [e for e in (project.documents or []) if e.get("url")]
    done = set(session.scalars(select(ProjectDocumentChunk.doc_url).where(
        ProjectDocumentChunk.city_project_id == project.id).distinct()))
    gone = done - {e["url"] for e in listed}
    if gone:
        session.execute(delete(ProjectDocumentChunk).where(ProjectDocumentChunk.doc_url.in_(gone)))
    for entry in listed:
        url, label = entry["url"], (entry.get("label") or "document").strip()
        if not wanted(entry):
            stats["skipped"] += 1
            continue
        if url in done and not refresh:
            stats["unchanged"] += 1
            continue
        try:
            found = passages(_cached_pdf(project, url))
        except Exception as exc:
            log.warning("could not read %s: %s", url, exc)
            stats["failed"] += 1
            continue
        if not found:
            stats["skipped"] += 1
            continue
        vectors = []
        for i in range(0, len(found), EMBED_BATCH):
            vectors += embed_texts([t for _, t in found[i:i + EMBED_BATCH]])
        session.execute(delete(ProjectDocumentChunk).where(ProjectDocumentChunk.doc_url == url))
        session.add_all(ProjectDocumentChunk(
            city_project_id=project.id, doc_url=url, doc_label=label, doc_date=label_date(label),
            page=page, ordinal=n, text=text, embedding=vec)
            for n, ((page, text), vec) in enumerate(zip(found, vectors)))
        session.commit()
        stats["indexed"] += 1
        stats["passages"] += len(found)
        log.info("%s: %s — %d passages", project.name, label, len(found))
    session.commit()
    return stats


def index_all(session: Session, slug: str | None = None, refresh: bool = False) -> dict:
    q = select(CityProject).order_by(CityProject.name)
    if slug:
        q = q.where(CityProject.external_slug == slug)
    totals: dict[str, int] = {}
    for project in session.scalars(q).all():
        for k, v in index_project(session, project, refresh).items():
            totals[k] = totals.get(k, 0) + v
    totals["documents_in_index"] = session.scalar(
        select(func.count(func.distinct(ProjectDocumentChunk.doc_url)))) or 0
    return totals
