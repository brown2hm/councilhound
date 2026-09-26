"""
Phase 1: Discovery & raw ingest (orchestration half).

discover()        -> upsert meetings rows from the archive page
fetch_documents() -> download agenda HTML, agenda-item PDFs, minutes,
                     actions reports; upsert documents rows
fetch_media()     -> captions VTT / MP3 / MP4 audio for Phase 2 transcription

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
from councilhound.config import GRANICUS_BASE_URL, JURISDICTION, RAW_DATA_DIR
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
    bodies: tuple[str, ...] | None = None,
) -> dict:
    """Scrape the archive page and upsert in-scope meetings. Returns counts.
    `bodies` narrows to those body keys — for backfilling one newly tracked
    body without re-walking every other body's history."""
    discovered = granicus.list_meetings(view_id)
    if since:
        discovered = [m for m in discovered if m.meeting_date >= since]
    if until:
        discovered = [m for m in discovered if m.meeting_date <= until]
    if bodies:
        discovered = [m for m in discovered if m.body in bodies]
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


def _ext_for(content_type: str, content: bytes = b"") -> str:
    """Pick the on-disk extension the text extractor dispatches on. Granicus
    labels Word agendas (closed sessions) `application/msword` even when the
    payload is a .docx zip, so sniff the bytes when the header is vague."""
    if "pdf" in content_type:
        return ".pdf"
    if "html" in content_type:
        return ".html"
    if "msword" in content_type or "wordprocessingml" in content_type:
        return ".docx"
    head = content[:1024]
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head.startswith(b"PK") and b"[Content_Types].xml" in head:
        return ".docx"
    if b"<html" in head.lower() or b"<!doctype html" in head.lower():
        return ".html"
    return ".bin"


def _fetch_doc_content(session: Session, meeting: Meeting, doc: Document, filename_base: str) -> None:
    if doc.local_path and os.path.exists(doc.local_path) and os.path.getsize(doc.local_path) > 0:
        return
    resp = http.get(doc.source_url)
    ext = _ext_for(resp.headers.get("Content-Type", ""), resp.content)
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

    if not (meeting.video_url or meeting.audio_url):
        # Advisory boards (PRAB, HHCAB) publish agenda + minutes with no
        # recording; Granicus has no player page for such clips (404), and
        # index points are timestamps into a recording anyway.
        return 0
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
        if t is None:
            # labels that don't line up (the County numbers items per
            # section, so the extractor writes 'Action Items 2' while the
            # player says '2.'): fall back to the item's title
            t = granicus.match_index_point_by_title(item.title, points)
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
        .where(Meeting.id.in_(has_items), Meeting.id.not_in(timestamped),
               # unrecorded meetings have nothing to link and would be
               # retried (and 404) on every run
               (Meeting.video_url.isnot(None)) | (Meeting.audio_url.isnot(None)))
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


def sync_projects(session: Session, fetch_details: bool = True, source=None) -> dict:
    """Refresh the jurisdiction's official development-project records from
    its projects adapter (councilhound.scraper.projects).

    The official directory is the set of records; ArcGIS/detail coordinates
    are mirrored into EntityGeocode for map pins. Unmatched official projects
    are created as tracker project entities so the directory can cross-link
    uniformly to topic pages.
    """
    from councilhound.scraper.projects import get_source

    source = source or get_source(JURISDICTION)
    if source is None:
        log.info("sync_projects: no projects adapter for %s; skipped", JURISDICTION.slug)
        return {"skipped": "no projects adapter"}
    discovered, html_complete = source.list_projects(fetch_details=fetch_details)
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


def _captions_url(meeting: Meeting) -> str:
    return f"{GRANICUS_BASE_URL}/videos/{meeting.granicus_clip_id}/captions.vtt"


def _fetch_captions(meeting: Meeting) -> str | None:
    """Save the clip's WebVTT captions when the tenant publishes real ones;
    None when the endpoint 404s or the file is empty/placeholder."""
    from councilhound.extraction.captions import is_real_captions

    resp = http.get_http_session().get(_captions_url(meeting), timeout=120)
    if resp.status_code != 200 or not is_real_captions(resp.text):
        log.info("clip %s: no usable captions (HTTP %s, %d bytes)",
                 meeting.granicus_clip_id, resp.status_code, len(resp.content))
        return None
    path = os.path.join(_meeting_dir(meeting), "captions.vtt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def extract_audio_track(video_path: str, audio_path: str) -> str:
    """Copy the first audio stream of a video container into its own file
    (no re-encode) with PyAV, which ships with faster-whisper — the dev box
    has no ffmpeg binary."""
    import av

    with av.open(video_path) as src:
        in_stream = next((s for s in src.streams if s.type == "audio"), None)
        if in_stream is None:
            raise ValueError(f"{video_path}: no audio stream")
        with av.open(audio_path, "w") as dst:
            out_stream = dst.add_stream_from_template(in_stream)
            for packet in src.demux(in_stream):
                if packet.dts is None:
                    continue
                packet.stream = out_stream
                dst.mux(packet)
    return audio_path


def fetch_media(session: Session, meeting: Meeting) -> str | None:
    """Fetch what the transcript stage will consume, per the jurisdiction's
    granicus.media.sources order: captions (VTT), the archive MP3, or the
    MP4's audio track. Sets audio_local_path to whichever landed.

    Works from residential IPs with our browser User-Agent. Granicus's CDN
    hard-blocks datacenter IPs (verified from Fly 2026-08-02: 403 on both
    archive-video and the archive-stream HLS host), so cloud runs fail fast
    here (http.download's cold-403 path) and audio is fetched/transcribed
    from a residential machine instead. Captions come from the tenant's own
    host, which cloud runs can reach."""
    if meeting.audio_local_path and os.path.exists(meeting.audio_local_path) \
            and os.path.getsize(meeting.audio_local_path) > 0:
        return meeting.audio_local_path
    media = JURISDICTION.granicus.media
    os.makedirs(_meeting_dir(meeting), exist_ok=True)
    path: str | None = None
    for source in media.sources:
        if source == "captions":
            path = _fetch_captions(meeting)
        elif source == "mp3":
            if not meeting.audio_url:
                continue
            path = os.path.join(_meeting_dir(meeting), "audio.mp3")
            http.download(meeting.audio_url, path, timeout=600)
        elif source == "mp4_audio_extract":
            if not meeting.video_url:
                continue
            video = os.path.join(_meeting_dir(meeting), "video.mp4")
            path = os.path.join(_meeting_dir(meeting), "audio.m4a")
            if not (os.path.exists(path) and os.path.getsize(path) > 0):
                http.download(meeting.video_url, video, timeout=3600)
                extract_audio_track(video, path)
                if not media.keep_video:
                    os.remove(video)
        if path:
            break
    if not path:
        log.warning("meeting %s (%s) has no media source (%s)", meeting.id, meeting.title,
                    ", ".join(media.sources))
        return None
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
    bodies: tuple[str, ...] | None = None,
) -> IngestRun:
    """Full Phase 1 pass: discover, then fetch documents (+ media) for every
    meeting not yet fully fetched. Per-meeting errors are recorded, not fatal."""
    run = IngestRun(phase="phase1_ingest", errors=[])
    session.add(run)
    session.commit()

    discover(session, view_id, since=since, until=until, limit=limit, bodies=bodies)

    q = select(Meeting).where(Meeting.granicus_view_id == view_id)
    if since:
        q = q.where(Meeting.meeting_date >= since)
    if until:
        q = q.where(Meeting.meeting_date <= until)
    if bodies:
        q = q.where(Meeting.body.in_(bodies))
    meetings = session.scalars(q.order_by(Meeting.meeting_date.desc())).all()
    if limit:
        meetings = meetings[:limit]

    errors: list[dict] = []
    processed = 0
    for meeting in meetings:
        try:
            fetch_documents(session, meeting)
            # 'fetched' marks docs-downloaded for structuring; never downgrade
            # an already-'extracted' meeting on a window re-scan.
            if meeting.status == "discovered":
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
