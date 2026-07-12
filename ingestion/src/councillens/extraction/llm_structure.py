"""
Phase 3: LLM structuring pass.

For a given meeting, send the agenda text + minutes text + relevant
transcript chunks to Claude and get back structured JSON: agenda items,
entities mentioned (people/projects/ordinances/locations), votes with
breakdown, and a meeting summary.

Key design point from PLAN.md: when an entity already exists (matched by
canonical_slug), APPEND to its running summary rather than overwriting, so
"progress over time" is queryable later without re-summarizing everything.
"""
import json
from anthropic import Anthropic
from councillens.config import ANTHROPIC_API_KEY

client = Anthropic(api_key=ANTHROPIC_API_KEY)

EXTRACTION_PROMPT = """\
You are extracting structured facts from a City of Fairfax, VA council meeting.
Given the agenda, minutes, and transcript excerpts below, return ONLY valid JSON
(no markdown fences, no preamble) matching this shape:

{{
  "summary": "plain-language summary of what happened",
  "agenda_items": [{{"label": "...", "description": "...", "outcome": "..."}}],
  "entities": [
    {{"type": "person|project|ordinance|case_number|location|topic",
      "name": "...", "canonical_slug": "kebab-case-slug", "context": "..."}}
  ],
  "votes": [
    {{"agenda_item_label": "...", "description": "...", "motion_result": "passed|failed|deferred",
      "vote_breakdown": {{"member_name": "yes|no|abstain|absent"}}}}
  ]
}}

AGENDA:
{agenda_text}

MINUTES:
{minutes_text}

TRANSCRIPT EXCERPTS:
{transcript_text}
"""


def structure_meeting(agenda_text: str, minutes_text: str, transcript_text: str) -> dict:
    """Call Claude to produce structured JSON for one meeting. Raises if the
    response isn't valid JSON - caller should catch and log for retry rather
    than silently dropping a meeting's data."""
    raise NotImplementedError(
        "Phase 3 task: call client.messages.create with EXTRACTION_PROMPT, "
        "parse response as JSON, return dict"
    )


def upsert_entity(session, entity_type: str, name: str, canonical_slug: str,
                   meeting_id: int, new_context: str) -> None:
    """Find or create an Entity by canonical_slug; append new_context to its
    running `summary` rather than overwriting. Also create an EntityMention row."""
    raise NotImplementedError("Phase 3 task")
