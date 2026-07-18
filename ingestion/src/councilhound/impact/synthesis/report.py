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
from councilhound.impact.synthesis.validate import validate_report

log = logging.getLogger(__name__)

REPORT_PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

TEMPLATE_SECTIONS = """\
# Impact analysis: {name}

## Executive summary
(4-8 sentences: what the project is, the headline economic and fiscal
findings WITH their ranges, and the three assumptions the results are most
sensitive to — name them plainly.)

## Project description
(what exists, what is proposed, current status; only facts from the spec)

## Economic effects
(new demand, where spending is captured — name the top clusters — the
project's own retail capture, the foot-traffic index change, jobs ledger.
State plainly that the Huff capture and foot-traffic figures are screening
estimates.)

## Fiscal effects
(current vs projected tax, the other recurring revenue lines, the cost
range with BOTH methods named and why they differ, the net range.)

## Not evaluated in this version
(connectivity, environmental, and comparable-places analyses are deferred;
say so in one short paragraph.)
"""

SYSTEM = """\
You write the narrative for a municipal development impact report from
structured analysis results. Hard rules:
- Use ONLY numbers that appear in the metrics/spec/assumptions JSON —
  quote them with their low-high ranges where given. Never compute, derive,
  round beyond presentation, or invent a number.
- Neutral analyst tone: both-sides on uncertain items, no advocacy, no
  hype. The reader is a council member or resident, not an investor.
- Screening-estimate language is mandatory where the notes say so.
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


def _prompt(bundle: EvaluationBundle, violations: list[str] | None = None) -> str:
    from councilhound.impact.provenance import rank_assumptions_by_sensitivity  # noqa: F401
    parts = [
        "Write the report narrative for this project following the template.",
        "\n=== TEMPLATE ===\n" + TEMPLATE_SECTIONS.format(name=bundle.spec.name),
        "\n=== PROJECT SPEC ===\n" + json.dumps(bundle.spec.model_dump(mode="json"), indent=1),
        "\n=== MODULE RESULTS ===\n" + json.dumps(
            [r.model_dump(mode="json") for r in bundle.results], indent=1, default=str),
    ]
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
    return draft, DEFAULT_MODEL, REPORT_PROMPT_VERSION
