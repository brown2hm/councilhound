"""The November ballot as one page: every contest in ballot order, each
candidate with the same checklist of outside sources (and what was looked
for and not found), and the questionnaires that put the same questions to
everyone in a race, answer by answer.

Nothing here comes from the meeting record except the link to a member
page for candidates who already have a voting record; the rest is the
pinned tables in app.candidates and app.questionnaires."""
import re
import unicodedata

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import candidates, questionnaires, terms
from app.db import db_session
from app.routers import members as members_router

router = APIRouter()

# how many each voter may choose, from the contest as printed
_VOTE_FOR = re.compile(r"vote for (?:not more than )?(\w+)")
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _words(name: str) -> list[str]:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return [w for w in re.findall(r"[a-z]+(?:'[a-z]+)?", name) if len(w) > 1]


def _first_last(name: str) -> tuple[str, str] | None:
    w = _words(name)
    return (w[0], w[-1]) if len(w) >= 2 else None


def _member_pages(session: Session) -> dict[str, dict]:
    """ballot name -> {slug, roles} for candidates who already have a member
    page, matched on first and last name together (ballot name or alias),
    never on a last name alone: 'Stacy Hall' is not 'City Hall' and two
    Browns are two people."""
    by_name: dict[tuple[str, str], list[dict]] = {}
    for m in members_router._roster(session).values():
        key = _first_last(m["entity"].name)
        if key:
            by_name.setdefault(key, []).append(m)
    out = {}
    for c in candidates.CANDIDATES:
        hits = {id(m): m for form in (c.ballot_name, *c.aliases)
                for m in by_name.get(_first_last(form) or ("", ""), [])}
        if len(hits) == 1:
            m = next(iter(hits.values()))
            out[c.ballot_name] = {"slug": m["entity"].canonical_slug,
                                  "roles": members_router._sorted_roles(m["roles"])}
    return out


def _source(s: candidates.CandidateSource) -> dict:
    return {"url": s.url, "publisher": s.publisher, "kind": s.kind,
            "kind_label": candidates.KIND_LABEL[s.kind], "title": s.title,
            "facts": list(s.facts), "checked": s.checked.isoformat(),
            "published": s.published.isoformat() if s.published else None}


def _questionnaire(q: questionnaires.Questionnaire) -> dict:
    """Every candidate in the contest, in ballot order: an answer per
    question (None where they left it blank), or responded False."""
    given = {r.candidate: r for r in q.responses}
    rows = []
    for c in candidates.in_contest(q.contest):
        r = given.get(c.ballot_name)
        rows.append({
            "candidate": c.ballot_name,
            "responded": r is not None,
            "url": (r.url if r and r.url else q.url),
            "published": r.published.isoformat() if r and r.published else None,
            "answers": {k: dict(r.answers).get(k) for k, _ in q.questions} if r else {},
        })
    return {"key": q.key, "contest": q.contest, "publisher": q.publisher, "title": q.title,
            "url": q.url, "checked": q.checked.isoformat(), "note": q.note,
            "questions": [{"key": k, "asked": asked} for k, asked in q.questions],
            "responses": rows}


@router.get("/")
def election(session: Session = Depends(db_session)):
    pages = _member_pages(session)
    contests = []
    for key, (body, label) in candidates.CONTESTS.items():
        m = _VOTE_FOR.search(label.lower())
        contests.append({
            "key": key,
            "name": candidates.CONTEST_NAME[key],
            "label": label,
            "vote_for": _NUMBERS.get(m.group(1)) if m else None,
            "election_date": (d.isoformat() if (d := candidates.election_date(key)) else None),
            "seats_up": terms.TERMS[body].seats_up,
            "candidates": [{
                "ballot_name": c.ballot_name,
                "incumbent": c.incumbent,
                "member": pages.get(c.ballot_name),
                "sources": [_source(s) for s in c.sources],
                "not_found": list(c.not_found),
            } for c in candidates.in_contest(key)],
            "race_sources": [_source(s) for s in candidates.RACE_SOURCES.get(key, ())],
            # the questionnaire most candidates answered first
            "questionnaires": [_questionnaire(q) for q in sorted(
                (q for q in questionnaires.QUESTIONNAIRES if q.contest == key),
                key=lambda q: -len(q.responses))],
        })
    return {
        "ballot_url": terms._BALLOT,
        "checked": candidates.CHECKED.isoformat(),
        "voting": _source(candidates.VOTING),
        "contests": contests,
    }
