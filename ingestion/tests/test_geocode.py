"""Geocoding: Census response parsing, miss recording (no eternal retries),
and transient-failure behavior."""
from unittest.mock import MagicMock

from councilhound import geocode as gc
from councilhound.db.models import Entity, EntityGeocode


def _census_response(matches):
    resp = MagicMock()
    resp.json.return_value = {"result": {"addressMatches": matches}}
    return resp


def test_geocode_pending(db_session, monkeypatch):
    s = db_session
    s.add_all([
        Entity(entity_type="location", name="10300 Willard Way", canonical_slug="10300-willard-way"),
        Entity(entity_type="location", name="Old Town", canonical_slug="old-town"),
        Entity(entity_type="project", name="Not A Place", canonical_slug="not-a-place"),
    ])
    s.commit()

    def fake_get(url, params=None, **kw):
        if "10300" in params["address"]:
            return _census_response([{
                "coordinates": {"x": -77.31, "y": 38.85},
                "matchedAddress": "10300 WILLARD WAY, FAIRFAX, VA, 22030",
            }])
        return _census_response([])

    monkeypatch.setattr(gc.http, "get", fake_get)
    result = gc.geocode_pending(s, pause=0)
    assert result == {"geocoded": 1, "missed": 1, "errors": 0, "candidates": 2}

    ok = s.query(EntityGeocode).filter_by(status="ok").one()
    assert float(ok.lat) == 38.85 and float(ok.lng) == -77.31

    # second run: both locations already have rows (ok or miss) -> no retries
    assert gc.geocode_pending(s, pause=0)["candidates"] == 0
