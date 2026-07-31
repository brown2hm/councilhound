"""Report synthesis: one LLM call over the structured results (brief §6.7).

The model receives the spec + every ModuleResult as JSON and writes prose
into a fixed template. It may not introduce numbers: validate.py regex-
extracts every quantity from the draft and matches it against the metric
set; on violations the call is retried once with the violations listed,
then hard-fails. The assumptions and data-sources appendices are built
deterministically in code and stored as structured JSON — the narrative
never carries them.
"""
from __future__ import annotations

import json
import logging
import os

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.impact.schemas import EvaluationBundle
from councilhound.impact.synthesis.validate import (validate_method_claims,
                                                    validate_report)

log = logging.getLogger(__name__)

REPORT_PROMPT_VERSION = "v3"  # v3: method-claim grounding, computed sensitivity,
#                                   external-estimate comparison
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

_HEADER = """\
# Impact analysis: {name}

## Executive summary
(4-8 sentences: what the project is, the headline findings WITH their
ranges, and the three assumptions the results are most sensitive to — name
them plainly.)

## Project description
(what exists, what is proposed, current status; only facts from the spec)
"""

_SECTION_ECONOMIC = """
## Economic effects
(new demand, where spending is captured — name the top clusters — the
project's own retail capture, the foot-traffic index change, jobs ledger.
State plainly that the Huff capture and foot-traffic figures are screening
estimates.)
"""

_SECTION_FISCAL = """
## Fiscal effects
(current vs projected tax, the other recurring revenue lines, the cost
range with BOTH methods named and why they differ, the net range. If
"External estimate" metrics are present, compare this analysis's net range
to those published figures plainly — say whether the ranges overlap and, if
they do not, name the methodological reasons visible in the metric methods
and notes. Never average the external figures with these.)
"""

_SECTION_BIKE_LANE = """
## Bike-lane corridor effects
(who the corridor newly serves — the decay-weighted catchment — induced
bike visits, the new-spending range at corridor businesses, and the
calibration framing: the induced-share bounds come from corridor
before/after studies, and the figures are screening estimates, not
predictions. Name the top corridor businesses if present.)
"""

_SECTION_TRAIL = """
## Trail effects
(both channels: trail-user spending — catchment, annual user-days, the
spending range and where it lands — and the property channel — assessed
value in the premium band, the uplift range with its zero floor, and the
tax increment IF computed. State that the ordinary-greenway anchors
exclude destination-trail tourism.)
"""

_SECTION_NOT_EVALUATED = """
## Not evaluated in this version
({not_evaluated} analyses are deferred; say so in one short paragraph.)
"""

_ALWAYS_DEFERRED = ("connectivity", "environmental", "comparable-places")

_MODULE_SECTIONS = (
    ("economic", _SECTION_ECONOMIC, "economic"),
    ("fiscal", _SECTION_FISCAL, "fiscal"),
    ("bike_lane", _SECTION_BIKE_LANE, "bike-lane corridor"),
    ("trail", _SECTION_TRAIL, "trail"),
)


def template_for(bundle: EvaluationBundle) -> str:
    """Assemble the template from the modules that actually produced
    metrics; everything else lands in the not-evaluated paragraph."""
    computed = {r.module for r in bundle.results if r.metrics}
    sections = [_HEADER]
    deferred: list[str] = []
    for module, section, label in _MODULE_SECTIONS:
        if module in computed:
            sections.append(section)
        else:
            deferred.append(label)
    deferred.extend(_ALWAYS_DEFERRED)
    sections.append(_SECTION_NOT_EVALUATED.replace(
        "{not_evaluated}", ", ".join(deferred)))
    return "".join(sections)

SYSTEM = """\
You write the narrative for a municipal development impact report from
structured analysis results. Hard rules:
- Use ONLY numbers that appear in the metrics/spec/assumptions JSON —
  quote them with their low-high ranges where given. Never compute, derive,
  round beyond presentation, or invent a number.
- Describe HOW a figure was computed using only that metric's `method` string
  and the labels in its `adjust` ledger. Never state or imply that an input
  is "included in", "accounted for in", "reflected in", "captured by" or
  "counted toward" a figure unless that metric's method or a term label says
  so. A quantity appearing in the spec is NOT evidence that any metric used
  it — several spec quantities deliberately enter no computation.
- Where a narrative_note says something was NOT computed, say so plainly
  rather than omitting it.
- Neutral analyst tone: both-sides on uncertain items, no advocacy, no
  hype. The reader is a council member or resident, not an investor.
- Screening-estimate language is mandatory where the notes say so.
- Report external (applicant or staff) estimates as published and attributed.
  Never average them with this analysis's figures or present them as ours.
- Keep every template section, in order, as markdown ## headings.
- No appendices — they are generated outside the narrative."""


def _needs_retry(exc: BaseException) -> bool:
    import anthropic
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (429, 500, 502, 503, 529)
    return False


@retry(retry=retry_if_exception(_needs_retry), stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=5, max=120), reraise=True)
def _call_claude(prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=DEFAULT_MODEL, max_tokens=8192, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _sensitivity_block(bundle: EvaluationBundle) -> str:
    """The template asks for "the three assumptions the results are most
    sensitive to". That used to be the model's guess — this computes it, by
    swinging each assumption from its low to its high bound through the
    metric's own power-law decomposition."""
    from councilhound.impact.provenance import (rank_assumptions_by_sensitivity,
                                                recompute_metric)

    headline = next((m for m in bundle.all_metrics()
                     if m.adjust and m.name.startswith("Net annual fiscal impact (range")),
                    None)
    if headline is None:
        headline = next((m for m in bundle.all_metrics() if m.adjust and m.headline), None)
    if headline is None:
        return ""
    assumptions = bundle.all_assumptions()
    baseline = {a.key: a.value for a in assumptions}
    touched = {key for t in headline.adjust or [] for key in (t.exps or {})}
    relevant = [a for a in assumptions if a.key in touched]
    if not relevant:
        return ""

    def recompute(key, value):
        return recompute_metric(headline, baseline, {**baseline, key: value})

    ranked = rank_assumptions_by_sensitivity(headline.value, relevant, recompute)
    lines = [f"Computed one-at-a-time sensitivity of '{headline.name}' "
             "(swing from each assumption's low bound to its high bound, all "
             "others held at their centrals). Name the top three in the "
             "executive summary and do not re-rank them yourself. The swing "
             "amounts below are provided for ordering only — do NOT state them "
             "in the narrative, as they are not published metrics:"]
    for i, (a, impact) in enumerate(ranked[:6], 1):
        lines.append(f"{i}. {a.key}: swing ${impact:,.0f} "
                     f"(central {a.value:,.4g}, range {a.low:,.4g}-{a.high:,.4g})")
    return "\n=== SENSITIVITY (computed) ===\n" + "\n".join(lines)


def _prompt(bundle: EvaluationBundle, violations: list[str] | None = None) -> str:
    parts = [
        "Write the report narrative for this project following the template.",
        "\n=== TEMPLATE ===\n" + template_for(bundle).format(name=bundle.spec.name),
        "\n=== PROJECT SPEC ===\n" + json.dumps(bundle.spec.model_dump(mode="json"), indent=1),
        "\n=== MODULE RESULTS ===\n" + json.dumps(
            [r.model_dump(mode="json") for r in bundle.results], indent=1, default=str),
    ]
    sensitivity = _sensitivity_block(bundle)
    if sensitivity:
        parts.append(sensitivity)
    if violations:
        parts.append(
            "\n=== PREVIOUS DRAFT REJECTED ===\nThese numbers were not traceable to "
            "the data; remove or replace them with exact metric values:\n- "
            + "\n- ".join(violations))
    return "\n".join(parts)


def synthesize_report(bundle: EvaluationBundle) -> tuple[str, str, str]:
    """Returns (markdown, model, prompt_version). Raises on persistent
    validation failure."""
    draft = _call_claude(_prompt(bundle))
    violations = validate_report(draft, bundle)
    if violations:
        log.warning("draft failed number validation (%d violations); regenerating",
                    len(violations))
        draft = _call_claude(_prompt(bundle, violations))
        violations = validate_report(draft, bundle)
        if violations:
            raise RuntimeError(
                "synthesized report still contains untraceable numbers after one "
                "regeneration:\n- " + "\n- ".join(violations))
    # method-claim check is advisory for now: the patterns are heuristic, and a
    # false positive should not block a report. Promote to a rejection once the
    # false-positive rate across a full re-run is known.
    for flag in validate_method_claims(draft, bundle):
        log.warning("METHOD CLAIM: %s", flag)
    return draft, DEFAULT_MODEL, REPORT_PROMPT_VERSION
