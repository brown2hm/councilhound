"""Post-validation of the synthesized narrative: every number in the draft
must be traceable to the metric set (values, bounds, spec quantities, or
assumption values) within rounding. The LLM writes prose; it does not get
to introduce quantities.
"""
from __future__ import annotations

import re

# numbers with optional $ , % . and thousands separators / magnitude suffixes
_NUMBER = re.compile(r"\$?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(million|M\b|k\b|thousand|%)?",
                     re.IGNORECASE)

_MAGNITUDE = {"million": 1e6, "m": 1e6, "k": 1e3, "thousand": 1e3}

# numbers that read as prose, not quantities
_IGNORED = {1, 2, 3, 4, 5, 10, 15, 100}  # "three lenses", "10-minute walk", percent bases


def allowed_values(bundle) -> set[float]:
    """Every number the draft is allowed to state."""
    allowed: set[float] = set()

    def add(x):
        if x is None:
            return
        x = float(x)
        allowed.add(round(x, 2))
        # rounded presentation forms the narrative may reasonably use
        for digits in (0, 1, 2):
            for scale in (1, 1e-3, 1e-6):  # raw, thousands, millions
                allowed.add(round(x * scale, digits))

    for m in bundle.all_metrics():
        add(m.value), add(m.low), add(m.high)
    for a in bundle.all_assumptions():
        add(a.value), add(a.low), add(a.high)
        add(a.value * 100), add(a.low * 100), add(a.high * 100)  # fraction -> %
    spec = bundle.spec
    for value in (spec.proposed.units, spec.proposed.retail_sqft, spec.proposed.office_sqft,
                  spec.proposed.stories, spec.proposed.acres, spec.proposed.parking_spaces,
                  spec.proposed.affordable_units, spec.existing.sqft, spec.existing.units,
                  spec.existing.assessed_value):
        add(value)
    # in-city shares etc. expressed as percents
    for m in bundle.all_metrics():
        if m.unit == "fraction":
            add(m.value * 100)
            add(m.low * 100 if m.low is not None else None)
            add(m.high * 100 if m.high is not None else None)
    return allowed


def extract_numbers(markdown: str) -> list[tuple[float, str]]:
    """(value, verbatim context) for every quantity-looking number outside
    code fences."""
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    found = []
    for match in _NUMBER.finditer(text):
        raw, suffix = match.group(1), (match.group(2) or "").lower()
        value = float(raw.replace(",", ""))
        if suffix in _MAGNITUDE:
            value *= _MAGNITUDE[suffix]
        context = text[max(0, match.start() - 40):match.end() + 20].replace("\n", " ")
        found.append((value, context.strip()))
    return found


def _matches(value: float, allowed: set[float]) -> bool:
    for candidate in (value, round(value), round(value, 1), round(value, 2)):
        if candidate in allowed:
            return True
    # tolerate rounding to 2-3 significant figures of any allowed value
    for a in allowed:
        if a != 0 and abs(value - a) / abs(a) < 0.005:
            return True
        if a == 0 and abs(value) < 1e-9:
            return True
    return False


def validate_report(markdown: str, bundle) -> list[str]:
    """Returns violations: numbers in the draft not traceable to the data."""
    allowed = allowed_values(bundle)
    violations = []
    for value, context in extract_numbers(markdown):
        if value in _IGNORED and value == int(value):
            continue
        if not _matches(value, allowed):
            violations.append(f"{value:g} (in: \"...{context}...\")")
    return violations
