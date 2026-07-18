"""`impact-setup-jurisdiction`: pin tax/budget rates + feed URLs with provenance.

One-time guided task, run locally by a human: fetch the city's tax/budget
pages, let the LLM propose each rate WITH a verbatim quote (same firewall
discipline as intake), then require per-value human confirmation before
anything lands in the YAML. Nothing undiscoverable is guessed — declining a
candidate leaves the value null and the fiscal module keeps refusing to run
on it (jurisdiction.require_rate).
"""
from __future__ import annotations

import logging
import os
import re

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.impact.jurisdiction import JurisdictionConfig

log = logging.getLogger(__name__)

SETUP_PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# value key -> (human label, unit hint, page URLs to read)
RATE_SOURCES: dict[str, tuple[str, str, list[str]]] = {
    "tax.real_estate_rate_per_100": (
        "Real estate tax rate", "$ per $100 of assessed value",
        ["https://www.fairfaxva.gov/Property-Business/Taxes/Real-Estate-Tax"]),
    "tax.meals_tax_rate": (
        "Meals (food & beverage) tax rate", "fraction, e.g. 0.04 for 4%",
        ["https://www.fairfaxva.gov/Property-Business/Taxes/Excise-Taxes"]),
    "tax.sales_tax_local_share": (
        "Local-option sales tax share", "fraction of taxable sales, e.g. 0.01",
        ["https://www.fairfaxva.gov/Property-Business/Taxes/Federal-and-State-Taxes",
         "https://www.fairfaxva.gov/Property-Business/Taxes"]),
    "tax.personal_property_per_household": (
        "Personal property tax revenue per household", "$/household/yr (budget actuals)",
        ["https://www.fairfaxva.gov/Government/Finance/Budget"]),
    "budget.general_fund_expenditure": (
        "General Fund expenditure", "$ total, adopted budget",
        ["https://www.fairfaxva.gov/Government/Finance/Budget"]),
    "budget.population_basis": (
        "Population basis used with the budget", "residents",
        ["https://www.fairfaxva.gov/Government/Finance/Budget"]),
}

EXTRACT_TOOL = {
    "name": "record_rate_candidates",
    "description": "Record tax/budget values found in the supplied municipal pages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": ["number", "null"]},
                        "fy": {"type": ["string", "null"],
                               "description": "fiscal year the value applies to, e.g. FY2026"},
                        "source_url": {"type": ["string", "null"]},
                        "source_quote": {"type": ["string", "null"],
                                         "description": "verbatim quote, max 15 words"},
                    },
                    "required": ["key", "value", "fy", "source_url", "source_quote"],
                },
            },
        },
        "required": ["candidates"],
    },
}

SYSTEM = """\
You extract municipal tax rates and budget figures. Rules:
- Only report values the pages actually state; value=null when absent.
- Every non-null value needs a verbatim source_quote of at most 15 words.
- Rates described in percent must be reported in the requested unit.
- Report the fiscal year each value applies to when stated."""


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
        model=DEFAULT_MODEL, max_tokens=4096, system=SYSTEM,
        tools=[EXTRACT_TOOL], tool_choice={"type": "tool", "name": "record_rate_candidates"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("no tool_use block in response")


def _page_text(url: str) -> str:
    from bs4 import BeautifulSoup

    from councilhound import http
    from councilhound.scraper.fairfax_projects import FAIRFAX_HEADERS
    headers = FAIRFAX_HEADERS if "fairfaxva.gov" in url else None
    soup = BeautifulSoup(http.get(url, headers=headers).text, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return re.sub(r"\n\s*\n+", "\n\n", soup.get_text("\n")).strip()


def _set_dotted(cfg: JurisdictionConfig, dotted: str, value, source, fy) -> None:
    obj = cfg
    parts = dotted.split(".")
    for part in parts[:-1]:
        obj = getattr(obj, part)
    pinned = getattr(obj, parts[-1])
    pinned.value = value
    pinned.source = source
    pinned.fy = fy


def run_setup(jurisdiction: str, echo=print) -> None:
    import click

    cfg = JurisdictionConfig.load(jurisdiction)

    pages: dict[str, str] = {}
    for _, _, urls in RATE_SOURCES.values():
        for url in urls:
            if url not in pages:
                echo(f"fetching {url}")
                try:
                    pages[url] = _page_text(url)
                except Exception as exc:
                    echo(f"  FAILED: {exc}")
                    pages[url] = ""

    prompt_parts = ["Extract these values from the pages below:\n"]
    for key, (label, unit, urls) in RATE_SOURCES.items():
        prompt_parts.append(f"- key={key}: {label} ({unit}); look in: {', '.join(urls)}")
    for url, text in pages.items():
        prompt_parts.append(f"\n=== PAGE {url} ===\n{text[:30_000]}")
    echo("asking the model for candidates (with verbatim quotes)...")
    raw = _call_claude("\n".join(prompt_parts))
    candidates = {c.get("key"): c for c in raw.get("candidates", [])}

    corpus = "\n".join(pages.values()).lower()
    pinned = skipped = 0
    for key, (label, unit, _urls) in RATE_SOURCES.items():
        cand = candidates.get(key) or {}
        value, quote = cand.get("value"), cand.get("source_quote")
        quote_ok = bool(quote) and len(quote.split()) <= 15 and \
            re.sub(r"[^a-z0-9]+", " ", quote.lower()).strip() in \
            re.sub(r"[^a-z0-9]+", " ", corpus)
        echo(f"\n{label} ({unit})")
        if value is not None and quote_ok:
            echo(f"  candidate: {value}  [{cand.get('fy')}]  \"{quote}\"")
            echo(f"  source: {cand.get('source_url')}")
        elif value is not None:
            echo(f"  candidate {value} REJECTED (quote missing/not verbatim) — enter manually")
            value = None
        else:
            echo("  no candidate found on the pages — enter manually or skip")
        answer = click.prompt("  value (blank to skip)", default="", show_default=False).strip()
        if answer:
            value = float(answer)
            source = click.prompt("  source URL", default=cand.get("source_url") or "")
            fy = click.prompt("  fiscal year", default=cand.get("fy") or "")
        elif value is not None and click.confirm("  pin this candidate?", default=True):
            source, fy = cand.get("source_url"), cand.get("fy")
        else:
            echo("  left null (fiscal metrics depending on it will refuse to run)")
            skipped += 1
            continue
        _set_dotted(cfg, key, value, source, fy)
        pinned += 1

    if not cfg.transit_feeds:
        feeds = click.prompt(
            "\nGTFS feed URLs (comma-separated; find current ones at "
            "https://mobilitydatabase.org — blank to skip)",
            default="", show_default=False).strip()
        if feeds:
            cfg.transit_feeds = [f.strip() for f in feeds.split(",") if f.strip()]

    path = cfg.save()
    echo(f"\npinned {pinned} value(s), skipped {skipped} -> {path}")
