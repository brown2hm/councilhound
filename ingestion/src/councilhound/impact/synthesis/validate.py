"""Post-validation of the synthesized narrative: every number in the draft
must be traceable to the metric set (values, bounds, spec quantities, or
assumption values) within rounding. The LLM writes prose; it does not get
to introduce quantities.
"""
from __future__ import annotations

import re

# numbers with optional sign (ASCII or U+2212), $ , % and magnitude suffixes.
# The comma-grouped branch allows a trailing decimal ("70,707.78") so a
# cents value matches as ONE number instead of orphaning ".78" -> "78".
_NUMBER = re.compile(r"([-−+]?)\s*\$?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
                     # (?![-–—]\d) keeps "39 K-12 students" from parsing as 39k —
                     # covers hyphen AND en/em dashes ("7.9 K–12" from the LLM)
                     r"(million|M\b(?![-–—]\d)|k\b(?![-–—]\d)|thousand|%)?", re.IGNORECASE)

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
    # figures published by the applicant/staff, quotable in the comparison
    # section (their metrics cover these too; this is belt-and-braces)
    for est in getattr(spec, "external_estimates", None) or []:
        for value in (est.net_annual_low, est.net_annual_high, est.revenue_total,
                      est.expenditure_total, est.assessed_value,
                      est.construction_cost):
            add(value)
    # in-city shares etc. expressed as percents ("fraction", "fraction of
    # baseline sales", ...)
    for m in bundle.all_metrics():
        if m.unit.startswith("fraction"):
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
    # assumption basis/rationale strings carry the literature anchors the
    # narrative may cite ("Liu & Shi 2020, 14 corridors", "N=1,967")
    for a in bundle.all_assumptions():
        quotable.append(a.rationale)
        if isinstance(a.basis, str):
            quotable.append(a.basis)
        else:
            quotable += [a.basis.notes or "", a.basis.vintage, a.basis.source_name]
    quotable.append(bundle.spec.name)  # street-number names: "10340 Democracy Lane"
    quotable.extend(bundle.spec.parcels)  # PINs the draft may cite ("57 2 18 001 A")
    quotable.extend(bundle.spec.extraction_quotes.values())
    quotable.extend(bundle.spec.extraction_notes)
    for est in getattr(bundle.spec, "external_estimates", None) or []:
        quotable += [est.quote or "", est.source, est.fy or ""]
    for text in quotable:
        for value, _context in extract_numbers(text):
            add(value)
    return allowed


def _sig_figs(raw: str) -> int:
    """Significant digits as WRITTEN ('1.5' -> 2, '39.2' -> 3, '467,949' -> 6).
    Trailing zeros don't count — prose rounds to hundreds/thousands ('5,900'
    states 2 significant figures) — but the floor of 2 keeps a coarse
    '1,000,000' from matching anything within half a million."""
    digits = raw.replace(",", "").replace(".", "").lstrip("0")
    return max(len(digits.rstrip("0")), 2)


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
            # a hyphen directly after a digit is a range separator
            # ("234.9-253.2") and after a letter it's a compound word
            # ("early-1970s", "Phase-2") — neither is a negative sign
            prev = text[match.start() - 1] if match.start() > 0 else ""
            if not (prev.isdigit() or prev.isalpha()):
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


# Claims that an input was USED in a computation. The number validator can't
# catch these: a draft once said the proposed office square footage "is
# accounted for in the tax value estimate" while the fiscal module never read
# that field, and the figure itself was a legitimate spec quantity, so every
# number checked out.
_INCLUSION_CLAIM = re.compile(
    r"\b(?:is|are|was|were|been|being)\s+(?:\w+\s+){0,3}?"
    r"(accounted for|included|counted|captured|reflected|incorporated|"
    r"factored)\b", re.IGNORECASE)

# spec quantities a draft might claim were used, and the words that would show
# up in a metric's method string or adjust-term labels if they actually were
_CLAIMABLE_INPUTS = {
    "office": ("office",),
    "retail": ("retail", "commercial", "ground-floor", "ground floor"),
    "parking": ("parking",),
    "affordable": ("affordable",),
    "student": ("student", "school"),
    "vehicle": ("vehicle",),
    "restaurant": ("restaurant", "meals", "dining"),
}

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def validate_method_claims(markdown: str, bundle) -> list[str]:
    """Flags sentences claiming an input was used in a computation when no
    metric's method or adjust-term label mentions it.

    Advisory (the caller logs rather than rejects): the patterns are heuristic
    and a false positive should not block a report.
    """
    grounded = []
    for m in bundle.all_metrics():
        grounded.append(m.method or "")
        grounded.append(m.name)
        for t in m.adjust or []:
            grounded.append(t.label or "")
    for result in bundle.results:
        grounded.extend(result.narrative_notes)
    grounded_text = " ".join(grounded).lower()

    flags = []
    for sentence in _SENTENCE.findall(markdown):
        if not _INCLUSION_CLAIM.search(sentence):
            continue
        lowered = sentence.lower()
        for topic, words in _CLAIMABLE_INPUTS.items():
            if not any(w in lowered for w in words):
                continue
            if not any(w in grounded_text for w in words):
                flags.append(f"unsupported '{topic}' inclusion claim: "
                             f"\"{sentence.strip()[:160]}\"")
                break
    return flags


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
