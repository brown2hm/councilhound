"""`impact-context` driver: build/refresh every context layer with timings.

Layers build lazily on first access everywhere else; this command exists to
front-load the expensive cold build (target: < 30 min cold, < 30 s warm) and
to print the quality-gate numbers in one place.
"""
from __future__ import annotations

import time

from councilhound.impact.cache import context_dir

# layer name -> filenames to delete on --refresh
LAYER_FILES = {
    "boundary": ["boundary.geojson"],
    "networks": ["walk_graph.graphml", "drive_graph.graphml", "node_weights.parquet"],
    "census": ["census_bg_*.parquet"],
    "lodes": ["lodes_*.parquet"],
    "pois": ["pois.geoparquet", "node_weights.parquet"],
    "transit": ["transit_stops.geoparquet"],
    "parcels": ["parcels.geoparquet", "value_per_acre.geojson"],
}


def _clear(slug: str, layer: str) -> None:
    base = context_dir(slug)
    patterns = LAYER_FILES.get(layer)
    if patterns is None:
        raise SystemExit(f"unknown layer '{layer}' (choose from {', '.join(LAYER_FILES)} or all)")
    for pattern in patterns:
        for path in base.glob(pattern):
            path.unlink()


def build_context(jurisdiction: str, refresh: str | None = None, echo=print) -> None:
    from councilhound.impact.jurisdiction import JurisdictionContext

    if refresh:
        layers = list(LAYER_FILES) if refresh == "all" else [refresh]
        for layer in layers:
            _clear(jurisdiction, layer)
        echo(f"cleared: {', '.join(layers)}")

    ctx = JurisdictionContext(jurisdiction)
    stages = [
        ("boundary", lambda: ctx.boundary),
        ("census_bg", lambda: ctx.census_bg),
        ("lodes", lambda: ctx.lodes),
        ("pois", lambda: ctx.pois),
        ("walk_graph", lambda: ctx.walk_graph),
        ("drive_graph", lambda: ctx.drive_graph),
        ("node_weights", lambda: ctx.node_weights),
        ("transit_stops", lambda: ctx.transit_stops),
        ("parcels", lambda: ctx.parcels),
    ]
    from councilhound.impact.cache import Manifest
    total_start = time.monotonic()
    for name, loader in stages:
        start = time.monotonic()
        result = loader()
        elapsed = time.monotonic() - start
        size = ""
        if hasattr(result, "__len__"):
            size = f"{len(result):>7,} records"
        elif hasattr(result, "number_of_nodes"):
            size = f"{result.number_of_nodes():>7,} nodes / {result.number_of_edges():,} edges"
        echo(f"{name:14} {elapsed:7.1f}s  {size}")
        entry = Manifest(jurisdiction).get(name)  # re-read: builders write their own instances
        if entry and entry.get("stats"):
            interesting = {k: v for k, v in entry["stats"].items()
                          if k not in ("records", "nodes")}
            if interesting:
                echo(f"{'':14}          {interesting}")
    echo(f"{'total':14} {time.monotonic() - total_start:7.1f}s")
