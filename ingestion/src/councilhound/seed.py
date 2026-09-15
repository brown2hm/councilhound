"""
Phase 3 setup: seed person entities from agenda headers.

Data-driven rather than hardcoded — the 24-month window spans a council
turnover, so rosters are parsed from every agenda's header block:

  City Council agendas:   "Mayor" line, then the name; "City Council" line,
                          then one member name per line.
  Planning Commission:    "Chair: X / Vice-Chair: Y / Commissioners: A, B, C"
  School Board:           "Chair" (or "Chairman") line, then the name; "Board
                          Members" line, then TWO names per line (the header
                          lays them out in columns; html_to_text collapses the
                          nbsp gap, so a four-token line is split in half).
  PRAB / HHCAB agendas are uploaded PDFs with no roster block, so those
  boards' members are not seeded; the LLM pass still resolves names it meets.

Seeded people get aliases ("Catherine S. Read", "Catherine Read", "Read",
"Mayor Read", "Councilmember Read", ...) so the LLM pass and vote-breakdown
names resolve to one entity regardless of how the documents refer to them.
Ambiguous aliases (shared last names) are skipped by add_alias.
"""
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import Document, Meeting
from councilhound.entities import add_alias, display_name, resolve_entity

log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){1,4},?(?: Jr\.?| Sr\.?| I{2,3}| IV)?$")


def _looks_like_name(line: str) -> bool:
    line = line.strip()
    return bool(line) and len(line) < 50 and bool(_NAME_RE.match(line)) \
        and not line.lower().startswith(("city council", "planning commission", "council chamber",
                                         "school board", "board members", "city hall"))


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


def _seed_person(session: Session, name: str, title_aliases: list[str], meeting_id: int) -> None:
    if not name or not _looks_like_name(name):
        return
    entity = resolve_entity(session, "person", name, first_seen_meeting_id=meeting_id)
    if entity is None:
        return
    tokens = [t for t in display_name(name).split() if t.lower().rstrip(".") not in ("jr", "sr", "ii", "iii", "iv")]
    last = tokens[-1] if tokens else ""
    if last:
        add_alias(session, entity, last)
        for title in title_aliases:
            add_alias(session, entity, f"{title} {last}")


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
        if meeting.body == "city_council":
            header = parse_council_header(doc.raw_text)
            if header["mayor"]:
                _seed_person(session, header["mayor"], ["Mayor"], meeting.id)
                seen_names.add(header["mayor"])
            for member in header["members"]:
                _seed_person(session, member, ["Councilmember", "Council Member", "Councilwoman", "Councilman"], meeting.id)
                seen_names.add(member)
        elif meeting.body == "planning_commission":
            header = parse_pc_header(doc.raw_text)
            for role, titles in (("chair", ["Chair", "Chairman", "Commissioner"]),
                                 ("vice_chair", ["Vice-Chair", "Vice Chair", "Commissioner"])):
                if header[role]:
                    _seed_person(session, header[role], titles, meeting.id)
                    seen_names.add(header[role])
            for c in header["commissioners"]:
                _seed_person(session, c, ["Commissioner"], meeting.id)
                seen_names.add(c)
        elif meeting.body == "school_board":
            # Titles are body-qualified so the members roster can tell a
            # School Board chair from a Planning Commission chair by alias.
            header = parse_school_board_header(doc.raw_text)
            if header["chair"]:
                _seed_person(session, header["chair"], ["School Board Chair"], meeting.id)
                seen_names.add(header["chair"])
            for member in header["members"]:
                _seed_person(session, member, ["School Board Member"], meeting.id)
                seen_names.add(member)
    session.commit()

    from councilhound.db.models import Entity, EntityAlias
    n_people = session.scalar(select(func.count(Entity.id)).where(Entity.entity_type == "person"))
    n_aliases = session.scalar(select(func.count(EntityAlias.id)))
    result = {"people": n_people, "aliases": n_aliases, "names_seen": len(seen_names)}
    log.info("seed_people: %s", result)
    return result
