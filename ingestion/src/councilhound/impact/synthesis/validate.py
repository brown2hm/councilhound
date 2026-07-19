"""Post-validation of the synthesized narrative: every number in the draft
must be traceable to the metric set (values, bounds, spec quantities, or
assumption values) within rounding. The LLM writes prose; it does not get
to introduce quantities.
"""
from __future__ import annotations

import re

# numbers with optional sign (ASCII or U+2212), $ , % and magnitude suffixes
_NUMBER = re.compile(r"([-−+]?)\s*\$?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
                     # (?!-\d) keeps "39 K-12 students" from parsing as 39k
                     r"(million|M\b(?!-\d)|k\b(?!-\d)|thousand|%)?", re.IGNORECASE)

_MAGNITUDE = {"million": 1e6, "m": 1e6, "k": 1e3, "thousand": 1e3}

# numbers that read as prose, not quantities
_IGNORED = {1, 2, 3, 4, 5, 10, 15, 100}  # "three lenses", "10-minute walk", percent bases


def _is_year(value: float) -> bool:
    return value == int(value) and 1900 <= value <= 2100


def allowed_values(bundle) -> set[float]:
    """Every number the draft is allowed to state."""
    allowed: set[float] = set()

    def add(x):
        if x is None:
            return
        x = float(x)
        # prose may carry the sign as a word ("a deficit of $5,985,151"),
        # so the unsigned form of any signed value is also quotable
        for v in (x, -x) if x < 0 else (x,):
            allowed.add(round(v, 2))
            # rounded presentation forms the narrative may reasonably use
            for digits in (0, 1, 2):
                for scale in (1, 1e-3, 1e-6):  # raw, thousands, millions
                    allowed.add(round(v * scale, digits))

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
    # numbers already present in deterministic module text are quotable:
    # narrative_notes (e.g. the computed students range), provenance notes
    # (e.g. comp per-unit values), extraction quotes, metric names (e.g.
    # "K-12", "10 nearest segments" — the hyphen otherwise scans as a minus
    # sign), and method strings
    quotable: list[str] = []
    for result in bundle.results:
        quotable.extend(result.narrative_notes)
        for m in result.metrics:
            quotable.append(m.name)
            quotable.append(m.method)
            for p in m.provenance:
                quotable += [p.notes or "", p.vintage, p.source_name]
    for p in bundle.all_sources():
        quotable += [p.notes or "", p.vintage, p.source_name]  # e.g. "Va. Code § 58.1-605"
    quotable.extend(bundle.spec.extraction_quotes.values())
    quotable.extend(bundle.spec.extraction_notes)
    for text in quotable:
        for value, _context in extract_numbers(text):
            add(value)
    return allowed


def _sig_figs(raw: str) -> int:
    """Significant digits as WRITTEN ('1.5' -> 2, '39.2' -> 3, '467,949' -> 6).
    Trailing zeros count (conservative), leading zeros don't."""
    digits = raw.replace(",", "").replace(".", "").lstrip("0")
    return max(len(digits), 1)


def extract_numbers(markdown: str) -> list[tuple[float, str]]:
    """(value, verbatim context) for every quantity-looking number outside
    code fences."""
    return [(v, c) for v, c, _ in extract_numbers_with_precision(markdown)]


def extract_numbers_with_precision(markdown: str) -> list[tuple[float, str, int]]:
    """(value, verbatim context, significant digits as written)."""
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    found = []
    for match in _NUMBER.finditer(text):
        sign, raw, suffix = match.group(1), match.group(2), (match.group(3) or "").lower()
        value = float(raw.replace(",", ""))
        if suffix in _MAGNITUDE:
            value *= _MAGNITUDE[suffix]
        if sign == "−":  # true minus
            value = -value
        elif sign == "-":
            # a hyphen directly after a digit is a range separator ("234.9-253.2"),
            # not a negative sign
            prev = text[match.start() - 1] if match.start() > 0 else ""
            if not prev.isdigit():
                value = -value
        context = text[max(0, match.start() - 40):match.end() + 20].replace("\n", " ")
        found.append((value, context.strip(), _sig_figs(raw)))
    return found


def _matches(value: float, allowed: set[float], sig: int | None = None) -> bool:
    for candidate in (value, round(value), round(value, 1), round(value, 2)):
        if candidate in allowed:
            return True
    for a in allowed:
        if a != 0 and abs(value - a) / abs(a) < 0.005:
            return True
        if a == 0 and abs(value) < 1e-9:
            return True
    # a number is held to its own written precision: "$1.5 million" is a
    # legitimate statement of $1,469,000 (2 significant figures), while
    # "$1,500,000" written in full would not be. Tolerance is half a unit in
    # the last written digit (plus float slack for exact midpoints).
    if sig:
        import math
        for a in allowed:
            if a == 0:
                continue
            quantum = 10.0 ** (math.floor(math.log10(abs(a))) - sig + 1)
            if abs(value - a) <= 0.51 * quantum:
                return True
    return False


def validate_report(markdown: str, bundle) -> list[str]:
    """Returns violations: numbers in the draft not traceable to the data."""
    allowed = allowed_values(bundle)
    violations = []
    for value, context, sig in extract_numbers_with_precision(markdown):
        if value in _IGNORED and value == int(value):
            continue
        if _is_year(value):
            continue
        if not _matches(value, allowed, sig):
            violations.append(f"{value:g} (in: \"...{context}...\")")
    return violations
