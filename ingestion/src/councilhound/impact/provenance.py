"""Provenance/assumption helpers + interval arithmetic for bound propagation.

Every deterministic formula in the modules runs on `Interval`s so an
Assumption's low/high bounds flow through to the final MetricValue without
per-formula hand derivation. Intervals here assume the non-negative,
monotonic quantities these models trade in (people, dollars, sqft), which
makes endpoint arithmetic exact for + and *; division uses the conservative
cross-endpoint form.
"""
from __future__ import annotations

from dataclasses import dataclass

from councilhound.impact.schemas import AdjustTerm, Assumption, MetricValue, Provenance


def prov(source_name: str, url: str, vintage: str, notes: str | None = None) -> Provenance:
    return Provenance(source_name=source_name, url=url, vintage=vintage, notes=notes)


# --- adjustment terms: exact client-side recompute model ---------------------
# A metric's adjust list decomposes its central value into power-law terms of
# assumption centrals (see AdjustTerm). The algebra below keeps the invariant
# sum(term values) == metric value, which evaluate.py asserts on every run.

def term(value: float, _label: str | None = None, **exps: float) -> AdjustTerm:
    """One adjustment term. `_label` names what the piece is (it leads with an
    underscore so it can never collide with an assumption key passed as a
    keyword)."""
    return AdjustTerm(value=float(value), exps=exps, label=_label)


def terms_scale(terms: list[AdjustTerm], k: float) -> list[AdjustTerm]:
    return [AdjustTerm(value=t.value * k, exps=dict(t.exps), label=t.label) for t in terms]


def terms_pow_extend(terms: list[AdjustTerm], **extra: float) -> list[AdjustTerm]:
    """Multiply every term by extra assumption factors (adds exponents)."""
    out = []
    for t in terms:
        exps = dict(t.exps)
        for key, e in extra.items():
            exps[key] = exps.get(key, 0.0) + e
        out.append(AdjustTerm(value=t.value, exps=exps, label=t.label))
    return out


def terms_relabel(terms: list[AdjustTerm], label: str) -> list[AdjustTerm]:
    """Stamp one name onto a borrowed decomposition. Composite metrics reuse
    another metric's terms (fiscal nets pull in revenue and cost lines); the
    borrowed terms carry the donor's internal labels, which are wrong in the
    consumer's ledger unless renamed."""
    return [AdjustTerm(value=t.value, exps=dict(t.exps), label=label) for t in terms]


def terms_value(terms: list[AdjustTerm]) -> float:
    return sum(t.value for t in terms)


@dataclass(frozen=True)
class Interval:
    value: float
    low: float
    high: float

    def __post_init__(self):
        if not (self.low <= self.value <= self.high):
            raise ValueError(f"interval out of order: {self.low} <= {self.value} <= {self.high}")

    @classmethod
    def point(cls, x: float) -> "Interval":
        return cls(x, x, x)

    @classmethod
    def from_assumption(cls, a: Assumption) -> "Interval":
        return cls(a.value, a.low, a.high)

    def _coerce(self, other) -> "Interval":
        return other if isinstance(other, Interval) else Interval.point(float(other))

    def __add__(self, other) -> "Interval":
        o = self._coerce(other)
        return Interval(self.value + o.value, self.low + o.low, self.high + o.high)

    __radd__ = __add__

    def __sub__(self, other) -> "Interval":
        o = self._coerce(other)
        return Interval(self.value - o.value, self.low - o.high, self.high - o.low)

    def __rsub__(self, other) -> "Interval":
        return self._coerce(other) - self

    def __mul__(self, other) -> "Interval":
        o = self._coerce(other)
        corners = (self.low * o.low, self.low * o.high, self.high * o.low, self.high * o.high)
        return Interval(self.value * o.value, min(corners), max(corners))

    __rmul__ = __mul__

    def __truediv__(self, other) -> "Interval":
        o = self._coerce(other)
        if o.low <= 0 <= o.high:
            raise ZeroDivisionError("interval division by range containing zero")
        corners = (self.low / o.low, self.low / o.high, self.high / o.low, self.high / o.high)
        return Interval(self.value / o.value, min(corners), max(corners))

    def scale(self, k: float) -> "Interval":
        return self * Interval.point(k)

    def __pow__(self, exponent: float) -> "Interval":
        """Positive-base power (used for Engel income-elasticity scaling);
        monotonic for base > 0 and exponent >= 0, so endpoints map to
        endpoints."""
        if self.low <= 0:
            raise ValueError("interval power requires a strictly positive base")
        if exponent < 0:
            raise ValueError("interval power supports non-negative exponents only")
        return Interval(self.value ** exponent, self.low ** exponent,
                        self.high ** exponent)


def metric(
    name: str,
    interval: Interval,
    unit: str,
    provenance: list[Provenance],
    assumptions: list[Assumption] | None = None,
    method: str = "",
    headline: bool = False,
    adjust: list[AdjustTerm] | None = None,
) -> MetricValue:
    """Build a MetricValue from a propagated interval, recording which
    assumptions touched it (by key)."""
    return MetricValue(
        name=name,
        value=interval.value,
        unit=unit,
        low=interval.low,
        high=interval.high,
        provenance=provenance,
        assumptions=[a.key for a in (assumptions or [])],
        method=method,
        headline=headline,
        adjust=adjust,
    )


def recompute_metric(m: MetricValue, baseline: dict[str, float],
                     adjusted: dict[str, float]) -> float:
    """Evaluate a metric's power-law decomposition at shifted assumption
    centrals: value' = sum_t t.value * prod_k (adjusted[k]/baseline[k])^exps[k].

    The Python twin of recompute() in frontend/lib/assumptions.ts — same
    formula, so a sensitivity ranking computed here matches what the reader
    sees when they move a slider in the assumptions lab.
    """
    total = 0.0
    for t in m.adjust or []:
        factor = 1.0
        for key, exponent in (t.exps or {}).items():
            base = baseline.get(key)
            now = adjusted.get(key, base)
            if base and now is not None and now != base:
                factor *= (now / base) ** exponent
        total += t.value * factor
    return total


def rank_assumptions_by_sensitivity(
    headline_value: float, assumptions: list[Assumption], recompute
) -> list[tuple[Assumption, float]]:
    """One-at-a-time sensitivity: |headline(high) - headline(low)| per
    assumption, where `recompute(key, value) -> float` re-evaluates the
    headline metric with that single assumption pinned to `value`. Returns
    (assumption, impact) sorted by impact desc — the brief requires the top
    three in the executive summary."""
    ranked = []
    for a in assumptions:
        impact = abs(recompute(a.key, a.high) - recompute(a.key, a.low))
        ranked.append((a, impact))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked
