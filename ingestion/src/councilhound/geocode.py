"""Geocode 'location' entities via the US Census geocoder (free, no key).

Street addresses ('10300 Willard Way') resolve; area names ('Old Town')
miss and are recorded as such so they aren't retried nightly. The suffix
anchors bare street addresses to the city.
"""
import logging
import os
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound import http
from councilhound.db.models import Entity, EntityGeocode

log = logging.getLogger(__name__)

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
GEOCODE_SUFFIX = os.environ.get("GEOCODE_SUFFIX", "Fairfax, VA")


def geocode_address(address: str) -> dict | None:
    """Return {'lat','lng','matched_address'} or None on no match."""
    resp = http.get(CENSUS_URL, params={
        "address": f"{address}, {GEOCODE_SUFFIX}",
        "benchmark": "Public_AR_Current",
        "format": "json",
    }, timeout=30)
    matches = resp.json().get("result", {}).get("addressMatches", [])
    if not matches:
        return None
    m = matches[0]
    return {
        "lat": m["coordinates"]["y"],
        "lng": m["coordinates"]["x"],
        "matched_address": m.get("matchedAddress"),
    }


def geocode_pending(session: Session, limit: int | None = None, pause: float = 0.5) -> dict:
    """Geocode location entities that have no geocode row yet."""
    done = select(EntityGeocode.entity_id).subquery()
    q = (select(Entity)
         .where(Entity.entity_type == "location", Entity.id.notin_(select(done.c.entity_id)))
         .order_by(Entity.id))
    if limit:
        q = q.limit(limit)
    entities = session.scalars(q).all()

    ok = miss = failed = 0
    for entity in entities:
        try:
            hit = geocode_address(entity.name)
        except Exception:
            log.exception("geocode failed for %s", entity.canonical_slug)
            failed += 1  # transient: no row, retried next run
            continue
        if hit:
            session.add(EntityGeocode(entity_id=entity.id, status="ok", **hit))
            ok += 1
        else:
            session.add(EntityGeocode(entity_id=entity.id, status="miss"))
            miss += 1
        session.commit()
        time.sleep(pause)

    result = {"geocoded": ok, "missed": miss, "errors": failed, "candidates": len(entities)}
    log.info("geocode_pending: %s", result)
    return result
