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
    # follow-up branches: "connectivity", "environmental", "comparables"
}

# Execution order matters: fiscal consumes economic's food_away capture.
DEFAULT_MODULES = ("economic", "fiscal")


def available() -> list[str]:
    return list(_REGISTERED)


def get_module(name: str) -> Callable:
    if name not in _REGISTERED:
        raise KeyError(f"unknown impact module '{name}' (available: {', '.join(_REGISTERED)})")
    return importlib.import_module(_REGISTERED[name]).run
