"""Shared assumption helpers: tenure-aware defaults and human overrides.

Two rules the modules share:

- One key per concept. Tenure changes an assumption's *default*, never its
  key: EvaluationBundle.all_assumptions dedupes by key and the frontend
  labels are keyed, so per-tenure keys would be dead knobs in the
  assumptions lab and an invitation to drift.
- A human at the confirm gate outranks a screening default. Overrides in
  spec.assumption_overrides are applied last and announce themselves in the
  narrative notes, so a reader always sees that a value was replaced.
"""
from __future__ import annotations

from councilhound.impact.schemas import Assumption

# tenure values that should use the for-sale variant of a default
FOR_SALE = ("for_sale",)


def is_for_sale(spec) -> bool:
    """True when the documents established for-sale tenure. 'mixed', 'unknown'
    and None all fall to the rental defaults — the conservative direction,
    since rental per-unit values and household sizes are the lower ones."""
    tenure = getattr(spec.proposed, "tenure", None)
    return tenure in FOR_SALE


def apply_overrides(assumptions: dict[str, Assumption], spec,
                    notes: list[str]) -> dict[str, Assumption]:
    """Replace value/low/high for any assumption the spec overrides.

    Unknown keys are reported rather than ignored: a typo in the YAML would
    otherwise look exactly like a working override.
    """
    overrides = getattr(spec, "assumption_overrides", None) or {}
    for key, override in overrides.items():
        current = assumptions.get(key)
        if current is None:
            continue  # another module may own this key; it reports its own
        assumptions[key] = current.model_copy(update={
            "value": override.value,
            "low": override.low,
            "high": override.high,
            "basis": "human override at confirm (spec.assumption_overrides)",
            "rationale": (override.rationale
                          or f"replaces the pipeline default of {current.value:,.4g} "
                             f"[{current.low:,.4g}, {current.high:,.4g}]"),
        })
        notes.append(
            f"assumption '{key}' overridden by hand: {override.value:,.4g} "
            f"[{override.low:,.4g}, {override.high:,.4g}] "
            f"(default was {current.value:,.4g} [{current.low:,.4g}, {current.high:,.4g}])"
            + (f" — {override.rationale}" if override.rationale else ""))
    return assumptions


def unknown_override_keys(spec, known: set[str]) -> list[str]:
    """Override keys no module declared — surfaced once, at the orchestrator."""
    overrides = getattr(spec, "assumption_overrides", None) or {}
    return sorted(set(overrides) - known)
