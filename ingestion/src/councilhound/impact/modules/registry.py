"""Module registry — the seam that lets follow-up branches add connectivity,
environmental, and comparables without touching the orchestrator: drop a
module file exposing `run(spec, ctx, prior=None) -> ModuleResult` and add its
name here. Imports are lazy so listing modules never pulls the geo stack."""
from __future__ import annotations

import importlib
from typing import Callable

# name -> dotted module path; each must expose run(spec, ctx, prior) -> ModuleResult
_REGISTERED: dict[str, str] = {
    "economic": "councilhound.impact.modules.economic",
    "fiscal": "councilhound.impact.modules.fiscal",
    "bike_lane": "councilhound.impact.modules.bike_lane",
    "trail": "councilhound.impact.modules.trail",
    # follow-up branches: "connectivity", "environmental", "comparables"
}

# Execution order matters: fiscal consumes economic's food_away capture.
DEFAULT_MODULES = ("economic", "fiscal")

# project_type -> modules to run (evaluate consults this unless --modules is
# passed). Modules still self-gate on spec contents as belt-and-braces, so a
# mistyped project_type degrades to a "Not computed" note, never a crash.
MODULES_BY_TYPE: dict[str, tuple[str, ...]] = {
    "residential": DEFAULT_MODULES,
    "mixed_use": DEFAULT_MODULES,
    "commercial": DEFAULT_MODULES,
    "street_multimodal": ("bike_lane", "trail"),  # trail self-gates on facilities
    "park": ("trail",),
    "other": DEFAULT_MODULES,
}


def modules_for(project_type: str) -> tuple[str, ...]:
    return MODULES_BY_TYPE.get(project_type, DEFAULT_MODULES)


def available() -> list[str]:
    return list(_REGISTERED)


def get_module(name: str) -> Callable:
    if name not in _REGISTERED:
        raise KeyError(f"unknown impact module '{name}' (available: {', '.join(_REGISTERED)})")
    return importlib.import_module(_REGISTERED[name]).run
