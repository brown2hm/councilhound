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
</tr>
</table>
</body></html>
"""


def test_parse_archive_scope_and_fields():
    meetings = parse_archive(ARCHIVE_SNIPPET, view_id="13")
    assert [m.clip_id for m in meetings] == ["4609", "4500"]  # BAR + School Board excluded

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


def test_classify():
    assert classify("city_council", "City Council Regular Meeting") == ("city_council", "council_regular")
    assert classify("city_council", "City Council Work Session") == ("city_council", "council_work_session")
    assert classify("city_council", "City Council Retreat") == ("city_council", "council_retreat")
    assert classify("community_development", "BAR Regular Meeting") is None
    assert classify("community_development", "Planning Commission Work Session") == (
        "planning_commission", "planning_commission",
    )


def test_extract_agenda_item_links():
    html = """
    <p><a href="MetaViewer.php?view_id=13&clip_id=4609&meta_id=134013">Staff report 7a</a></p>
    <p><a href="MetaViewer.php?view_id=13&clip_id=4609&meta_id=134013">dup link</a></p>
    <p><a href="MetaViewer.php?view_id=13&clip_id=4609&meta_id=134016">Ordinance 2026-04</a></p>
    """
    items = extract_agenda_item_links(html)
    assert [i["meta_id"] for i in items] == ["134013", "134016"]
    assert items[0]["label"] == "Staff report 7a"
