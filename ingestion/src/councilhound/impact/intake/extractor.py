"""LLM extraction of a ProjectSpec from project documents.

The one place the LLM touches project quantities — under a firewall enforced
in code, not prompt: every numeric field must arrive with a verbatim
source quote (≤ 15 words) that actually appears in the supplied text. A
missing or unverifiable quote demotes the field to null/low-confidence.
The model can propose; only the documents can assert.

Call pattern mirrors extraction/entity_profile.py (forced tool-use, tenacity
retry on transient anthropic errors, env-configurable model).
"""
from __future__ import annotations

import logging
import os
import re

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.impact.intake.documents import ProjectDocument

log = logging.getLogger(__name__)

EXTRACT_PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_QUOTE_WORDS = 15
MAX_DOC_CHARS = 60_000  # per document, keeps the prompt bounded

NUMERIC_FIELDS = (
    "existing.sqft", "existing.units", "existing.assessed_value",
    "proposed.units", "proposed.retail_sqft", "proposed.office_sqft",
    "proposed.stories", "proposed.acres", "proposed.parking_spaces",
    "proposed.affordable_units",
)

_FIELD_PROPS = {
    "value": {"type": ["number", "null"]},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "source_quote": {
        "type": ["string", "null"],
        "description": "VERBATIM quote (max 15 words) from the documents that states this value. null if the documents do not state it.",
    },
}


def _numeric_field_schema(desc: str) -> dict:
    return {
        "type": "object",
        "properties": {**_FIELD_PROPS, "value": {**_FIELD_PROPS["value"], "description": desc}},
        "required": ["value", "confidence", "source_quote"],
    }


EXTRACT_TOOL = {
    "name": "record_project_spec",
    "description": "Record the extracted development-project specification.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_type": {
                "type": "string",
                "enum": ["residential", "mixed_use", "commercial",
                         "street_multimodal", "park", "other"],
            },
            "existing_use": {"type": ["string", "null"],
                             "description": "Current use of the site, e.g. 'two vacant commercial buildings'."},
            "existing_sqft": _numeric_field_schema("Existing building square footage being removed/replaced."),
            "existing_units": _numeric_field_schema("Existing dwelling units on site."),
            "proposed_units": _numeric_field_schema("Proposed dwelling units (use the maximum if a range)."),
            "proposed_retail_sqft": _numeric_field_schema("Proposed ground-floor/commercial retail sq ft."),
            "proposed_office_sqft": _numeric_field_schema("Proposed office sq ft."),
            "proposed_stories": _numeric_field_schema("Proposed building stories/height in floors."),
            "proposed_acres": _numeric_field_schema("Site area in acres."),
            "proposed_parking_spaces": _numeric_field_schema("Proposed parking spaces."),
            "proposed_affordable_units": _numeric_field_schema("Committed affordable dwelling units."),
            "parcel_pins": {
                "type": "array", "items": {"type": "string"},
                "description": "Parcel PINs / tax map numbers stated in the documents, verbatim.",
            },
            "conflicts": {
                "type": "array", "items": {"type": "string"},
                "description": "Places where documents disagree (state which document says what).",
            },
        },
        "required": ["project_type", *[f.replace('.', '_') for f in NUMERIC_FIELDS],
                     "parcel_pins", "conflicts"],
    },
}

EXTRACT_SYSTEM = """\
You extract development-project facts for a municipal analysis pipeline. \
Rules, in priority order:
1. NEVER supply a number the documents do not state. If a quantity is absent, \
set value=null, confidence=low, source_quote=null. A plausible guess is a \
defect, not a help.
2. Every non-null numeric value MUST carry source_quote: a verbatim span of \
at most 15 words copied exactly from the documents that states the value.
3. When documents conflict, prefer the most recent staff report over \
marketing/summary text, and record the conflict in `conflicts`.
4. confidence=high only when the value is stated plainly; medium when \
inferred from clearly equivalent phrasing; low otherwise."""


def _needs_retry(exc: BaseException) -> bool:
    import anthropic
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (429, 500, 502, 503, 529)
    return False


@retry(retry=retry_if_exception(_needs_retry), stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=5, max=120), reraise=True)
def _call_claude(prompt: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=EXTRACT_SYSTEM,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "record_project_spec"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("no tool_use block in response")


def _normalize(text: str) -> str:
    """Whitespace/punctuation-tolerant form for verbatim-quote checking."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def enforce_firewall(raw: dict, corpus: str) -> tuple[dict, list[str]]:
    """Demote any numeric field whose quote is missing, too long, or not
    verbatim in the corpus. Returns (cleaned fields dict, demotion notes)."""
    notes: list[str] = []
    corpus_norm = _normalize(corpus)
    cleaned: dict[str, dict] = {}
    for field in NUMERIC_FIELDS:
        key = field.replace(".", "_")
        entry = raw.get(key)
        if not isinstance(entry, dict):  # malformed output -> treat as absent
            if entry is not None:
                notes.append(f"{field}: malformed extraction entry ({entry!r}) — nulled")
            entry = {}
        value = entry.get("value")
        quote = entry.get("source_quote")
        confidence = entry.get("confidence", "low")
        if isinstance(value, str):
            try:
                value = float(value.replace(",", ""))
            except ValueError:
                notes.append(f"{field}: non-numeric value {value!r} — nulled")
                value = None
        if value is not None:
            reason = None
            if not quote:
                reason = "no source quote"
            elif len(quote.split()) > MAX_QUOTE_WORDS:
                reason = f"quote longer than {MAX_QUOTE_WORDS} words"
            elif _normalize(quote) not in corpus_norm:
                reason = "quote not found verbatim in documents"
            if reason:
                notes.append(f"{field}: demoted to null ({reason}; model claimed {value!r})")
                value, quote, confidence = None, None, "low"
        cleaned[field] = {"value": value, "confidence": confidence, "source_quote": quote}
    return cleaned, notes


def _build_prompt(docs: list[ProjectDocument]) -> str:
    parts = ["Extract the project specification from these documents.",
             "Documents are ordered most-authoritative-last is NOT guaranteed — "
             "judge by document type and date; staff reports beat summaries.\n"]
    for i, doc in enumerate(docs, 1):
        parts.append(f"=== DOCUMENT {i}: {doc.label} ({doc.url}) ===\n"
                     f"{doc.text[:MAX_DOC_CHARS]}\n")
    return "\n".join(parts)


def extract_spec_fields(docs: list[ProjectDocument]) -> dict:
    """Run the extraction call + firewall. Returns:
    {project_type, existing_use, fields: {dotted -> {value, confidence,
    source_quote}}, parcel_pins, conflicts, notes}."""
    corpus = "\n".join(doc.text for doc in docs)
    raw = _call_claude(_build_prompt(docs))
    fields, notes = enforce_firewall(raw, corpus)
    pins = [str(p).strip() for p in raw.get("parcel_pins") or [] if str(p).strip()]
    # PINs must be verbatim in the corpus too — they feed parcel resolution
    corpus_norm = _normalize(corpus)
    verified_pins = [p for p in pins if _normalize(p) in corpus_norm]
    for pin in set(pins) - set(verified_pins):
        notes.append(f"parcel PIN {pin!r} not found in documents — dropped")
    return {
        "project_type": raw.get("project_type", "other"),
        "existing_use": raw.get("existing_use"),
        "fields": fields,
        "parcel_pins": verified_pins,
        "conflicts": [str(c) for c in raw.get("conflicts") or []],
        "notes": notes,
    }
