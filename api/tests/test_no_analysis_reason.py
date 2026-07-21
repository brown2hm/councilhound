"""Every official project without a published impact analysis carries a
legible reason instead of a silent gap — modeled on the July 2026 prod set."""
from councilhound.db.models import CityProject, ProjectEvaluation


def _project(db, slug, name, description, status="Under Review", requests=None):
    p = CityProject(external_slug=slug, name=name, description=description,
                    official_status=status, requests=requests,
                    detail_url=f"https://example.gov/{slug}")
    db.add(p)
    db.flush()
    return p


def test_no_analysis_reasons(db, client):
    # synthesized -> button, no reason
    davies = _project(db, "Davies-Property", "Davies Property",
                      "replace a single-family home with up to 276 apartments")
    db.add(ProjectEvaluation(city_project_id=davies.id, status="synthesized"))
    # mid-pipeline -> in preparation
    gallery = _project(db, "Gallery", "Gallery at City Center",
                       "up to 392 apartments (multifamily units)")
    db.add(ProjectEvaluation(city_project_id=gallery.id, status="confirmed"))
    # no housing anywhere in the text -> resident-driven model can't run
    _project(db, "Taco-Bell", "Taco Bell",
             "a 2,090 square foot fast-food restaurant with a drive-through")
    # hotel rooms and a REMAINING single-family home are not a program
    _project(db, "Farr-House", "Farr House",
             "a hotel and hospitality venue with 96 rooms, spa and membership "
             "club; the colonial style single-family would remain on site",
             status="Pre-Application")
    # housing, but only a potential applicant's concept -> awaiting plans
    _project(db, "Courthouse-Plaza", "Courthouse Plaza",
             "The potential applicant proposes 315 multi-family residential units")
    # housing + submitted docs, just not run -> honest default
    _project(db, "Northfax-West", "Northfax West",
             "56 townhouses, 200 unit senior living facility",
             status="Under Construction")
    db.commit()

    rows = {p["slug"]: p for p in client.get("/development/").json()
            if p["source"] == "official"}
    assert rows["Davies-Property"]["no_analysis_reason"] is None
    assert rows["Davies-Property"]["has_evaluation"] is True
    assert rows["Gallery"]["no_analysis_reason"] == "analysis in preparation"
    assert rows["Taco-Bell"]["no_analysis_reason"] == "no residential program to model"
    assert rows["Farr-House"]["no_analysis_reason"] == "no residential program to model"
    assert rows["Courthouse-Plaza"]["no_analysis_reason"] == "awaiting submitted plans"
    assert rows["Northfax-West"]["no_analysis_reason"] == "not yet evaluated"
