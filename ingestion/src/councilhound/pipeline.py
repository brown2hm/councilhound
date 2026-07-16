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

from councilhound import http
from councilhound.config import RAW_DATA_DIR
from councilhound.db.models import CityProject, Document, EntityGeocode, IngestRun, Meeting
from councilhound.entities import resolve_entity
from councilhound.scraper import granicus
from councilhound.scraper import fairfax_projects

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


def link_index_points(session: Session, meeting: Meeting) -> int:
    """Fetch the clip's official agenda index points and set start_seconds on
    matching agenda_items (matched by normalized label). Returns matches."""
    from councilhound.db.models import AgendaItem

    items = session.scalars(
        select(AgendaItem).where(AgendaItem.meeting_id == meeting.id)
    ).all()
    if not items:
        return 0
    points = granicus.fetch_index_points(meeting.granicus_clip_id, meeting.granicus_view_id)
    by_label: dict[str, int] = {}
    for p in points:
        if p["label"] is not None:
            by_label.setdefault(p["label"], p["time"])  # first occurrence = item start
    matched = 0
    for item in items:
        t = by_label.get(item.label.lower().rstrip("."))
        if t is not None:
            item.start_seconds = t
            matched += 1
    session.commit()
    if points:
        log.info("meeting %s: %d/%d agenda items matched to index points",
                 meeting.granicus_clip_id, matched, len(items))
    return matched


def link_index_points_pending(session: Session, limit: int | None = None) -> dict:
    """Run link_index_points for every meeting that has agenda items but no
    timestamps yet."""
    from councilhound.db.models import AgendaItem

    timestamped = (
        select(AgendaItem.meeting_id)
        .where(AgendaItem.start_seconds.isnot(None))
        .distinct()
    )
    has_items = select(AgendaItem.meeting_id).distinct()
    q = (
        select(Meeting)
        .where(Meeting.id.in_(has_items), Meeting.id.not_in(timestamped))
        .order_by(Meeting.meeting_date.desc())
    )
    if limit:
        q = q.limit(limit)
    meetings = session.scalars(q).all()
    done = failed = 0
    for meeting in meetings:
        try:
            link_index_points(session, meeting)
            done += 1
        except Exception:
            session.rollback()
            log.exception("index points failed for clip %s", meeting.granicus_clip_id)
            failed += 1
    return {"meetings": done, "failed": failed, "candidates": len(meetings)}


def sync_upcoming(session: Session, view_id: str) -> dict:
    """Refresh the upcoming-events table from the ViewPublisher page. Full
    replacement per view: past events graduate into real Meetings via the
    archive, so there is no history to preserve here."""
    from councilhound.db.models import UpcomingMeeting

    events = granicus.list_upcoming(view_id)
    old = {u.granicus_event_id: u for u in session.scalars(
        select(UpcomingMeeting).where(UpcomingMeeting.granicus_view_id == view_id))}

    agendas = 0
    for ev in events:
        agenda_text = None
        if ev.agenda_url:
            try:
                agenda_text = granicus.fetch_agenda_text(ev.agenda_url)
                agendas += 1
            except Exception:
                log.exception("agenda fetch failed for event %s", ev.event_id)
        row = old.pop(ev.event_id, None) or UpcomingMeeting(granicus_event_id=ev.event_id)
        row.granicus_view_id = ev.view_id
        row.title = ev.title
        row.body = ev.body
        row.starts_at = ev.starts_at
        row.in_progress = ev.in_progress
        row.agenda_url = ev.agenda_url
        row.agenda_text = agenda_text if agenda_text else row.agenda_text
        row.synced_at = datetime.now(timezone.utc)
        session.add(row)
    for stale in old.values():  # no longer listed -> happened or was pulled
        session.delete(stale)
    session.commit()
    result = {"upcoming": len(events), "agendas_fetched": agendas, "removed": len(old)}
    log.info("sync_upcoming view %s: %s", view_id, result)
    return result


def _upsert_project_geocode(session: Session, entity_id: int, lat, lng, address: str | None) -> None:
    if lat is None or lng is None:
        return
    geo = session.scalar(select(EntityGeocode).where(EntityGeocode.entity_id == entity_id))
    if geo is None:
        geo = EntityGeocode(entity_id=entity_id)
        session.add(geo)
    geo.status = "ok"
    geo.lat = lat
    geo.lng = lng
    geo.matched_address = address
    geo.geocoded_at = datetime.now(timezone.utc)


def sync_projects(session: Session, fetch_details: bool = True) -> dict:
    """Refresh official City of Fairfax development-project records.

    The city directory is the set of records; ArcGIS/detail coordinates are
    mirrored into EntityGeocode for map pins. Unmatched official projects are
    created as tracker project entities so the directory can cross-link
    uniformly to topic pages.
    """
    discovered, html_complete = fairfax_projects.list_projects(fetch_details=fetch_details)
    old = {p.external_slug: p for p in session.scalars(select(CityProject))}

    created = updated = linked = geocoded = 0
    now = datetime.now(timezone.utc)
    for d in discovered:
        entity = resolve_entity(session, "project", d.name, create=True)
        if entity:
            entity.entity_type = "project"
        if entity and d.official_status and not entity.current_status:
            entity.current_status = d.official_status.lower().replace("-", "_").replace(" ", "_")
        row = old.pop(d.external_slug, None)
        if row is None:
            row = CityProject(external_slug=d.external_slug)
            session.add(row)
            created += 1
        else:
            updated += 1
        if entity:
            row.entity_id = entity.id
            linked += 1
        fields = {
            "name": d.name, "project_type": d.project_type, "division": d.division,
            "official_status": d.official_status, "status_code": d.status_code,
            "description": d.description, "requests": d.requests, "address": d.address,
            "applicant": d.applicant, "planner_name": d.planner_name,
            "planner_phone": d.planner_phone, "planner_email": d.planner_email,
            "detail_url": d.detail_url, "image_url": d.image_url,
            "documents": d.documents, "official_timeline": d.official_timeline,
            "lat": d.lat, "lng": d.lng,
        }
        for key, value in fields.items():
            # A partial (ArcGIS-only) sync must not blank out the richer HTML
            # fields seeded by a full local run — only overwrite what it has.
            if html_complete or value not in (None, "", [], {}):
                setattr(row, key, value)
        row.synced_at = now
        if entity:
            _upsert_project_geocode(session, entity.id, d.lat, d.lng, d.address)
            if d.lat is not None and d.lng is not None:
                geocoded += 1

    # Only an authoritative full-HTML sync prunes; a partial ArcGIS-only run
    # leaves HTML-only projects alone (and never wipes everything on a miss).
    removed = 0
    if html_complete and discovered:
        removed = len(old)
        for stale in old.values():
            session.delete(stale)
    session.commit()
    result = {
        "projects": len(discovered),
        "created": created,
        "updated": updated,
        "linked": linked,
        "geocoded": geocoded,
        "removed": removed,
        "complete": html_complete,
    }
    log.info("sync_projects: %s", result)
    return result


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
            meeting.status = "fetched"
            session.commit()
            processed += 1
        except Exception as exc:  # keep going; failures land in the run log
            session.rollback()
            log.exception("ingest failed for meeting clip_id=%s", meeting.granicus_clip_id)
            errors.append({"clip_id": meeting.granicus_clip_id, "error": str(exc)})
            continue
        # Audio is best-effort and NOT a gate: a meeting can be structured
        # from its agenda/minutes text without it, and a just-happened
        # meeting often has documents posted before the MP3 is downloadable.
        # A failure here leaves the meeting 'fetched' so structuring proceeds;
        # transcription retries on the next run once the audio is available.
        if not skip_media:
            try:
                fetch_media(session, meeting)
            except Exception as exc:
                session.rollback()
                log.warning("media fetch deferred for clip_id=%s: %s",
                            meeting.granicus_clip_id, exc)
                errors.append({"clip_id": meeting.granicus_clip_id,
                               "error": f"media: {exc}"})

    run.finished_at = datetime.now(timezone.utc)
    run.meetings_processed = processed
    run.errors = errors
    session.commit()
    return run
