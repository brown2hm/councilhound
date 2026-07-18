"""GTFS transit context: stop locations + weekday service intensity.

Feed URLs come from the jurisdiction YAML (pinned during setup, discovered
via the Mobility Database — never guessed in code). Transit is a light input
this branch (the connectivity module is a follow-up), so an unpinned or
unreachable feed degrades to an empty layer with a manifest note instead of
failing the whole context build.
"""
from __future__ import annotations

import logging

from councilhound import http
from councilhound.impact.cache import Manifest, context_dir, raw_path
from councilhound.impact.provenance import prov

log = logging.getLogger(__name__)


def load_stops(ctx):
    """GeoDataFrame of stops: {stop_id, stop_name, feed, weekday_trips, geometry}."""
    import geopandas as gpd
    import pandas as pd

    slug = ctx.cfg.slug
    path = context_dir(slug) / "transit_stops.geoparquet"
    if path.exists():
        return gpd.read_parquet(path)

    frames = []
    provenance = []
    for feed_url in ctx.cfg.transit_feeds:
        try:
            frames.append(_stops_for_feed(feed_url))
            provenance.append(prov("GTFS feed", feed_url, "current").model_dump())
        except Exception as exc:
            log.warning("GTFS feed %s failed (%s); skipping", feed_url, exc)
            provenance.append(prov("GTFS feed (FAILED)", feed_url, "current",
                                   f"skipped: {exc}").model_dump())

    if frames:
        stops = pd.concat(frames, ignore_index=True)
        gdf = gpd.GeoDataFrame(
            stops.drop(columns=["stop_lon", "stop_lat"]),
            geometry=gpd.points_from_xy(stops["stop_lon"], stops["stop_lat"]),
            crs="EPSG:4326",
        )
    else:
        note = ("no transit feeds pinned" if not ctx.cfg.transit_feeds
                else "all pinned feeds failed")
        log.warning("transit layer empty: %s", note)
        gdf = gpd.GeoDataFrame(
            {"stop_id": [], "stop_name": [], "feed": [], "weekday_trips": []},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
        )
    gdf.to_parquet(path)
    Manifest(slug).record("transit_stops", provenance, {"stops": len(gdf)})
    return gdf


def _stops_for_feed(feed_url: str):
    """Weekday trips-per-stop for one GTFS zip (service-intensity proxy)."""
    import gtfs_kit as gk
    import pandas as pd

    fname = feed_url.rstrip("/").split("/")[-1] or "feed.zip"
    if not fname.endswith(".zip"):
        fname += ".zip"
    local = raw_path("gtfs", "current", fname)
    if not local.exists():
        http.download(feed_url, str(local))
    feed = gk.read_feed(str(local), dist_units="mi")

    # weekday service_ids from calendar (or busiest date fallback)
    if feed.calendar is not None and not feed.calendar.empty:
        weekday = feed.calendar[
            feed.calendar[["monday", "tuesday", "wednesday", "thursday", "friday"]].sum(axis=1) >= 5
        ]["service_id"]
        trips = feed.trips[feed.trips["service_id"].isin(weekday)]
    else:
        trips = feed.trips
    stop_trip_counts = (
        feed.stop_times[feed.stop_times["trip_id"].isin(trips["trip_id"])]
        .groupby("stop_id")["trip_id"].nunique().rename("weekday_trips")
    )
    stops = feed.stops.merge(stop_trip_counts, on="stop_id", how="left")
    stops["weekday_trips"] = stops["weekday_trips"].fillna(0)
    stops["feed"] = fname
    return pd.DataFrame(stops[["stop_id", "stop_name", "feed", "weekday_trips",
                               "stop_lon", "stop_lat"]])
