"""
Phase 3 setup: seed person entities from agenda headers.

Data-driven rather than hardcoded — the 24-month window spans a council
turnover, so rosters are parsed from every agenda's header block. Which
parser a body uses, and which title aliases each role gets, come from the
jurisdiction config (bodies[].roster); ROSTER_PARSERS maps parser ids to
functions returning {role_key: [names]}. The City's formats:

  City Council agendas:   "Mayor" line, then the name; "City Council" line,
                          then one member name per line.
  Planning Commission:    "Chair: X / Vice-Chair: Y / Commissioners: A, B, C"
  School Board:           "Chair" (or "Chairman") line, then the name; "Board
                          Members" line, then TWO names per line (the header
                          lays them out in columns; html_to_text collapses the
                          nbsp gap, so a four-token line is split in half).
  PRAB / HHCAB agendas are uploaded PDFs with no roster block, so those
  boards' members are not seeded; the LLM pass still resolves names it meets.
  A body whose agendas carry no roster can pin one in config
  (roster.static) — the `static` parser, also the fallback when a header
  parser finds nothing and a static roster exists.

Seeded people get aliases ("Catherine S. Read", "Catherine Read", "Read",
"Mayor Read", "Councilmember Read", ...) so the LLM pass and vote-breakdown
names resolve to one entity regardless of how the documents refer to them.
Ambiguous aliases (shared last names) are skipped by add_alias.
"""
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.bodies import REGISTRY, Body
from councilhound.db.models import Document, Meeting
from councilhound.entities import add_alias, display_name, resolve_entity

log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){1,4},?(?: Jr\.?| Sr\.?| I{2,3}| IV)?$")
# header lines that pass the name regex but are labels: the bodies' own
# names plus the fixed layout words agendas use
_NOT_NAMES = tuple(sorted({*(b.label.lower() for b in REGISTRY.bodies.values()),
                           "council chamber", "board members", "city hall"}))


def _looks_like_name(line: str) -> bool:
    line = line.strip()
    return bool(line) and len(line) < 50 and bool(_NAME_RE.match(line)) \
        and not line.lower().startswith(_NOT_NAMES)


def parse_council_header(raw_text: str) -> dict:
    """Return {'mayor': name|None, 'members': [names]} from a council agenda."""
    lines = [l.strip() for l in raw_text.split("\n")[:60]]
    mayor, members = None, []
    i = 0
    while i < len(lines):
        if lines[i] == "Mayor":
            for j in range(i + 1, min(i + 4, len(lines))):
                if _looks_like_name(lines[j]):
                    mayor = lines[j]
                    break
        elif lines[i] == "City Council":
            for j in range(i + 1, len(lines)):
                if not lines[j]:
                    continue
                if _looks_like_name(lines[j]):
                    members.append(lines[j])
                else:
                    break
            break
        i += 1
    return {"mayor": mayor, "members": members}


_PC_RE = re.compile(
    r"Chair:\s*(?P<chair>[^/\n]+?)\s*/\s*Vice-?\s?Chair:\s*(?P<vice>[^/\n]+?)\s*/\s*"
    r"Commissioners?:\s*(?P<rest>[^\n]+)",
    re.IGNORECASE,
)


def parse_pc_header(raw_text: str) -> dict:
    """Return {'chair': ..., 'vice_chair': ..., 'commissioners': [...]} or empties."""
    m = _PC_RE.search(raw_text[:3000])
    if not m:
        return {"chair": None, "vice_chair": None, "commissioners": []}
    commissioners = []
    for c in m.group("rest").split(","):
        # trim a glued-on agenda list ("Paul Cunningham 1. Pledge of...")
        c = re.split(r"\s+\d+[.)]\s", c.strip() + " ")[0].strip()
        if _looks_like_name(c):
            commissioners.append(c)
    return {
        "chair": m.group("chair").strip(),
        "vice_chair": m.group("vice").strip(),
        "commissioners": commissioners,
    }


def _split_glued_names(line: str) -> list[str]:
    """A School Board header line holds two side-by-side names whose gap
    (nbsp run) html_to_text collapsed to one space. Four capitalised tokens
    split into two names; anything else is taken as one name if it looks
    like one. Board members have all had two-token names (2021-2026)."""
    tokens = line.split()
    if len(tokens) == 4 and all(_looks_like_name(" ".join(pair))
                                for pair in (tokens[:2], tokens[2:])):
        return [" ".join(tokens[:2]), " ".join(tokens[2:])]
    return [line] if _looks_like_name(line) else []


def parse_school_board_header(raw_text: str) -> dict:
    """Return {'chair': name|None, 'members': [names]} from a School Board
    agenda header, or empties when the block is absent."""
    lines = [l.strip() for l in raw_text.split("\n")[:60]]
    chair, members = None, []
    i = 0
    while i < len(lines):
        if lines[i] in ("Chair", "Chairman", "Chairwoman"):
            for j in range(i + 1, min(i + 4, len(lines))):
                if _looks_like_name(lines[j]):
                    chair = lines[j]
                    break
        elif lines[i] == "Board Members":
            for j in range(i + 1, len(lines)):
                if not lines[j]:
                    continue
                # the block ends at the meeting title ("Regular School Board
                # Meeting"), which is four capitalised words and would
                # otherwise split into two plausible "names"
                if re.search(r"meeting|session|retreat", lines[j], re.IGNORECASE):
                    break
                names = _split_glued_names(lines[j])
                if not names:
                    break
                members.extend(names)
            break
        i += 1
    return {"chair": chair, "members": members}


_SUFFIXES = ("jr", "sr", "ii", "iii", "iv")


def surname_forms(name: str) -> list[str]:
    """The last name, plus the two-word surname when the name has one
    ("Rachna Sizemore Heizer" -> ["Heizer", "Sizemore Heizer"]; an initial
    or a comma before the last token is not a surname part)."""
    tokens = [t for t in display_name(name).replace(",", " ").split()
              if t.lower().rstrip(".") not in _SUFFIXES]
    if not tokens:
        return []
    forms = [tokens[-1]]
    if len(tokens) >= 3 and not tokens[-2].endswith(".") and tokens[-2][:1].isupper():
        forms.append(f"{tokens[-2]} {tokens[-1]}")
    return forms


def _seed_person(session: Session, name: str, title_aliases: list[str], meeting_id: int,
                 extra_aliases: tuple[str, ...] = ()) -> None:
    if not name or not _looks_like_name(name):
        return
    entity = resolve_entity(session, "person", name, first_seen_meeting_id=meeting_id)
    if entity is None:
        return
    for last in surname_forms(name):
        add_alias(session, entity, last)
        for title in title_aliases:
            add_alias(session, entity, f"{title} {last}")
    for alias in extra_aliases:
        add_alias(session, entity, alias)


# --- parser registry: id -> (raw agenda text, body) -> {role_key: [names]} ---

def _city_council_header(raw_text: str, _body: Body) -> dict[str, list[str]]:
    h = parse_council_header(raw_text)
    return {"mayor": [h["mayor"]] if h["mayor"] else [], "member": list(h["members"])}


def _pc_chair_line(raw_text: str, _body: Body) -> dict[str, list[str]]:
    h = parse_pc_header(raw_text)
    return {"chair": [h["chair"]] if h["chair"] else [],
            "vice_chair": [h["vice_chair"]] if h["vice_chair"] else [],
            "commissioner": list(h["commissioners"])}


def _school_board_glued(raw_text: str, _body: Body) -> dict[str, list[str]]:
    h = parse_school_board_header(raw_text)
    return {"chair": [h["chair"]] if h["chair"] else [], "member": list(h["members"])}


def static_roster(body: Body) -> dict[str, list[str]]:
    """The config-pinned roster (bodies[].roster.static), grouped by role."""
    out: dict[str, list[str]] = {}
    if body.roster:
        for m in body.roster.static:
            out.setdefault(m.role, []).append(m.name)
    return out


def _static(_raw_text: str, body: Body) -> dict[str, list[str]]:
    return static_roster(body)


_BOS_LINE = re.compile(
    r"^(?:(?P<chair>Chairman|Chair|Vice[- ]Chairman|Vice[- ]Chair)\s+(?P<chair_last>[A-Z][\w'-]+(?: [A-Z][\w'-]+)?)"
    r"|Supervisor\s+(?P<sup_last>[A-Z][\w'-]+(?: [A-Z][\w'-]+)?),\s*(?P<district>[A-Z][\w' ]+?) District)\s*$")


def _bos_supervisor_lines(raw_text: str, body: Body) -> dict[str, list[str]]:
    """Fairfax County's annotated Board agenda names each member once under
    'Matters Presented by Board Members' ('Chairman McKay', 'Supervisor
    Smith, Sully District') — last names only, so each line is resolved
    against the static roster by surname (and district when given). The
    static roster supplies the full names; unmatched lines are skipped."""
    if not body.roster or not body.roster.static:
        return {}
    by_role: dict[str, list[str]] = {}
    for line in raw_text.split("\n")[:400]:
        m = _BOS_LINE.match(line.strip())
        if not m:
            continue
        last = (m.group("chair_last") or m.group("sup_last")).lower()
        district = (m.group("district") or "").strip().lower()
        for member in body.roster.static:
            forms = [f.lower() for f in surname_forms(member.name)]
            if last not in forms:
                continue
            if district and member.district and member.district.lower() != district:
                continue
            if member.name not in by_role.setdefault(member.role, []):
                by_role[member.role].append(member.name)
            break
    return by_role


ROSTER_PARSERS = {
    "city_council_header": _city_council_header,
    "pc_chair_line": _pc_chair_line,
    "school_board_glued": _school_board_glued,
    "bos_supervisor_lines": _bos_supervisor_lines,
    "static": _static,
}


def parse_roster(raw_text: str, body: Body) -> dict[str, list[str]]:
    """{role_key: [names]} from an agenda's header per the body's parser;
    empty when the body has no roster config or nothing parses. Falls back
    to the static roster when one is pinned."""
    if not body.roster:
        return {}
    parser = ROSTER_PARSERS[body.roster.parser]
    parsed = {k: [n for n in v if n] for k, v in parser(raw_text, body).items()}
    if not any(parsed.values()):
        parsed = static_roster(body)
    return {k: v for k, v in parsed.items() if v}


def district_alias(district: str | None, noun: str | None) -> str | None:
    """"Sully District Supervisor" for a district seat — the record says
    "Supervisor Smith, Sully District" and "the Sully District Supervisor"
    interchangeably. None for at-large seats: several members share one,
    so "At-Large Commissioner" names nobody in particular."""
    if not district or not noun or district.strip().lower().startswith("at-large"):
        return None
    return f"{district.strip()} District {noun}"


def seed_people(session: Session) -> dict:
    """Scan every agenda's header and seed person entities + aliases."""
    docs = session.execute(
        select(Document, Meeting)
        .join(Meeting, Document.meeting_id == Meeting.id)
        .where(Document.doc_type == "agenda", Document.raw_text.isnot(None))
        .order_by(Meeting.meeting_date)
    ).all()

    seen_names: set[str] = set()
    for doc, meeting in docs:
        body = REGISTRY.bodies.get(meeting.body)
        if body is None or body.roster is None:
            continue
        districts = {m.name: m.district for m in body.roster.static if m.district}
        for role_key, names in parse_roster(doc.raw_text, body).items():
            titles = body.seed_titles(role_key)
            for name in names:
                alias = district_alias(districts.get(name), body.roster.district_title
                                       or (titles[0] if titles else None))
                _seed_person(session, name, titles, meeting.id, (alias,) if alias else ())
                seen_names.add(name)
    session.commit()

    from councilhound.db.models import Entity, EntityAlias
    n_people = session.scalar(select(func.count(Entity.id)).where(Entity.entity_type == "person"))
    n_aliases = session.scalar(select(func.count(EntityAlias.id)))
    result = {"people": n_people, "aliases": n_aliases, "names_seen": len(seen_names)}
    log.info("seed_people: %s", result)
    return result
