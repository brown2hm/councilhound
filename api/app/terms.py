"""When a member's seat is next decided: the body's pinned term schedule
(jurisdictions/<slug>.yaml bodies[].terms) read for one person, with any
per-seat override. Shared by the members routes and /ask so both state
the same dates from the same source."""
import datetime

from councilhound.bodies import REGISTRY
from councilhound.entities import display_name
from councilhound.people import last_name


def _seat(seats, name: str | None):
    """The seat entry for this member: by display name (initials dropped,
    so "Rachel McQuillen" finds "Rachel M. McQuillen"), else by last name
    when only one seat has it (the County PC has two Thomases)."""
    if not name:
        return None
    exact = [s for s in seats if display_name(s.name).lower() == display_name(name).lower()]
    if exact:
        return exact[0]
    by_last = [s for s in seats if last_name(s.name).lower() == last_name(name).lower()]
    return by_last[0] if len(by_last) == 1 else None


def term_for(body_key: str | None, name: str | None,
             today: datetime.date | None = None) -> dict | None:
    """{selection, appointed_by, term_years, term_ends, next_election,
    on_ballot, seats_up, note, source, verified} for this member, or None
    when the body has no pinned schedule."""
    body = REGISTRY.bodies.get(body_key or "")
    terms = body.terms if body else None
    if terms is None:
        return None
    today = today or datetime.date.today()
    seat = _seat(terms.members, name)
    term_ends = (seat.term_ends if seat and seat.term_ends else terms.term_ends)
    next_election = terms.next_election if terms.selection == "elected" else None
    if next_election and next_election < today:
        next_election = None  # the pinned election has passed; the schedule needs re-checking
    return {
        "body": body.key,
        "body_label": body.label,
        "selection": terms.selection,
        "appointed_by": terms.appointed_by,
        "term_years": terms.term_years,
        "staggered": terms.staggered,
        "term_ends": term_ends.isoformat() if term_ends else None,
        "next_election": next_election.isoformat() if next_election else None,
        "on_ballot": seat.on_ballot if seat else None,
        "seats_up": terms.seats_up,
        "note": " ".join(n for n in (terms.note, seat.note if seat else None) if n) or None,
        "source": terms.source,
        "verified": terms.verified.isoformat(),
    }


def body_terms(body_key: str, today: datetime.date | None = None) -> dict | None:
    """The body-wide schedule, with the official candidate list."""
    body = REGISTRY.bodies.get(body_key)
    if body is None or body.terms is None:
        return None
    out = term_for(body_key, None, today)
    out["candidates"] = list(body.terms.candidates)
    out["seats"] = [
        {"name": s.name, "term_ends": s.term_ends.isoformat() if s.term_ends else None,
         "on_ballot": s.on_ballot, "note": s.note}
        for s in body.terms.members
    ]
    return out


def describe(term: dict) -> str:
    """One plain sentence-set for a prompt source."""
    parts = []
    if term["selection"] == "elected":
        parts.append(f"Elected to the {term['body_label']}"
                     + (f" for {term['term_years']}-year terms" if term["term_years"] else "")
                     + (" (staggered)" if term["staggered"] else "") + ".")
    else:
        parts.append(f"Appointed to the {term['body_label']}"
                     + (f" by the {term['appointed_by']}" if term["appointed_by"] else "")
                     + (f" for {term['term_years']}-year terms" if term["term_years"] else "") + ".")
    if term["term_ends"]:
        parts.append(f"Current term ends {term['term_ends']}.")
    if term["next_election"]:
        parts.append(f"Next election: {term['next_election']}"
                     + (f" ({term['seats_up']})" if term["seats_up"] else "") + ".")
    if term["on_ballot"] is True:
        parts.append("On the ballot at that election.")
    elif term["on_ballot"] is False:
        parts.append("Not on the ballot at that election.")
    if term["note"]:
        parts.append(term["note"])
    parts.append(f"(Schedule checked {term['verified']} against {term['source']}.)")
    return " ".join(parts)
