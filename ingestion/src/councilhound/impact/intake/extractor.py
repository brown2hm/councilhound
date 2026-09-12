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

EXTRACT_PROMPT_VERSION = "v3"  # v3: residential tenure (for-sale vs rental)
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_QUOTE_WORDS = 15
MAX_DOC_CHARS = 60_000  # per document, keeps the prompt bounded
MAX_TOTAL_CHARS = 400_000  # whole-corpus budget across documents

# Residential tenure drives assessed value per unit (for-sale condos assess
# several times an apartment building's per-unit value), household size,
# occupancy, and school yield. An enum can't be checked verbatim the way a
# number can, so each value carries evidence tokens that must appear in the
# model's supporting quote.
TENURE_EVIDENCE = {
    "for_sale": ("for sale", "for-sale", "condominium", "condominiums", "condo",
                 "condos", "owner occupied", "owner-occupied", "homeownership",
                 "fee simple", "townhomes for sale", "sold"),
    "rental": ("rental", "rentals", "apartment", "apartments", "lease", "leased",
               "renter", "multifamily rental", "for rent"),
}

NUMERIC_FIELDS = (
    "existing.sqft", "existing.units", "existing.assessed_value",
    "proposed.units", "proposed.retail_sqft", "proposed.office_sqft",
    "proposed.stories", "proposed.acres", "proposed.parking_spaces",
    "proposed.affordable_units", "corridor.length_ft",
)

# corridor street names: strings under the same verbatim rule as numbers —
# they feed geometric resolution, so an invented name is a wrong corridor
STRING_FIELDS = ("corridor.street_name", "corridor.from_street", "corridor.to_street")

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
            "corridor_length_ft": _numeric_field_schema(
                "Corridor/segment length in FEET for street or trail projects "
                "(convert miles x 5280 only if the documents state miles; then "
                "quote the miles statement)."),
            "corridor_street_name": {
                "type": ["string", "null"],
                "description": "For street/trail corridor projects: the street or "
                               "trail name, copied VERBATIM from the documents.",
            },
            "corridor_from_street": {
                "type": ["string", "null"],
                "description": "Cross street bounding one end of the corridor, "
                               "verbatim from the documents (null if not stated).",
            },
            "corridor_to_street": {
                "type": ["string", "null"],
                "description": "Cross street bounding the other end, verbatim "
                               "(null if not stated).",
            },
            "corridor_facilities": {
                "type": "array", "items": {"type": "string"},
                "description": "Facilities the project builds along the corridor, "
                               "verbatim phrases, e.g. 'protected bike lane', "
                               "'shared use path', 'multi-use trail'.",
            },
            "proposed_tenure": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": ["string", "null"],
                        "enum": ["for_sale", "rental", "mixed", None],
                        "description": "Residential tenure: for_sale (condominiums / "
                                       "for-sale townhomes), rental (apartments), mixed, "
                                       "or null if the documents do not say.",
                    },
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "source_quote": {
                        "type": ["string", "null"],
                        "description": "VERBATIM quote (max 15 words) stating the tenure, "
                                       "e.g. 'seventy-nine (79) for-sale condominium "
                                       "dwelling units'. null if not stated.",
                    },
                },
                "required": ["value", "confidence", "source_quote"],
            },
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
                     *[f.replace('.', '_') for f in STRING_FIELDS],
                     "proposed_tenure", "corridor_facilities", "parcel_pins",
                     "conflicts"],
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
inferred from clearly equivalent phrasing; low otherwise.
5. proposed_tenure follows the same rule: quote the words that establish it \
("for-sale condominium units", "apartments for lease"). Do not infer tenure \
from building type, price, or unit count — if the documents never say, use \
null."""


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
    """Whitespace/punctuation-tolerant form for verbatim-quote checking.

    Note for PINs specifically: this agrees with
    councilhound.impact.pins.norm_pin up to case, and it must stay that way.
    The two normalizers disagreeing (this one dropping separators, the parcel
    resolver's collapsing whitespace only) is what let hyphenated PINs pass
    the quote firewall here and then match nothing in the parcel layer.
    """
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


def enforce_string_firewall(raw: dict, corpus: str) -> tuple[dict, list[str]]:
    """Same contract as the numeric firewall, for the corridor street-name
    strings: a non-null value must itself appear verbatim (normalized) in the
    corpus — the string IS its own quote. Returns ({dotted: str|None}, notes)."""
    notes: list[str] = []
    corpus_norm = _normalize(corpus)
    cleaned: dict[str, str | None] = {}
    for field in STRING_FIELDS:
        value = raw.get(field.replace(".", "_"))
        if value is not None and not isinstance(value, str):
            notes.append(f"{field}: non-string value ({value!r}) — nulled")
            value = None
        if value is not None:
            value = value.strip() or None
        if value is not None and _normalize(value) not in corpus_norm:
            notes.append(f"{field}: {value!r} not found verbatim in documents — nulled")
            value = None
        cleaned[field] = value
    return cleaned, notes


def enforce_enum_firewall(entry, corpus: str, field: str, evidence: dict[str, tuple[str, ...]],
                          ) -> tuple[dict, list[str]]:
    """Verbatim rule for an enum: the VALUE is a code word that never appears
    in the documents, so the quote carries the burden. A non-null value needs a
    quote that (a) is verbatim in the corpus and (b) contains at least one
    evidence token for the claimed value. Failure nulls the field, which lands
    the consumer on its conservative default rather than on a guess.

    `mixed` requires evidence for both classes somewhere in the corpus.
    """
    notes: list[str] = []
    if not isinstance(entry, dict):
        if entry is not None:
            notes.append(f"{field}: malformed extraction entry ({entry!r}) — nulled")
        entry = {}
    value = entry.get("value")
    quote = entry.get("source_quote")
    confidence = entry.get("confidence", "low")
    if value is not None:
        corpus_norm = _normalize(corpus)
        quote_norm = _normalize(quote or "")
        allowed = set(evidence) | {"mixed"}
        reason = None
        if value not in allowed:
            reason = f"value not one of {sorted(allowed)}"
        elif not quote:
            reason = "no source quote"
        elif len(quote.split()) > MAX_QUOTE_WORDS:
            reason = f"quote longer than {MAX_QUOTE_WORDS} words"
        elif quote_norm not in corpus_norm:
            reason = "quote not found verbatim in documents"
        else:
            if value == "mixed":
                present = [cls for cls, tokens in evidence.items()
                           if any(_normalize(t) in corpus_norm for t in tokens)]
                if len(present) < 2:
                    reason = ("claimed 'mixed' but the documents show evidence for "
                              f"only {present or 'no'} tenure")
            elif not any(_normalize(t) in quote_norm for t in evidence[value]):
                reason = f"quote states no evidence for {value!r}"
        if reason:
            notes.append(f"{field}: demoted to null ({reason}; model claimed {value!r})")
            value, quote, confidence = None, None, "low"
    return {"value": value, "confidence": confidence, "source_quote": quote}, notes


def _build_prompt(docs: list[ProjectDocument]) -> str:
    parts = ["Extract the project specification from these documents.",
             "Documents are ordered most-authoritative-last is NOT guaranteed — "
             "judge by document type and date; staff reports beat summaries.\n"]
    # per-document cap plus a whole-corpus budget: the largest projects carry
    # 70+ documents, and an unbounded corpus both costs and buries the
    # authoritative staff report under years of superseded submissions
    used = 0
    for i, doc in enumerate(docs, 1):
        text = doc.text[:MAX_DOC_CHARS]
        if used + len(text) > MAX_TOTAL_CHARS:
            remaining = MAX_TOTAL_CHARS - used
            if remaining < 2_000:
                parts.append(f"=== {len(docs) - i + 1} FURTHER DOCUMENT(S) OMITTED "
                             "(corpus size budget) ===")
                log.warning("corpus budget reached; omitted %d of %d documents",
                            len(docs) - i + 1, len(docs))
                break
            text = text[:remaining] + "\n[... truncated: corpus size budget ...]"
        used += len(text)
        parts.append(f"=== DOCUMENT {i}: {doc.label} ({doc.url}) ===\n{text}\n")
    return "\n".join(parts)


EXTERNAL_DOC_PATTERN = re.compile(
    r"fiscal impact|fiscal analysis|staff report|staff memo|net fiscal|"
    r"public hearing", re.I)

EXTERNAL_WINDOW_CHARS = 5_000  # verbatim context kept on each side of a match

_OMIT = "[... {n} chars omitted ...]"  # marker between windows; never document text


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _pattern_windows(text: str, pattern: re.Pattern,
                     window: int = EXTERNAL_WINDOW_CHARS,
                     cap: int = MAX_DOC_CHARS) -> str:
    """Excerpt `text` as verbatim windows around each `pattern` match, merged
    when overlapping and capped at ~`cap` chars total.

    Replaces head-truncation (`text[:cap]`) for the external-estimates prompt:
    staff fiscal estimates routinely sit deep in 200k-char hearing packets
    (Davies-Property's at char ~108k, Fairfax-Presbyterian-Church's at ~144k),
    where a head slice silently drops them and the figures have to be
    hand-transcribed at the confirm gate. Window text is copied verbatim, so a
    quote drawn from a window still passes the firewall's full-corpus check;
    the omission markers are not document text, so a quote spanning one fails
    that check — which is correct, the model never saw the real bridge text.
    The head is always included as an anchor for project identity.
    """
    if len(text) <= cap:
        return text
    matches = [(m.start(), m.end()) for m in pattern.finditer(text)]
    if not matches:  # selected by label alone — no anchor, keep the old head slice
        return text[:cap] + "\n" + _OMIT.format(n=len(text) - cap)

    # shrink the window if wide ones blow the per-document budget; if even the
    # narrowest do (60+ scattered matches), keep windows in document order
    # until the budget runs out
    for w in (window, window // 2, window // 5, window // 10):
        spans = _merge_spans([(0, w)] + [(max(0, s - w), min(len(text), e + w))
                                         for s, e in matches])
        if sum(e - s for s, e in spans) <= cap:
            break
    else:
        kept, used = [], 0
        for s, e in spans:
            if used + (e - s) > cap:
                log.warning("window budget reached; dropped %d of %d excerpt(s)",
                            len(spans) - len(kept), len(spans))
                break
            kept.append((s, e))
            used += e - s
        spans = kept

    parts: list[str] = []
    prev_end = 0
    for s, e in spans:
        if s > prev_end:
            parts.append(_OMIT.format(n=s - prev_end))
        parts.append(text[s:e])
        prev_end = e
    if prev_end < len(text):
        parts.append(_OMIT.format(n=len(text) - prev_end))
    return "\n".join(parts)

EXTERNAL_NUMERIC_FIELDS = ("net_annual_low", "net_annual_high", "revenue_total",
                           "expenditure_total", "assessed_value",
                           "construction_cost")

EXTERNAL_TOOL = {
    "name": "record_external_estimates",
    "description": "Record fiscal estimates that the applicant or city staff "
                   "published for this project.",
    "input_schema": {
        "type": "object",
        "properties": {
            "estimates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string",
                                   "description": "Document this came from."},
                        "kind": {"type": "string",
                                 "enum": ["applicant_fia", "staff_report", "other"]},
                        "net_annual_low": {"type": ["number", "null"],
                                           "description": "Low end of the stated NET annual fiscal impact."},
                        "net_annual_high": {"type": ["number", "null"]},
                        "revenue_total": {"type": ["number", "null"],
                                          "description": "Stated total annual revenue."},
                        "expenditure_total": {"type": ["number", "null"]},
                        "assessed_value": {"type": ["number", "null"],
                                           "description": "Stated projected assessed/total value."},
                        "construction_cost": {"type": ["number", "null"],
                                              "description": "Stated project cost / cost basis."},
                        "fy": {"type": ["string", "null"]},
                        "quote": {
                            "type": ["string", "null"],
                            "description": "VERBATIM quote (max 25 words) stating these "
                                           "figures, copied exactly.",
                        },
                    },
                    "required": ["source", "kind", "quote"],
                },
            },
        },
        "required": ["estimates"],
    },
}

EXTERNAL_SYSTEM = """\
You extract fiscal estimates that OTHERS published for a development project, \
so an independent analysis can be compared against them. Rules:
0. Record ONLY estimates for the named subject project. Staff reports and \
memos routinely quote fiscal estimates for OTHER projects (a neighbouring \
development, a prior project on a nearby site, a precedent cited for \
comparison) — omit those entirely, no matter how clearly they are stated.
1. Record only figures the documents state. Never compute, sum, or infer one.
2. Every estimate MUST carry `quote`: a verbatim span of at most 25 words \
copied exactly from the document that states the figures.
3. `kind`: applicant_fia for the applicant's or their consultant's fiscal \
impact analysis; staff_report for a city staff report or memo; other otherwise.
4. Report one entry per document that states a fiscal estimate. If a document \
states none, omit it. If no document states any, return an empty list.
5. Annual figures only for net_annual_low/high — never a multi-year total or a \
cumulative sum."""

MAX_EXTERNAL_QUOTE_WORDS = 25


@retry(retry=retry_if_exception(_needs_retry), stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=5, max=120), reraise=True)
def _call_external(prompt: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=DEFAULT_MODEL, max_tokens=4096, system=EXTERNAL_SYSTEM,
        tools=[EXTERNAL_TOOL],
        tool_choice={"type": "tool", "name": "record_external_estimates"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("no tool_use block in response")


_SOURCE_URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")


def _resolve_source_url(source: str, docs: list[ProjectDocument]) -> str | None:
    """Map the model's source label back to a document URL.

    The model routinely decorates labels — "Document 2: <label> – Attachment 1
    Analysis", or the label with its URL appended in parens — so an exact
    lookup misses and the url lands null. Try, in order: exact label, a URL
    embedded in the source string (validated against the documents'), then
    normalized containment in either direction, taking the largest overlap.
    """
    for d in docs:
        if d.label == source:
            return d.url
    for match in _SOURCE_URL_PATTERN.finditer(source):
        url = match.group().rstrip(".,;:")
        for d in docs:
            if d.url == url:
                return d.url
    source_norm = _normalize(source)
    if not source_norm:
        return None
    best_url, best_overlap = None, 0
    for d in docs:
        label_norm = _normalize(d.label or "")
        if label_norm and (label_norm in source_norm or source_norm in label_norm):
            overlap = min(len(label_norm), len(source_norm))
            if overlap > best_overlap:
                best_url, best_overlap = d.url, overlap
    return best_url


def extract_external_estimates(docs: list[ProjectDocument],
                               project_name: str | None = None,
                               ) -> tuple[list[dict], list[str]]:
    """Fiscal estimates published by the applicant or city staff.

    A separate, narrow call: only documents whose label or opening text looks
    like a fiscal analysis or staff report are sent, which keeps this cheap and
    keeps the authoritative figures from being buried under years of plan
    sheets. `project_name` anchors attribution — council packets routinely
    quote estimates for OTHER projects, which must not be recorded as this
    project's. Returns (estimates, notes).
    """
    relevant = [d for d in docs
                if EXTERNAL_DOC_PATTERN.search(d.label or "")
                or EXTERNAL_DOC_PATTERN.search(d.text[:4000])]
    if not relevant:
        return [], ["No applicant fiscal impact analysis or staff report found in "
                    "the document corpus — no external estimate to compare against."]

    # the verbatim-check corpus is deliberately the FULL text, not the windowed
    # prompt: windows are verbatim substrings, so every honest quote verifies,
    # and a quote spanning an omission marker (text the model never saw) fails
    corpus = "\n".join(d.text for d in relevant)
    corpus_norm = _normalize(corpus)
    subject = (f'Extract the fiscal estimates these documents state for the '
               f'project "{project_name}". Ignore estimates for any other '
               'project, even in the same document.\n'
               if project_name else
               "Extract the fiscal estimates these documents state.\n")
    parts = [subject]
    for i, doc in enumerate(relevant, 1):
        parts.append(f"=== DOCUMENT {i}: {doc.label} ({doc.url}) ===\n"
                     f"{_pattern_windows(doc.text, EXTERNAL_DOC_PATTERN)}\n")
    raw = _call_external("\n".join(parts))

    out: list[dict] = []
    notes: list[str] = []
    for entry in raw.get("estimates") or []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source") or "unknown document")
        quote = entry.get("quote")
        if not quote:
            notes.append(f"external estimate from {source!r} dropped: no source quote")
            continue
        if len(quote.split()) > MAX_EXTERNAL_QUOTE_WORDS:
            notes.append(f"external estimate from {source!r} dropped: quote longer "
                         f"than {MAX_EXTERNAL_QUOTE_WORDS} words")
            continue
        if _normalize(quote) not in corpus_norm:
            notes.append(f"external estimate from {source!r} dropped: quote not found "
                         "verbatim in the documents")
            continue
        clean = {"source": source,
                 "kind": entry.get("kind") if entry.get("kind") in
                 ("applicant_fia", "staff_report", "other") else "other",
                 "quote": quote, "fy": entry.get("fy"),
                 "url": _resolve_source_url(source, relevant)}
        kept_any = False
        for field in EXTERNAL_NUMERIC_FIELDS:
            value = entry.get(field)
            if isinstance(value, str):
                try:
                    value = float(value.replace(",", "").replace("$", ""))
                except ValueError:
                    value = None
            clean[field] = value if isinstance(value, (int, float)) else None
            kept_any = kept_any or clean[field] is not None
        if not kept_any:
            notes.append(f"external estimate from {source!r} dropped: no figures")
            continue
        out.append(clean)
    if out:
        notes.append(f"Recorded {len(out)} external fiscal estimate(s) for comparison "
                     f"from {len(relevant)} document(s).")
    return out, notes


def extract_spec_fields(docs: list[ProjectDocument]) -> dict:
    """Run the extraction call + firewall. Returns:
    {project_type, existing_use, fields: {dotted -> {value, confidence,
    source_quote}}, parcel_pins, conflicts, notes}."""
    corpus = "\n".join(doc.text for doc in docs)
    raw = _call_claude(_build_prompt(docs))
    fields, notes = enforce_firewall(raw, corpus)
    strings, string_notes = enforce_string_firewall(raw, corpus)
    notes.extend(string_notes)
    tenure, tenure_notes = enforce_enum_firewall(
        raw.get("proposed_tenure"), corpus, "proposed.tenure", TENURE_EVIDENCE)
    notes.extend(tenure_notes)
    pins = [str(p).strip() for p in raw.get("parcel_pins") or [] if str(p).strip()]
    # PINs must be verbatim in the corpus too — they feed parcel resolution
    corpus_norm = _normalize(corpus)
    verified_pins = [p for p in pins if _normalize(p) in corpus_norm]
    for pin in set(pins) - set(verified_pins):
        notes.append(f"parcel PIN {pin!r} not found in documents — dropped")
    facilities = [str(f).strip() for f in raw.get("corridor_facilities") or []
                  if str(f).strip()]
    verified_facilities = [f for f in facilities if _normalize(f) in corpus_norm]
    for facility in set(facilities) - set(verified_facilities):
        notes.append(f"corridor facility {facility!r} not found in documents — dropped")
    return {
        "project_type": raw.get("project_type", "other"),
        "existing_use": raw.get("existing_use"),
        "fields": fields,
        "strings": strings,
        "corridor_facilities": verified_facilities,
        "tenure": tenure,
        "parcel_pins": verified_pins,
        "conflicts": [str(c) for c in raw.get("conflicts") or []],
        "notes": notes,
    }
