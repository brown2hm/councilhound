"""Disk cache for the impact subsystem.

Layout (all under the repo data root, gitignored):
    RAW_DATA_DIR/impact/<source>/<vintage>/...     immutable raw downloads
    DATA_DIR/impact/context/<jurisdiction>/        built context layers
        manifest.json                              {layer: provenance + stats}
    DATA_DIR/impact/specs/<slug>.yaml              HITL spec artifacts
    DATA_DIR/impact/runs/<slug>/<timestamp>/       full-res audit dumps

Layer files carry their vintage in the filename; the manifest records the
Provenance dump + build stats per layer, which is what "warm cache" checks.
Writes are atomic (.part -> rename), mirroring councilhound.http.download.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from councilhound.config import DATA_DIR, RAW_DATA_DIR


def raw_path(source: str, vintage: str, filename: str = "") -> Path:
    p = Path(RAW_DATA_DIR) / "impact" / source / vintage
    p.mkdir(parents=True, exist_ok=True)
    return p / filename if filename else p


def context_dir(jurisdiction: str) -> Path:
    p = Path(DATA_DIR) / "impact" / "context" / jurisdiction
    p.mkdir(parents=True, exist_ok=True)
    return p


def specs_dir() -> Path:
    p = Path(DATA_DIR) / "impact" / "specs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_dir(slug: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p = Path(DATA_DIR) / "impact" / "runs" / slug / ts
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write_bytes(path: Path, data: bytes) -> None:
    part = path.with_suffix(path.suffix + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, default=str))


def cached(path: Path, build: Callable[[Path], None]) -> Path:
    """Build-if-missing: `build(tmp_path)` must write the artifact to the
    given temp path; it is atomically renamed into place on success."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    build(part)
    if not part.exists():
        raise RuntimeError(f"cache builder for {path.name} produced no file")
    os.replace(part, path)
    return path


class Manifest:
    """Per-context-dir record of what each layer was built from."""

    def __init__(self, jurisdiction: str):
        self.path = context_dir(jurisdiction) / "manifest.json"
        self.data: dict[str, dict] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    def record(self, layer: str, provenance: dict | list[dict], stats: dict | None = None) -> None:
        self.data[layer] = {
            "provenance": provenance,
            "stats": stats or {},
            "built_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(self.path, self.data)

    def get(self, layer: str) -> dict | None:
        return self.data.get(layer)
