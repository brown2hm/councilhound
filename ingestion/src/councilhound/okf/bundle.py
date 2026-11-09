"""Bundle-file primitives: frontmatter round-trip, deterministic page
writes, reserved index.md/log.md rendering, the OKF v0.2 trust fields
(`generated`, actors, ISO 8601 datetimes), and the {{metric:...}} marker
grammar. Everything here is pure file/string handling — no DB."""
import hashlib
import os
import re
from datetime import date, datetime, timezone

import yaml

OKF_VERSION = "0.2"
RESERVED = {"index.md", "log.md"}
# curator-owned pages seeded by export.py; everything else generated in a
# project dir (history.md, index.md, log.md) is pipeline-owned
CURATED_PAGES = {"overview.md", "positions.md", "impact.md"}
PAGE_ORDER = ["overview", "history", "positions", "impact", "documents"]

# OKF v0.2 §7 actor convention: `process:<id>` for automated processes,
# `<producer>/<version>` for agents. The deterministic export/refresh is the
# process; the LLM curator is an agent versioned by its model.
PIPELINE_ACTOR = "process:councilhound-okf"
# OKF v0.2 §5.4 reserves `status` for lifecycle. The city's project status
# lives under `project_status` so a v0.2 consumer never reads
# `pre_application` as an unknown lifecycle value.
LIFECYCLE_STATUSES = {"draft", "stable", "deprecated"}
# frontmatter keys rendered first, in this order, so every page reads the
# same way; producer-defined keys follow in insertion order
_KEY_ORDER = ["type", "title", "description", "resource", "tags", "generated",
              "verified", "status", "stale_after", "project_status"]
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
# §7: `human:<id>`, `process:<id>`, or `<producer>/<version>`
_ACTOR_RE = re.compile(r"^(human:\S+|process:\S+|[A-Za-z0-9_.-]+/\S+)$")


def curator_actor(model: str) -> str:
    return f"councilhound-curator/{model}"


def is_actor(value) -> bool:
    return isinstance(value, str) and bool(_ACTOR_RE.match(value))


def verified_events(frontmatter: dict | None) -> list[dict]:
    """The `verified` family as a list (§5.2: a bare `{by, at}` mapping is a
    one-element list). Malformed entries are dropped here and reported by
    lint, so consumers never trip over them."""
    raw = (frontmatter or {}).get("verified")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def trust_tier(frontmatter: dict | None) -> str:
    """§5.3: unverified, machine-confirmed, or human-reviewed — keyed off the
    `human:` prefix, which is why the actor convention is enforced."""
    events = verified_events(frontmatter)
    if any(str(e.get("by", "")).startswith("human:") for e in events):
        return "human-reviewed"
    return "machine-confirmed" if events else "unverified"


def iso_datetime(value) -> str:
    """OKF v0.2 §5: every timestamp is an ISO 8601 datetime with an explicit
    offset. A bare date (our meeting-derived stamps) becomes midnight UTC; a
    naive datetime is taken as UTC; an aware one is converted."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc).replace(microsecond=0)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    text = str(value).strip()
    if _ISO_DATETIME_RE.match(text):
        return text
    return f"{text[:10]}T00:00:00Z"


def is_iso_datetime(value) -> bool:
    if isinstance(value, datetime):
        return value.tzinfo is not None
    return isinstance(value, str) and bool(_ISO_DATETIME_RE.match(value))


def generated(by: str, at) -> dict:
    """The v0.2 `generated` family: who produced the content and when it last
    meaningfully changed."""
    return {"by": by, "at": iso_datetime(at)}


def generated_at(frontmatter: dict | None) -> str | None:
    """The page's last-change instant as an ISO string: `generated.at`, or
    the v0.1 `timestamp` a v0.2 consumer may fall back to (§13.1)."""
    fm = frontmatter or {}
    gen = fm.get("generated")
    raw = gen.get("at") if isinstance(gen, dict) else None
    if raw in (None, ""):
        raw = fm.get("timestamp")
    if raw in (None, ""):
        return None
    return iso_datetime(raw)


def generated_date(frontmatter: dict | None) -> date | None:
    stamp = generated_at(frontmatter)
    if stamp is None:
        return None
    try:
        return date.fromisoformat(stamp[:10])
    except ValueError:
        return None


def order_frontmatter(frontmatter: dict) -> dict:
    head = {k: frontmatter[k] for k in _KEY_ORDER if k in frontmatter}
    head.update({k: v for k, v in frontmatter.items() if k not in head})
    return head

MARKER_RE = re.compile(r"\{\{(metric|map):([a-z0-9][a-z0-9-]*)\}\}")
# root-absolute markdown links assert bundle-internal relationships
_BUNDLE_LINK_RE = re.compile(r"\]\((/[^)#\s]+)")
# absolute links out to the public site, which the bundle does not contain
_SITE_LINK_TEMPLATE = r"{base}/(members|topics|development)/([A-Za-z0-9][A-Za-z0-9_-]*)"
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
CURATOR_OFF_OPEN = "<!-- curator:off -->"
CURATOR_OFF_CLOSE = "<!-- /curator:off -->"
CURATOR_OFF_RE = re.compile(
    r"<!--\s*curator:off\s*-->.*?<!--\s*/curator:off\s*-->", re.DOTALL)


def slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", name.lower())).strip("-")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_frontmatter(frontmatter: dict) -> str:
    return yaml.safe_dump(order_frontmatter(frontmatter), sort_keys=False,
                          allow_unicode=True, default_flow_style=False, width=88)


def render_page(frontmatter: dict, body: str) -> str:
    return f"---\n{render_frontmatter(frontmatter)}---\n\n{body.strip()}\n"


def parse_page(text: str) -> tuple[dict | None, str]:
    """Returns (frontmatter, body); frontmatter is None when absent."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    return yaml.safe_load(m.group(1)) or {}, text[m.end():].lstrip("\n")


def read_page(path: str) -> tuple[dict | None, str] | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return parse_page(f.read())


def write_text(bundle_dir: str, rel_path: str, text: str) -> bool:
    """Write only when content differs; returns whether the file changed."""
    path = os.path.join(bundle_dir, rel_path)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def write_page(bundle_dir: str, rel_path: str, frontmatter: dict, body: str) -> bool:
    return write_text(bundle_dir, rel_path, render_page(frontmatter, body))


def render_index(title: str, entries: list[tuple[str, str, str]],
                 root: bool = False) -> str:
    """Reserved index.md: one line per concept, no frontmatter — except the
    bundle root, which declares the spec version it targets (v0.2 §12, the
    only frontmatter an index may carry).
    entries: (root-absolute link, title, one-line description)."""
    lines = [f"# {title}", ""]
    lines += [f"- [{name}]({link}) — {desc}" if desc else f"- [{name}]({link})"
              for link, name, desc in entries]
    body = "\n".join(lines) + "\n"
    if root:
        return f"---\n{render_frontmatter({'okf_version': OKF_VERSION})}---\n\n{body}"
    return body


def append_log(bundle_dir: str, rel_dir: str, lines: list[str],
               on: date | None = None) -> None:
    """Append dated bullets to the reserved log.md (chronological, oldest
    first). Reuses the trailing date heading when it matches."""
    if not lines:
        return
    day = (on or date.today()).isoformat()
    path = os.path.join(bundle_dir, rel_dir, "log.md") if rel_dir else \
        os.path.join(bundle_dir, "log.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    else:
        existing = "# Log\n"
    headings = re.findall(r"^## (\d{4}-\d{2}-\d{2})$", existing, re.MULTILINE)
    out = existing.rstrip("\n") + "\n"
    if not headings or headings[-1] != day:
        out += f"\n## {day}\n\n"
    out += "".join(f"- {line}\n" for line in lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)


def bundle_links(body: str) -> list[str]:
    return [m.group(1) for m in _BUNDLE_LINK_RE.finditer(body)]


def site_links(text: str, base_url: str) -> list[tuple[str, str]]:
    """(section, slug) for every link out to the public site, e.g.
    ("members", "billy-bates"). Trailing segments are ignored, so
    /development/Foo/wiki yields ("development", "Foo")."""
    pattern = re.compile(
        _SITE_LINK_TEMPLATE.format(base=re.escape(base_url.rstrip("/"))))
    return [(m.group(1), m.group(2)) for m in pattern.finditer(text)]


def markers(body: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in MARKER_RE.finditer(body)]


def walk_pages(bundle_dir: str):
    """Yield (rel_path, absolute_path) for every .md file, sorted for
    deterministic iteration."""
    found = []
    for root, _dirs, files in os.walk(bundle_dir):
        for name in files:
            if name.endswith(".md"):
                path = os.path.join(root, name)
                found.append((os.path.relpath(path, bundle_dir), path))
    return sorted(found)
