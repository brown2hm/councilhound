"""
Phase 1: Discovery & raw ingest.

Given a Granicus view_id for City of Fairfax, VA (fairfax.granicus.com),
discover meetings and download their agenda/minutes documents and either a
caption track or the video/audio file.

Known URL patterns (confirmed by research, see PLAN.md section 0):
  - Meeting list:      {BASE}/ViewPublisher.php?view_id={view_id}  (also &mode=rss)
  - Video player:      {BASE}/player/clip/{clip_id}?meta_id={meta_id}
  - Agenda (HTML):     {BASE}/GeneratedAgendaViewer.php?view_id={view_id}&clip_id={clip_id}
  - Agenda item doc:   {BASE}/MetaViewer.php?view_id={view_id}&clip_id={clip_id}&meta_id={meta_id}

TODO (first task): confirm whether clip pages expose a caption/VTT track.
If yes, prefer that over Whisper transcription entirely - much cheaper.
"""
from dataclasses import dataclass
from typing import Optional
import requests
from bs4 import BeautifulSoup

from fairfax_kb.config import GRANICUS_BASE_URL


@dataclass
class DiscoveredMeeting:
    clip_id: str
    view_id: str
    meeting_date: str
    title: str
    meta_id: Optional[str] = None


def list_meetings(view_id: str) -> list[DiscoveredMeeting]:
    """
    Fetch the meeting archive for a given view_id and return discovered
    meetings. Try the RSS feed first (ViewPublisher.php?view_id=X&mode=rss),
    fall back to parsing the HTML archive page if RSS isn't available.

    Not yet implemented - this is the first thing the coding agent should
    build and test against real Fairfax data.
    """
    raise NotImplementedError(
        "Phase 1 task: implement meeting discovery for view_id via RSS or "
        "HTML parsing of ViewPublisher.php"
    )


def fetch_agenda_documents(meeting: DiscoveredMeeting) -> list[dict]:
    """
    Given a discovered meeting, fetch the generated agenda HTML, follow
    links to individual agenda-item PDFs (MetaViewer.php), and fetch the
    minutes document. Returns a list of dicts matching the `documents`
    table shape (doc_type, source_url, local_path, agenda_item_label).
    """
    raise NotImplementedError("Phase 1 task")


def fetch_captions_or_video(meeting: DiscoveredMeeting, out_dir: str) -> dict:
    """
    Attempt to fetch a caption/VTT track for the meeting's clip. If none
    exists, fall back to downloading the video/audio via the clip's
    "Video Download" link for later Whisper transcription (Phase 2).

    Returns a dict describing what was obtained, e.g.
    {"kind": "captions", "path": "..."} or {"kind": "video", "path": "..."}.
    """
    raise NotImplementedError("Phase 1 task - confirm caption availability first")
