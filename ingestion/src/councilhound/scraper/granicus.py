"""
Phase 1: Discovery & raw ingest (parsing half).

Parses the Granicus archive page (ViewPublisher.php?view_id=N) for City of
Fairfax. Verified structure (2026-07-11): the page is a sequence of year
blocks, each containing per-body <h3> section headers ("City Council
Meetings", "Community Development and Planning Meetings", ...) followed by a
<table class="listingTable"> of meeting rows. Row anatomy:

  - Name cell: an <a onClick="window.open('//.../MediaPlayer.php?view_id=13
    &clip_id=NNNN'...)"> play link (clip_id lives here, NOT in an href),
    followed by the meeting title text.
  - Date cell (headers="Date ..."): e.g. "Jul  7, 2026" (double space).
  - Duration cell: "03h 15m".
  - Links: AgendaViewer.php?view_id&clip_id (redirects to
    GeneratedAgendaViewer.php), MinutesViewer.php?view_id&clip_id&doc_id=<uuid>,
    direct https://archive-video.granicus.com/<slug>/<slug>_<uuid>.mp3/.mp4
    (slug = granicus.media_host_slug in the jurisdiction config).
  - Some rows carry a "Documents..." <select> whose <option value=...> are
    additional MinutesViewer docs, labeled e.g. "Minutes", "Reporter"
    (= "Council Actions" report, official votes/outcomes — not a transcript).

Rows without a clip_id (upcoming events, canceled meetings) are skipped.
There are NO caption tracks (/videos/<clip>/captions.vtt is an empty stub) —
transcripts come from the MP3 via Whisper in Phase 2.

Which <h3> sections are in scope comes from councilhound.bodies. City Council,
Planning Commission and School Board rows carry MP3/MP4 links; the advisory
boards (PRAB, HHCAB) are agenda + minutes only, and their agendas are
uploaded PDFs rather than Granicus-generated HTML (verified 2026-09-15).
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup

from councilhound import http
from councilhound.bodies import BODIES, BODY_KEYS, REGISTRY, Registry
from councilhound.config import JURISDICTION
from councilhound.jurisdiction import JurisdictionConfig
from councilhound.config import GRANICUS_BASE_URL

log = logging.getLogger(__name__)

# Archive <h3> section header -> body key (from the registry), for views laid
# out in sections. A section shared with other boards (the City files
# Planning Commission rows under "Community Development and Planning" next
# to BAR/BZA) is disambiguated by the body's title_must_contain rule.
SECTION_BODIES = {b.archive_section: k for k, b in BODIES.items() if b.archive_section}

IN_SCOPE_BODIES = BODY_KEYS


@dataclass
class DiscoveredDoc:
    label: str  # link/option text, e.g. 'Minutes', 'Reporter'
    url: str
    doc_type: str  # 'minutes' | 'actions_report' | 'other'


@dataclass
class DiscoveredMeeting:
    clip_id: str
    view_id: str
    body: str
    meeting_type: str
    meeting_date: date
    title: str
    duration_seconds: int | None = None
    agenda_url: str | None = None
    minutes_url: str | None = None
    audio_url: str | None = None
    video_url: str | None = None
    extra_docs: list[DiscoveredDoc] = field(default_factory=list)


@dataclass
class UpcomingEvent:
    event_id: str
    view_id: str
    title: str
    body: str | None  # None = out-of-scope committee/board, still listed
    starts_at: datetime | None  # city-local; None while the event is live
    in_progress: bool
    agenda_url: str | None


def _absolute(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return GRANICUS_BASE_URL + url
    return url


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DATE_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\b")


def _parse_date(text: str) -> date | None:
    """A 'Jul 7, 2026' / 'July 7, 2026' / 'Sept. 15, 2026' date anywhere in
    the text (the City has a Date column; the County only dates its titles)."""
    m = _DATE_RE.search(re.sub(r"\s+", " ", text))
    if not m:
        return None
    month = _MONTHS.get(m.group(1)[:3].lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def _parse_duration(text: str) -> int | None:
    m = re.search(r"(\d+)h\s*(\d+)m", text)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60


def classify(section_body: str, title: str,
             registry: Registry = REGISTRY) -> tuple[str, str] | None:
    """Map (body key of the archive section, row title) -> (body,
    meeting_type) per the body's config rules, or None if out of scope
    (Commission on the Arts, Electoral Board, BAR/BZA, etc.)."""
    body = registry.bodies.get(section_body)
    if body is None:
        return None
    t = title.lower()
    if body.title_must_contain and not any(s in t for s in body.title_must_contain):
        return None
    for needle, meeting_type in body.meeting_types:
        if needle in t:
            return body.key, meeting_type
    return body.key, body.default_meeting_type


def _classify_doc(label: str, cfg: JurisdictionConfig = JURISDICTION) -> str:
    """Document type of a MinutesViewer link from its label, per the
    jurisdiction's granicus.documents rules."""
    l = label.lower()
    docs = cfg.granicus.documents
    for rule in docs.label_rules:
        if rule.contains.lower() in l:
            return rule.type
    return docs.minutesviewer_default


def _select_clip(tr, cfg: JurisdictionConfig = JURISDICTION) -> str | None:
    """The row's clip id. A row can carry several player links (the County
    publishes an English-captions clip and a Spanish-captions clip); pick by
    the jurisdiction's row rules."""
    row_cfg = cfg.granicus.row
    found: list[tuple[str, str]] = []  # (clip_id, anchor text)
    for a in tr.find_all("a"):
        blob = (a.get("href") or "") + (a.get("onclick") or "")
        m = re.search(r"MediaPlayer\.php\?[^\"']*clip_id=(\d+)", blob)
        if m and m.group(1) not in [c for c, _ in found]:
            found.append((m.group(1), a.get_text(" ", strip=True)))
    if not found:
        m = re.search(r"MediaPlayer\.php\?[^\"']*clip_id=(\d+)", str(tr))
        return m.group(1) if m else None
    if row_cfg.clip_label_prefer:
        for clip_id, text in found:
            if row_cfg.clip_label_prefer.lower() in text.lower():
                return clip_id
    return found[-1][0] if row_cfg.clip_select == "last" else found[0][0]


def _parse_row(tr, section_body: str, view_id: str, cfg: JurisdictionConfig = JURISDICTION,
               registry: Registry = REGISTRY) -> DiscoveredMeeting | None:
    clip_id = _select_clip(tr, cfg)
    if not clip_id:
        return None  # upcoming/canceled: nothing archived to ingest

    name_td = tr.find("td", headers=re.compile(r"^Name"))
    title = name_td.get_text(" ", strip=True) if name_td else tr.get_text(" ", strip=True)[:120]
    classified = classify(section_body, title, registry)
    if not classified:
        return None
    body, meeting_type = classified

    date_td = tr.find("td", headers=re.compile(r"^Date"))
    meeting_date = _parse_date(date_td.get_text(" ", strip=True)) if date_td else _parse_date(title)
    if not meeting_date:
        log.warning("skipping clip %s (%r): unparseable date", clip_id, title)
        return None

    duration_td = tr.find("td", headers=re.compile(r"^Duration"))
    duration = _parse_duration(duration_td.get_text(strip=True)) if duration_td else None

    m = DiscoveredMeeting(
        clip_id=clip_id,
        view_id=view_id,
        body=body,
        meeting_type=meeting_type,
        meeting_date=meeting_date,
        title=title,
        duration_seconds=duration,
    )

    # Harvest links from both <a href> and "Documents..." <select><option value>
    row_cfg = cfg.granicus.row
    candidates = []
    for a in tr.find_all("a"):
        href = a.get("href", "")
        if (not href or href.startswith("javascript")) and a.get("onclick"):
            # the County wraps document links in window.open('//host/AgendaViewer.php?...')
            m_open = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", a["onclick"])
            href = m_open.group(1) if m_open else href
        candidates.append((a.get_text(strip=True), href))
    for opt in tr.find_all("option"):
        candidates.append((opt.get_text(strip=True), opt.get("value", "")))

    for label, url in candidates:
        if not url or url.startswith("javascript"):
            continue
        url = _absolute(url)
        if "AgendaViewer.php" in url and "clip_id" in url:
            m.agenda_url = m.agenda_url or url
        elif "MinutesViewer.php" in url:
            doc_type = _classify_doc(label, cfg)
            if doc_type == "minutes" and not m.minutes_url:
                m.minutes_url = url
            elif doc_type == "agenda" and not m.agenda_url:
                # the County's "minutes" link is its annotated agenda
                m.agenda_url = url
            else:
                m.extra_docs.append(DiscoveredDoc(label=label or doc_type, url=url, doc_type=doc_type))
        elif (row_cfg.external_archive and row_cfg.external_archive.enabled
              and row_cfg.external_archive.link_text_contains.lower() in (label or "").lower()):
            m.extra_docs.append(DiscoveredDoc(
                label=label, url=url, doc_type=row_cfg.external_archive.doc_type))
        elif url.endswith(".mp3"):
            m.audio_url = url
        elif url.endswith(".mp4"):
            m.video_url = url
    body_cfg = registry.bodies.get(body)
    if (not m.agenda_url and body_cfg and body_cfg.agenda_url_template
            and meeting_type == body_cfg.default_meeting_type):
        # the County's Planning Commission rows link no agenda (the cell is
        # commented out); its regular-meeting agendas live on the county
        # site by date. Committees and work sessions have no such file.
        m.agenda_url = meeting_date.strftime(body_cfg.agenda_url_template)
    return m


def parse_archive(html: str, view_id: str, cfg: JurisdictionConfig = JURISDICTION,
                  registry: Registry | None = None) -> list[DiscoveredMeeting]:
    """Parse the full archive page into in-scope DiscoveredMeetings, per the
    jurisdiction's layout for this view: 'sections' — <h3> headers name the
    body of the rows that follow (bodies[].archive_section); 'single' — the
    whole view is one body, every listing row is it."""
    if registry is None:
        registry = REGISTRY if cfg is JURISDICTION else Registry.from_config(cfg)
    soup = BeautifulSoup(html, "lxml")
    meetings: list[DiscoveredMeeting] = []
    view_cfg = cfg.view_for(view_id)
    layout = view_cfg.layout if view_cfg else "sections"

    if layout == "single":
        body = view_cfg.body
        for table in soup.find_all("table", class_="listingTable"):
            if table.get("id") == "upcoming":
                continue
            for tr in table.find_all("tr"):
                meeting = _parse_row(tr, body, view_id, cfg, registry)
                if meeting:
                    meetings.append(meeting)
        log.info("parsed %d meetings from single-body archive view_id=%s", len(meetings), view_id)
        return meetings

    sections = {b.archive_section: k for k, b in registry.bodies.items() if b.archive_section}
    section_body: str | None = None
    for el in soup.find_all(["h3", "table"]):
        if el.name == "h3":
            section_body = sections.get(el.get_text(strip=True))
            continue
        if section_body is None or "listingTable" not in (el.get("class") or []):
            continue
        for tr in el.find_all("tr"):
            meeting = _parse_row(tr, section_body, view_id, cfg, registry)
            if meeting:
                meetings.append(meeting)

    log.info("parsed %d in-scope meetings from archive view_id=%s", len(meetings), view_id)
    return meetings


def list_meetings(view_id: str) -> list[DiscoveredMeeting]:
    """Fetch the archive page for view_id and return in-scope meetings,
    newest first."""
    resp = http.get(f"{GRANICUS_BASE_URL}/ViewPublisher.php?view_id={view_id}")
    meetings = parse_archive(resp.text, view_id)
    meetings.sort(key=lambda m: m.meeting_date, reverse=True)
    return meetings


def classify_upcoming_title(title: str, registry: Registry = REGISTRY,
                            view_id: str | None = None) -> str | None:
    """Body key for an upcoming-events row, from its title alone (the
    upcoming table has no per-body sections). None = a body we don't track,
    still listed. Bodies are tried in config order, so joint sessions go to
    the body whose rule matches first; a view that belongs to one body
    (upcoming.default_for_view) claims its unmatched rows."""
    t = title.lower()
    for body in registry.bodies.values():
        if any(t.startswith(p) for p in body.upcoming_starts_with):
            return body.key
        if any(p in t for p in body.upcoming_contains):
            return body.key
    if view_id is not None:
        for body in registry.bodies.values():
            if body.upcoming_default_for_view == str(view_id):
                return body.key
    return None


def parse_upcoming(html: str, view_id: str, registry: Registry = REGISTRY) -> list[UpcomingEvent]:
    """Parse the 'Upcoming and In Progress Events' table on the same
    ViewPublisher page the archive lives on. Rows carry an event_id (clips
    only exist after the meeting), a date like 'July 14, 2026 - 07:00 PM'
    (or an 'In Progress' player link while live), and an AgendaViewer link."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="upcoming")
    if table is None:
        return []
    events = []
    for tr in table.find_all("tr"):
        name_td = tr.find("td", headers=re.compile(r"^EventName"))
        if name_td is None:
            continue
        title = re.sub(r"\s+", " ", name_td.get_text(strip=True))

        event_id = None
        for a in tr.find_all("a"):
            m = re.search(r"event_id=(\d+)", (a.get("href") or "") + (a.get("onclick") or ""))
            if m:
                event_id = m.group(1)
                break
        if not event_id:
            # Rows with no agenda posted yet carry no event_id-bearing link at
            # all: the agenda cell is empty and the eComment anchor is
            # href="#" with the id in a data attribute. That is the normal
            # state for a meeting announced before its agenda, so treating it
            # as unparseable silently emptied the whole upcoming table.
            for a in tr.find_all("a", attrs={"data-event-id": True}):
                candidate = a["data-event-id"].strip()
                if candidate.isdigit() and candidate != "0":
                    event_id = candidate
                    break
        if not event_id:
            continue

        date_td = tr.find("td", headers=re.compile(r"^EventDate"))
        if date_td is not None:
            for hidden in date_td.find_all("span", style=re.compile(r"display:\s*none")):
                hidden.decompose()  # the County hides an epoch for sorting in the cell
        date_text = re.sub(r"\s+", " ", date_td.get_text(" ", strip=True)) if date_td else ""
        starts_at, in_progress = None, "in progress" in date_text.lower()
        if not in_progress:
            m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\s*-\s*(\d{1,2}):(\d{2})\s*([AP]M)",
                          date_text, re.IGNORECASE)
            if m:
                month = _MONTHS.get(m.group(1)[:3].lower())
                hour = int(m.group(4)) % 12 + (12 if m.group(6).upper() == "PM" else 0)
                if month:
                    try:
                        starts_at = datetime(int(m.group(3)), month, int(m.group(2)), hour, int(m.group(5)))
                    except ValueError:
                        pass

        agenda_a = tr.find("a", href=re.compile(r"AgendaViewer\.php"))
        events.append(UpcomingEvent(
            event_id=event_id,
            view_id=view_id,
            title=title,
            body=classify_upcoming_title(title, registry, view_id=view_id),
            starts_at=starts_at,
            in_progress=in_progress,
            agenda_url=_absolute(agenda_a["href"]) if agenda_a else None,
        ))
    return events


def list_upcoming(view_id: str) -> list[UpcomingEvent]:
    resp = http.get(f"{GRANICUS_BASE_URL}/ViewPublisher.php?view_id={view_id}")
    return parse_upcoming(resp.text, view_id)


def fetch_agenda_text(agenda_url: str) -> str:
    """Plain text of an AgendaViewer target, for matching tracked entities
    against upcoming agendas. Council and Planning Commission agendas are
    Granicus-generated HTML; the advisory boards (PRAB, HHCAB) upload a PDF
    that AgendaViewer redirects to."""
    resp = http.get(agenda_url)
    if "pdf" in resp.headers.get("Content-Type", "").lower() or resp.content[:5] == b"%PDF-":
        import fitz  # pymupdf

        with fitz.open(stream=resp.content, filetype="pdf") as doc:
            return re.sub(r"\s+", " ", " ".join(page.get_text("text") for page in doc)).strip()
    return BeautifulSoup(resp.text, "lxml").get_text(" ", strip=True)


def parse_index_points(player_html: str) -> list[dict]:
    """Parse the official agenda index points from a MediaPlayer page.
    Granicus embeds human-indexed markers per agenda item:
      <div class="index-point" time="9" ...>1. Call the regular meeting...</div>
    Returns [{'label': '1', 'time': 9, 'text': ...}]; label is the leading
    item number normalized to match our agenda_items labels ('7a.' -> '7a')."""
    soup = BeautifulSoup(player_html, "lxml")
    points = []
    last_number = None
    for div in soup.find_all("div", class_="index-point"):
        time_attr = div.get("time")
        text = div.get_text(" ", strip=True)
        if time_attr is None or not text:
            continue
        label = None
        m = re.match(r"^\s*(\d+)([a-z])?[.)]\s", text)
        if m:
            last_number = m.group(1)
            label = (m.group(1) + (m.group(2) or "")).lower()
        else:
            # sub-items are indexed as bare letters ('a. Presentation...');
            # they belong to the last numbered item -> '3' + 'a' = '3a'
            sub = re.match(r"^\s*([a-z])[.)]\s", text, re.IGNORECASE)
            if sub and last_number:
                label = (last_number + sub.group(1)).lower()
        points.append({"label": label, "time": int(time_attr), "text": text})
    return points


_WORD = re.compile(r"[a-z0-9]+")


def _title_key(text: str) -> str:
    """Lowercased alphanumeric words with a leading item number, a leading
    clock time ('3:30') and dashes stripped — what an index point and an
    agenda item share when they describe the same item."""
    t = text.lower()
    t = re.sub(r"^\s*(\d{1,2}:\d{2}\s+)?(\d+[a-z]?[.)]\s+)?", "", t)
    return " ".join(_WORD.findall(t))


def match_index_point_by_title(title: str | None, points: list[dict], min_words: int = 4,
                               min_overlap: float = 0.8) -> int | None:
    """The time of the index point whose text describes this agenda item,
    for archives whose item numbering doesn't survive extraction: the item
    title and the index text share most of their words (containment of the
    shorter word set in the longer, so a district suffix or a reworded tail
    doesn't break the match). Short titles are not trusted ('Closed
    Session' would claim any closed-session marker). None when nothing fits."""
    if not title:
        return None
    words = _title_key(title).split()
    if len(words) < min_words:
        return None
    key = set(words)
    best: tuple[float, int, int] | None = None  # (overlap, shared, time)
    for p in points:
        pw = _title_key(p["text"]).split()
        if len(pw) < min_words:
            continue
        shared = len(key & set(pw))
        overlap = shared / min(len(key), len(set(pw)))
        if overlap >= min_overlap and (best is None or (overlap, shared) > best[:2]):
            best = (overlap, shared, p["time"])
    return best[2] if best else None


def fetch_index_points(clip_id: str, view_id: str) -> list[dict]:
    """Fetch + parse a clip's official agenda index points."""
    resp = http.get(f"{GRANICUS_BASE_URL}/MediaPlayer.php?view_id={view_id}&clip_id={clip_id}")
    return parse_index_points(resp.text)


def extract_agenda_item_links(agenda_html: str, base_url: str = GRANICUS_BASE_URL) -> list[dict]:
    """From a GeneratedAgendaViewer page, return the MetaViewer.php PDF links:
    [{'meta_id': ..., 'url': ..., 'label': <anchor text>}]."""
    soup = BeautifulSoup(agenda_html, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"MetaViewer\.php")):
        url = _absolute(a["href"])
        meta = re.search(r"meta_id=(\d+)", url)
        if not meta or meta.group(1) in seen:
            continue
        seen.add(meta.group(1))
        items.append({"meta_id": meta.group(1), "url": url, "label": a.get_text(" ", strip=True)})
    return items
