"""Parser tests against a miniature archive page mirroring the verified
structure of fairfax.granicus.com/ViewPublisher.php?view_id=13 (2026-07-11)."""
import datetime

from councilhound.scraper.granicus import classify, extract_agenda_item_links, parse_archive

ARCHIVE_SNIPPET = """
<html><body>
<h3>City Council Meetings</h3>
<table class="listingTable">
<tr>
  <td class="listItem" headers="Name" id="City-Council-Special-Meeting">
    <a href="javascript:void(0);" onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&clip_id=4609','player')">play</a>&nbsp;City Council Special Meeting &amp; Work Session
  </td>
  <td class="listItem" headers="Date City-Council-Special-Meeting" nowrap>Jul  7, 2026</td>
  <td class="listItem" headers="Duration City-Council-Special-Meeting">03h 15m</td>
  <td class="listItem"><a href="//fairfax.granicus.com/AgendaViewer.php?view_id=13&clip_id=4609">Agenda</a></td>
  <td class="listItem">
    <select onchange="window.open(this.value)">
      <option value="">Documents...</option>
      <option value="//fairfax.granicus.com/MinutesViewer.php?view_id=13&clip_id=4609&doc_id=aaa">Reporter</option>
      <option value="//fairfax.granicus.com/MinutesViewer.php?view_id=13&clip_id=4609&doc_id=bbb">Minutes</option>
    </select>
  </td>
  <td class="listItem"><a href="https://archive-video.granicus.com/fairfax/fairfax_uuid1.mp3">MP3</a></td>
  <td class="listItem"><a href="https://archive-video.granicus.com/fairfax/fairfax_uuid1.mp4">MP4</a></td>
</tr>
<tr>
  <td class="listItem" headers="Name">Upcoming meeting, no clip yet</td>
  <td class="listItem" headers="Date">Aug  1, 2026</td>
</tr>
</table>
<h3>Community Development and Planning Meetings</h3>
<table class="listingTable">
<tr>
  <td class="listItem" headers="Name">
    <a onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&clip_id=4500','p')">play</a>&nbsp;Planning Commission Regular Meeting/Work Session
  </td>
  <td class="listItem" headers="Date">Jun 22, 2026</td>
  <td class="listItem" headers="Duration">03h 06m</td>
</tr>
<tr>
  <td class="listItem" headers="Name">
    <a onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&clip_id=4501','p')">play</a>&nbsp;BAR Regular Meeting
  </td>
  <td class="listItem" headers="Date">Jun 23, 2026</td>
  <td class="listItem" headers="Duration">01h 00m</td>
</tr>
</table>
<h3>School Board Meetings</h3>
<table class="listingTable">
<tr>
  <td class="listItem" headers="Name">
    <a onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&clip_id=4502','p')">play</a>&nbsp;School Board Regular Meeting
  </td>
  <td class="listItem" headers="Date">Jul  1, 2026</td>
  <td class="listItem" headers="Duration">01h 12m</td>
  <td class="listItem"><a href="https://archive-video.granicus.com/fairfax/fairfax_uuid2.mp3">MP3</a></td>
</tr>
</table>
<h3>Park and Recreation Advisory Board Meetings</h3>
<table class="listingTable">
<tr>
  <td class="listItem" headers="Name">
    <a onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&clip_id=4642','p')">play</a>&nbsp;PRAB Regular Meeting
  </td>
  <td class="listItem" headers="Date">Sep 10, 2026</td>
  <td class="listItem" headers="Duration"></td>
  <td class="listItem"><a href="//fairfax.granicus.com/AgendaViewer.php?view_id=13&clip_id=4642">Agenda</a></td>
  <td class="listItem"><a href="//fairfax.granicus.com/MinutesViewer.php?view_id=13&clip_id=4642&doc_id=ccc">Minutes</a></td>
</tr>
</table>
<h3>Housing and Healthy Communities Advisory Board Meetings</h3>
<table class="listingTable">
<tr>
  <td class="listItem" headers="Name">
    <a onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&clip_id=4640','p')">play</a>&nbsp;HHCAB Committee Meeting (Housing Trust Fund)
  </td>
  <td class="listItem" headers="Date">Sep  2, 2026</td>
  <td class="listItem" headers="Duration"></td>
</tr>
</table>
<h3>Commission for Women Meetings</h3>
<table class="listingTable">
<tr>
  <td class="listItem" headers="Name">
    <a onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&clip_id=4600','p')">play</a>&nbsp;Commission for Women Regular Meeting
  </td>
  <td class="listItem" headers="Date">Sep  3, 2026</td>
  <td class="listItem" headers="Duration"></td>
</tr>
</table>
</body></html>
"""


def test_parse_archive_scope_and_fields():
    meetings = parse_archive(ARCHIVE_SNIPPET, view_id="13")
    # BAR and Commission for Women excluded; the three added bodies are in
    assert [m.clip_id for m in meetings] == ["4609", "4500", "4502", "4642", "4640"]

    council = meetings[0]
    assert council.body == "city_council"
    assert council.meeting_type == "council_special"
    assert council.meeting_date == datetime.date(2026, 7, 7)
    assert council.duration_seconds == 3 * 3600 + 15 * 60
    assert council.agenda_url.endswith("AgendaViewer.php?view_id=13&clip_id=4609")
    assert council.minutes_url.endswith("doc_id=bbb")
    assert council.audio_url.endswith(".mp3")
    assert council.video_url.endswith(".mp4")
    reporter = [d for d in council.extra_docs if d.doc_type == "actions_report"]
    assert len(reporter) == 1 and reporter[0].url.endswith("doc_id=aaa")

    pc = meetings[1]
    assert pc.body == "planning_commission"
    assert pc.meeting_type == "planning_commission"

    sb, prab, hhcab = meetings[2:]
    assert (sb.body, sb.meeting_type) == ("school_board", "school_board_regular")
    assert sb.audio_url.endswith("fairfax_uuid2.mp3")
    assert (prab.body, prab.meeting_type) == ("prab", "prab_meeting")
    assert prab.audio_url is None and prab.duration_seconds is None  # no recording
    assert prab.agenda_url.endswith("clip_id=4642") and prab.minutes_url.endswith("doc_id=ccc")
    assert (hhcab.body, hhcab.meeting_type) == ("hhcab", "hhcab_committee")


def test_classify():
    assert classify("city_council", "City Council Regular Meeting") == ("city_council", "council_regular")
    assert classify("city_council", "City Council Work Session") == ("city_council", "council_work_session")
    assert classify("city_council", "City Council Retreat") == ("city_council", "council_retreat")
    assert classify("planning_commission", "BAR Regular Meeting") is None
    assert classify("planning_commission", "Planning Commission Work Session") == (
        "planning_commission", "planning_commission",
    )
    assert classify("school_board", "School Board Work Session") == ("school_board", "school_board_work_session")
    assert classify("school_board", "School Board Closed Meeting") == ("school_board", "school_board_closed")
    assert classify("school_board", "Joint School Board and City Council Work Session") == (
        "school_board", "school_board_meeting",
    )
    assert classify("prab", "PRAB and School Board Joint Meeting") == ("prab", "prab_meeting")
    assert classify("hhcab", "HHCAB Regular Meeting") == ("hhcab", "hhcab_meeting")
    assert classify("hhcab", "HHCAB Committee Meeting (Home Sharing)") == ("hhcab", "hhcab_committee")
    assert classify("electoral_board", "Electoral Board Regular Meeting") is None


def test_classify_upcoming_title():
    from councilhound.scraper.granicus import classify_upcoming_title

    assert classify_upcoming_title("City Council Work Session") == "city_council"
    assert classify_upcoming_title("Planning Commission Regular Meeting/Work Session") == "planning_commission"
    assert classify_upcoming_title("School Board Retreat") == "school_board"
    assert classify_upcoming_title("Joint School Board/City Council Work Session") == "school_board"
    assert classify_upcoming_title("PRAB Regular Meeting") == "prab"
    assert classify_upcoming_title("HHCAB Committee Meeting (Homelessness)") == "hhcab"
    assert classify_upcoming_title("BAR Regular Meeting") is None
    assert classify_upcoming_title("Commission for Women Regular meeting") is None


def test_extract_agenda_item_links():
    html = """
    <p><a href="MetaViewer.php?view_id=13&clip_id=4609&meta_id=134013">Staff report 7a</a></p>
    <p><a href="MetaViewer.php?view_id=13&clip_id=4609&meta_id=134013">dup link</a></p>
    <p><a href="MetaViewer.php?view_id=13&clip_id=4609&meta_id=134016">Ordinance 2026-04</a></p>
    """
    items = extract_agenda_item_links(html)
    assert [i["meta_id"] for i in items] == ["134013", "134016"]
    assert items[0]["label"] == "Staff report 7a"


def test_parse_index_points():
    from councilhound.scraper.granicus import parse_index_points

    html = """
    <div class="index-point" role="tab" time="9">1. Call the regular meeting to order.</div>
    <div class="index-point" role="tab" time="32">2. Pledge of Allegiance.</div>
    <div class="index-point" role="tab" time="60">a. Presentation of a proclamation.</div>
    <div class="index-point" role="tab" time="439">7a. Rezoning application Z-25-01.</div>
    <div class="index-point" role="tab" time="500">Unlabeled comment period</div>
    """
    pts = parse_index_points(html)
    assert [(p["label"], p["time"]) for p in pts] == [
        ("1", 9), ("2", 32), ("2a", 60), ("7a", 439), (None, 500),
    ]


def test_parse_upcoming():
    from councilhound.scraper.granicus import parse_upcoming

    html = """
    <table class="listingTable" id="upcoming">
      <tr>
        <td class="listItem" headers="EventName" scope="row">Planning Commission Regular Meeting/Work Session</td>
        <td class="listItem" headers="EventDate Planning-Commission">
          <a href="javascript:void(0);" onClick="window.open('//fairfax.granicus.com/MediaPlayer.php?view_id=13&event_id=3537','player')">In Progress - View Event</a>
        </td>
        <td class="listItem" headers="EventAgendaLink Planning-Commission">
          <a href="//fairfax.granicus.com/AgendaViewer.php?view_id=13&event_id=3537">Agenda</a>
        </td>
      </tr>
      <tr>
        <td class="listItem" headers="EventName" scope="row">City Council Meeting</td>
        <td class="listItem" headers="EventDate City-Council-Meeting">July&nbsp;14,&nbsp;2026 - 07:00&nbsp;PM</td>
        <td class="listItem" headers="EventAgendaLink City-Council-Meeting">
          <a href="//fairfax.granicus.com/AgendaViewer.php?view_id=13&event_id=2872">Agenda</a>
        </td>
      </tr>
      <tr>
        <td class="listItem" headers="EventName" scope="row">Environmental Sustainability Committee</td>
        <td class="listItem" headers="EventDate Env">July&nbsp;15,&nbsp;2026 - 07:00&nbsp;PM</td>
        <td class="listItem" headers="EventAgendaLink Env">
          <a href="//fairfax.granicus.com/AgendaViewer.php?view_id=13&event_id=3590">Agenda</a>
        </td>
      </tr>
    </table>
    """
    events = parse_upcoming(html, "13")
    assert [e.event_id for e in events] == ["3537", "2872", "3590"]

    live, council, committee = events
    assert live.in_progress and live.starts_at is None
    assert live.body == "planning_commission"
    assert council.body == "city_council"
    assert council.starts_at.isoformat() == "2026-07-14T19:00:00"
    assert council.agenda_url.startswith("https://fairfax.granicus.com/AgendaViewer.php")
    assert committee.body is None  # out of scope, still listed


def test_parse_upcoming_without_agenda_link():
    """A meeting announced before its agenda is posted has an empty agenda
    cell and no event_id-bearing link at all — the id lives only in the
    eComment anchor's data attribute. This silently emptied the whole
    upcoming table (August 2026)."""
    from councilhound.scraper.granicus import parse_upcoming

    html = """
    <table class="listingTable" id="upcoming">
      <tr>
        <th id="EventName" scope="col">Name</th>
        <th id="EventDate" scope="col">Date</th>
      </tr>
      <tr class="odd">
        <td class="listItem" headers="EventName" id="City-Council-Special-Meeting-" scope="row">City Council Special Meeting </td>
        <td class="listItem" headers="EventDate City-Council-Special-Meeting-" nowrap="">
                August 18, 2026 - 06:00 PM
        </td>
        <td class="listItem" headers="EventAgendaLink City-Council-Special-Meeting-">
        </td>
        <td class="listItem" headers="EcommentsLink City-Council-Special-Meeting-"><a aria-label="eComment: City Council Special Meeting " class="ecomment" data-event-id="3682" data-rollover-id="0" href="#" link="#" rel="ecomment" style="display:none;" target="_blank">eComment</a></td>
      </tr>
    </table>
    """
    events = parse_upcoming(html, "13")
    assert [e.event_id for e in events] == ["3682"]

    ev = events[0]
    assert ev.body == "city_council"
    assert ev.starts_at.isoformat() == "2026-08-18T18:00:00"
    assert ev.agenda_url is None
    assert not ev.in_progress
    # data-rollover-id="0" sits on the same anchor and must never win
    assert ev.event_id != "0"
