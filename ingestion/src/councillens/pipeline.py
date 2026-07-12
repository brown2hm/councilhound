"""
Phase 1: Discovery & raw ingest (orchestration half).

discover()        -> upsert meetings rows from the archive page
fetch_documents() -> download agenda HTML, agenda-item PDFs, minutes,
                     actions reports; upsert documents rows
fetch_media()     -> download the meeting MP3 for Phase 2 transcription

All steps are idempotent: meetings upsert on (view_id, clip_id), documents
upsert on source_url, downloads skip existing non-empty files. Per-meeting
failures are logged into the IngestRun row and don't abort the run.
"""
import logging
import os
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from councillens import http
from councillens.config import RAW_DATA_DIR
from councillens.db.models import Document, IngestRun, Meeting
from councillens.scraper import granicus

log = logging.getLogger(__name__)


def _meeting_dir(meeting: Meeting) -> str:
    return os.path.join(RAW_DATA_DIR, meeting.granicus_clip_id)


def discover(
    session: Session,
    view_id: str,
    since: date | None = None,
    until: date | None = None,
    limit: int | None = None,
) -> dict:
    """Scrape the archive page and upsert in-scope meetings. Returns counts."""
    discovered = granicus.list_meetings(view_id)
    if since:
        discovered = [m for m in discovered if m.meeting_date >= since]
    if until:
        discovered = [m for m in discovered if m.meeting_date <= until]
    if limit:
        discovered = discovered[:limit]

    created = updated = 0
    for d in discovered:
        row = session.scalar(
            select(Meeting).where(
                Meeting.granicus_view_id == d.view_id,
                Meeting.granicus_clip_id == d.clip_id,
            )
        )
        if row is None:
            row = Meeting(
                granicus_clip_id=d.clip_id,
                granicus_view_id=d.view_id,
                status="discovered",
            )
            session.add(row)
            created += 1
        else:
            updated += 1
        row.body = d.body
        row.meeting_type = d.meeting_type
        row.meeting_date = d.meeting_date
        row.title = d.title
        row.duration_seconds = d.duration_seconds
        row.agenda_url = d.agenda_url
        row.minutes_url = d.minutes_url
        row.audio_url = d.audio_url
        row.video_url = d.video_url

        # Extra docs (e.g. the "Reporter" Council Actions report) become
        # documents rows immediately; content is fetched in fetch_documents.
        for doc in d.extra_docs:
            _upsert_document(session, row, doc.doc_type, doc.url, title=doc.label)

    session.commit()
    log.info("discover view_id=%s: %d created, %d already known", view_id, created, updated)
    return {"created": created, "updated": updated, "total_in_scope": len(discovered)}


def _upsert_document(session: Session, meeting: Meeting, doc_type: str, source_url: str,
                     title: str | None = None) -> Document:
    doc = session.scalar(select(Document).where(Document.source_url == source_url))
    if doc is None:
        doc = Document(meeting_id=meeting.id, doc_type=doc_type, source_url=source_url, title=title)
        session.add(doc)
        session.flush()
    return doc


def _ext_for(content_type: str) -> str:
    if "pdf" in content_type:
        return ".pdf"
    if "html" in content_type:
        return ".html"
    return ".bin"


def _fetch_doc_content(session: Session, meeting: Meeting, doc: Document, filename_base: str) -> None:
    if doc.local_path and os.path.exists(doc.local_path) and os.path.getsize(doc.local_path) > 0:
        return
    resp = http.get(doc.source_url)
    ext = _ext_for(resp.headers.get("Content-Type", ""))
    path = os.path.join(_meeting_dir(meeting), filename_base + ext)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(resp.content)
    doc.local_path = path
    doc.fetched_at = datetime.now(timezone.utc)


def fetch_documents(session: Session, meeting: Meeting) -> int:
    """Fetch agenda HTML (+ its agenda-item PDFs), minutes, and any extra
    docs for one meeting. Returns number of documents with content on disk."""
    fetched = 0

    if meeting.agenda_url:
        agenda_doc = _upsert_document(session, meeting, "agenda", meeting.agenda_url, title="Agenda")
        _fetch_doc_content(session, meeting, agenda_doc, "agenda")
        fetched += 1
        # Follow MetaViewer links inside the agenda to per-item PDFs
        if agenda_doc.local_path and agenda_doc.local_path.endswith(".html"):
            with open(agenda_doc.local_path, encoding="utf-8", errors="replace") as f:
                items = granicus.extract_agenda_item_links(f.read())
            for item in items:
                item_doc = _upsert_document(
                    session, meeting, "agenda_item_pdf", item["url"], title=item["label"]
                )
                _fetch_doc_content(session, meeting, item_doc, f"item_{item['meta_id']}")
                fetched += 1

    if meeting.minutes_url:
        minutes_doc = _upsert_document(session, meeting, "minutes", meeting.minutes_url, title="Minutes")
        _fetch_doc_content(session, meeting, minutes_doc, "minutes")
        fetched += 1

    for doc in session.scalars(
        select(Document).where(Document.meeting_id == meeting.id, Document.local_path.is_(None))
    ).all():
        _fetch_doc_content(session, meeting, doc, f"{doc.doc_type}_{doc.id}")
        fetched += 1

    session.commit()
    return fetched


def fetch_media(session: Session, meeting: Meeting) -> str | None:
    """Download the meeting MP3 (audio for Phase 2 transcription). Direct
    archive-video.granicus.com URLs work with our browser User-Agent."""
    if not meeting.audio_url:
        log.warning("meeting %s (%s) has no audio_url", meeting.id, meeting.title)
        return None
    if meeting.audio_local_path and os.path.exists(meeting.audio_local_path) \
            and os.path.getsize(meeting.audio_local_path) > 0:
        return meeting.audio_local_path
    path = os.path.join(_meeting_dir(meeting), "audio.mp3")
    http.download(meeting.audio_url, path, timeout=600)
    meeting.audio_local_path = path
    session.commit()
    return path


def run_ingest(
    session: Session,
    view_id: str,
    since: date | None = None,
    until: date | None = None,
    limit: int | None = None,
    skip_media: bool = False,
) -> IngestRun:
    """Full Phase 1 pass: discover, then fetch documents (+ media) for every
    meeting not yet fully fetched. Per-meeting errors are recorded, not fatal."""
    run = IngestRun(phase="phase1_ingest", errors=[])
    session.add(run)
    session.commit()

    discover(session, view_id, since=since, until=until, limit=limit)

    q = select(Meeting).where(Meeting.granicus_view_id == view_id)
    if since:
        q = q.where(Meeting.meeting_date >= since)
    if until:
        q = q.where(Meeting.meeting_date <= until)
    meetings = session.scalars(q.order_by(Meeting.meeting_date.desc())).all()
    if limit:
        meetings = meetings[:limit]

    errors: list[dict] = []
    processed = 0
    for meeting in meetings:
        try:
            fetch_documents(session, meeting)
            if not skip_media:
                fetch_media(session, meeting)
            meeting.status = "fetched"
            session.commit()
            processed += 1
        except Exception as exc:  # keep going; failures land in the run log
            session.rollback()
            log.exception("ingest failed for meeting clip_id=%s", meeting.granicus_clip_id)
            errors.append({"clip_id": meeting.granicus_clip_id, "error": str(exc)})

    run.finished_at = datetime.now(timezone.utc)
    run.meetings_processed = processed
    run.errors = errors
    session.commit()
    return run
