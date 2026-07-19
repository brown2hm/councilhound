"""Bundle-file primitives: frontmatter round-trip, deterministic page
writes, reserved index.md/log.md rendering, and the {{metric:...}} marker
grammar. Everything here is pure file/string handling — no DB."""
import hashlib
import os
import re
from datetime import date

import yaml

RESERVED = {"index.md", "log.md"}
# curator-owned pages seeded by export.py; everything else generated in a
# project dir (history.md, index.md, log.md) is pipeline-owned
CURATED_PAGES = {"overview.md", "positions.md", "impact.md"}
PAGE_ORDER = ["overview", "history", "positions", "impact"]

MARKER_RE = re.compile(r"\{\{(metric|map):([a-z0-9][a-z0-9-]*)\}\}")
# root-absolute markdown links assert bundle-internal relationships
_BUNDLE_LINK_RE = re.compile(r"\]\((/[^)#\s]+)")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
CURATOR_OFF_RE = re.compile(
    r"<!--\s*curator:off\s*-->.*?<!--\s*/curator:off\s*-->", re.DOTALL)


def slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", name.lower())).strip("-")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_page(frontmatter: dict, body: str) -> str:
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True,
                        default_flow_style=False, width=88)
    return f"---\n{fm}---\n\n{body.strip()}\n"


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


def render_index(title: str, entries: list[tuple[str, str, str]]) -> str:
    """Reserved index.md: no frontmatter, one line per concept.
    entries: (root-absolute link, title, one-line description)."""
    lines = [f"# {title}", ""]
    lines += [f"- [{name}]({link}) — {desc}" if desc else f"- [{name}]({link})"
              for link, name, desc in entries]
    return "\n".join(lines) + "\n"


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
