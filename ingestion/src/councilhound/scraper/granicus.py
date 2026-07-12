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
    direct https://archive-video.granicus.com/fairfax/fairfax_<uuid>.mp3/.mp4.
  - Some rows carry a "Documents..." <select> whose <option value=...> are
    additional MinutesViewer docs, labeled e.g. "Minutes", "Reporter"
    (= "Council Actions" report, official votes/outcomes — not a transcript).

Rows without a clip_id (upcoming events, canceled meetings) are skipped.
There are NO caption tracks (/videos/<clip>/captions.vtt is an empty stub) —
transcripts come from the MP3 via Whisper in Phase 2.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup

from councilhound import http
from councilhound.config import GRANICUS_BASE_URL

log = logging.getLogger(__name__)

# Archive <h3> section header -> body key. Planning Commission meetings live
# in the "Community Development and Planning" section mixed with BAR/BZA rows,
# so that section additionally filters on the row title.
SECTION_BODIES = {
    "City Council Meetings": "city_council",
    "Community Development and Planning Meetings": "community_development",
}

IN_SCOPE_BODIES = ("city_council", "planning_commission")


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


def _absolute(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return GRANICUS_BASE_URL + url
    return url


def _parse_date(text: str) -> date | None:
    cleaned = re.sub(r"\s+", " ", text).strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_duration(text: str) -> int | None:
    m = re.search(r"(\d+)h\s*(\d+)m", text)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60


def classify(section_body: str, title: str) -> tuple[str, str] | None:
    """Map (archive section, row title) -> (body, meeting_type), or None if
    out of scope (School Board, committees, BAR/BZA, etc.)."""
    t = title.lower()
    if section_body == "city_council":
        if "retreat" in t:
            return "city_council", "council_retreat"
        if "special" in t:
            return "city_council", "council_special"
        if "work session" in t:
            return "city_council", "council_work_session"
        if "regular" in t:
            return "city_council", "council_regular"
        return "city_council", "council_meeting"
    if section_body == "community_development" and "planning commission" in t:
        return "planning_commission", "planning_commission"
    return None


def _classify_doc(label: str) -> str:
    l = label.lower()
    if "reporter" in l or "action" in l:
        return "actions_report"
    if "minutes" in l:
        return "minutes"
    return "other"


def _parse_row(tr, section_body: str, view_id: str) -> DiscoveredMeeting | None:
    row_html = str(tr)
    clip_match = re.search(r"MediaPlayer\.php\?[^\"']*clip_id=(\d+)", row_html)
    if not clip_match:
        return None  # upcoming/canceled: nothing archived to ingest

    name_td = tr.find("td", headers=re.compile(r"^Name"))
    title = name_td.get_text(" ", strip=True) if name_td else tr.get_text(" ", strip=True)[:120]
    classified = classify(section_body, title)
    if not classified:
        return None
    body, meeting_type = classified

    date_td = tr.find("td", headers=re.compile(r"^Date"))
    meeting_date = _parse_date(date_td.get_text(strip=True)) if date_td else None
    if not meeting_date:
        log.warning("skipping clip %s (%r): unparseable date", clip_match.group(1), title)
        return None

    duration_td = tr.find("td", headers=re.compile(r"^Duration"))
    duration = _parse_duration(duration_td.get_text(strip=True)) if duration_td else None

    m = DiscoveredMeeting(
        clip_id=clip_match.group(1),
        view_id=view_id,
        body=body,
        meeting_type=meeting_type,
        meeting_date=meeting_date,
        title=title,
        duration_seconds=duration,
    )

    # Harvest links from both <a href> and "Documents..." <select><option value>
    candidates = [(a.get_text(strip=True), a.get("href", "")) for a in tr.find_all("a")]
    for opt in tr.find_all("option"):
        candidates.append((opt.get_text(strip=True), opt.get("value", "")))

    for label, url in candidates:
        if not url or url.startswith("javascript"):
            continue
        url = _absolute(url)
        if "AgendaViewer.php" in url and "clip_id" in url:
            m.agenda_url = m.agenda_url or url
        elif "MinutesViewer.php" in url:
            doc_type = _classify_doc(label)
            if doc_type == "minutes" and not m.minutes_url:
                m.minutes_url = url
            else:
                m.extra_docs.append(DiscoveredDoc(label=label or doc_type, url=url, doc_type=doc_type))
        elif url.endswith(".mp3"):
            m.audio_url = url
        elif url.endswith(".mp4"):
            m.video_url = url
    return m


def parse_archive(html: str, view_id: str) -> list[DiscoveredMeeting]:
    """Parse the full archive page into in-scope DiscoveredMeetings."""
    soup = BeautifulSoup(html, "lxml")
    meetings: list[DiscoveredMeeting] = []
    section_body: str | None = None

    for el in soup.find_all(["h3", "table"]):
        if el.name == "h3":
            section_body = SECTION_BODIES.get(el.get_text(strip=True))
            continue
        if section_body is None or "listingTable" not in (el.get("class") or []):
            continue
        for tr in el.find_all("tr"):
            meeting = _parse_row(tr, section_body, view_id)
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
