from councilhound.scraper.fairfax_projects import (
    DiscoveredProject,
    list_projects,
    parse_project_detail,
    parse_project_list,
)


LIST_HTML = """
<div class="list-item-container item-no-date">
  <article>
    <a href="https://www.fairfaxva.gov/Property-Business/Development/Projects/Courthouse-Plaza">
      <h2 class="list-item-title">
        <span><img src="/project-icons/gold-private-development-icon.png" alt="Private Development Icon"></span>
        Courthouse Plaza
      </h2>
      <p>Potential rezoning proposal.</p>
    </a>
  </article>
</div>
<div class="list-item-container item-no-date">
  <article>
    <a href="/Property-Business/Development/Projects/Blenheim-Blvd-Multimodal-Improvements">
      <h2 class="list-item-title">
        <span><img src="/project-icons/coral-city-project-icon.png"></span>
        Blenheim Blvd Multimodal Improvements
      </h2>
      <p>Reconstruction with sidewalks.</p>
    </a>
  </article>
</div>
"""


DETAIL_HTML = """
<main>
<h1>Courthouse Plaza</h1>
<ul>
  <li>Project type Private Development</li>
  <li>Project division Community &amp; Development</li>
  <li>Project schedule Under Review</li>
</ul>
<h2>Project</h2>
<ul><li>A City Council Work Session is scheduled.</li></ul>
<h2>Background</h2>
<p>The potential applicant proposes a rezoning.</p>
<h2>Requests</h2>
<p>Potential applications include a rezoning.</p>
<h2>Plans</h2>
<p><a href="/files/plan.pdf">May 7, 2026 Master Development Plan (PDF)</a></p>
<h2>Location</h2>
<p>10300 Willard Way, Fairfax, VA 22030 <a href="https://maps.example">View Map</a></p>
<p>38.8476065,-77.3025809</p>
<h2>Contact details</h2>
<p>Clara Schweiger, Planner II</p>
<p>(703) 293-7130</p>
<p>clara.schweiger@fairfaxva.gov</p>
<h2>Applicant</h2>
<p>Applicant's Representative: Molly Novotny Curata Partners</p>
</main>
"""


def test_parse_project_list():
    projects = parse_project_list(LIST_HTML)
    assert [p.external_slug for p in projects] == [
        "Courthouse-Plaza",
        "Blenheim-Blvd-Multimodal-Improvements",
    ]
    assert projects[0].project_type == "Private Development"
    assert projects[1].project_type == "City Project"


def test_parse_project_detail():
    base = DiscoveredProject(
        external_slug="Courthouse-Plaza",
        name="Courthouse Plaza",
        detail_url="https://www.fairfaxva.gov/Property-Business/Development/Projects/Courthouse-Plaza",
        description="List summary.",
    )
    detail = parse_project_detail(DETAIL_HTML, base)
    assert detail.official_status == "Under Review"
    assert detail.division == "Community & Development"
    assert detail.description == "The potential applicant proposes a rezoning."
    assert detail.requests == "Potential applications include a rezoning."
    assert detail.documents[0]["url"].endswith("/files/plan.pdf")
    assert detail.lat == 38.8476065
    assert detail.lng == -77.3025809
    assert detail.planner_email == "clara.schweiger@fairfaxva.gov"
    assert "Molly Novotny" in detail.applicant


def test_list_projects_merges_arcgis_stale_name(monkeypatch):
    html = LIST_HTML + """
    <div class="list-item-container"><article>
      <a href="/Property-Business/Development/Projects/10340-Democracy-Lane">
        <h2 class="list-item-title">10340 Democracy Lane</h2>
      </a>
    </article></div>
    """
    monkeypatch.setattr(
        "councilhound.scraper.fairfax_projects._fetch_project_list_pages",
        lambda: [html],
    )
    monkeypatch.setattr(
        "councilhound.scraper.fairfax_projects.fetch_arcgis_projects",
        lambda: {
            "Democracy-Lane": {
                "name": "Democracy Lane",
                "detail_url": "https://example.test/Democracy-Lane",
                "official_status": "Pre-Application",
                "lat": 38.86,
                "lng": -77.30,
            }
        },
    )

    projects = list_projects(fetch_details=False)
    democracy = [p for p in projects if "Democracy" in p.name]
    assert len(democracy) == 1
    assert democracy[0].name == "10340 Democracy Lane"
    assert democracy[0].external_slug == "10340-Democracy-Lane"
    assert democracy[0].official_status == "Pre-Application"
