"""When a member's seat is next decided: each body's term schedule, pinned
from official sources like every other jurisdiction fact, read for one
person with any per-seat override. Shared by the members routes and /ask
so both state the same dates from the same source.

(The multi-jurisdiction branch keeps these in bodies[].terms of the
jurisdiction YAML; until it merges, the City's schedules live here.)"""
import datetime
from dataclasses import dataclass, field

from councilhound.bodies import BODIES
from councilhound.entities import display_name
from councilhound.people import last_name

_D = datetime.date
_BALLOT = ("https://www.fairfaxva.gov/files/assets/city/v/1/elections/documents/"
           "sample-ballots/sample-ballot-nov2026-full.pdf")


@dataclass(frozen=True)
class TermSeat:
    name: str
    term_ends: datetime.date | None = None
    on_ballot: bool | None = None      # running at Terms.next_election
    note: str | None = None


@dataclass(frozen=True)
class Terms:
    selection: str                     # 'elected' | 'appointed'
    source: str                        # URL the schedule was read from
    verified: datetime.date            # when it was last checked
    appointed_by: str | None = None
    term_years: int | None = None
    staggered: bool = False
    term_ends: datetime.date | None = None   # when every seat's term ends together
    next_election: datetime.date | None = None
    seats_up: str | None = None
    # official ballot for next_election: (contest as printed, candidates)
    candidates: tuple[tuple[str, tuple[str, ...]], ...] = ()
    members: tuple[TermSeat, ...] = field(default_factory=tuple)
    note: str | None = None


TERMS: dict[str, Terms] = {
    # Charter §3.1: Mayor and all six at-large seats elected together every
    # two years at the November general election, terms from January 1.
    # Candidates as printed on the City's official sample ballot.
    "city_council": Terms(
        selection="elected", term_years=2, term_ends=_D(2026, 12, 31),
        next_election=_D(2026, 11, 3), seats_up="Mayor and all six council seats",
        candidates=(
            ("Mayor (vote for one)", ("Kirsten Sides Lockhart", 'Thomas D. "Tom" Peterson')),
            ("City Council (vote for not more than six)", (
                "Stacy R. Hall", "Rachel M McQuillen", "Anthony T. Amos", "Sandi W. Slappey Brown",
                "Kelly M. O'Brien", "Russell A. Jones", "Stephen S. Kim", "Susan Hartley Kuiler",
                "María José Padmore", "Steve S Chang", "Jessica L. Lough")),
        ),
        members=(
            TermSeat("Catherine S. Read", on_ballot=False, note="Not seeking a third term as Mayor."),
            TermSeat("Billy M. Bates", on_ballot=False, note="Not seeking reelection."),
            TermSeat("Stacey D. Hardy-Chandler", on_ballot=False, note="Not seeking reelection."),
            TermSeat("Thomas D. Peterson", on_ballot=True,
                     note="Running for Mayor rather than reelection to Council."),
            TermSeat("Stacy R. Hall", on_ballot=True, note="Running for reelection to Council."),
            TermSeat("Rachel M. McQuillen", on_ballot=True, note="Running for reelection to Council."),
            TermSeat("Anthony T. Amos", on_ballot=True, note="Running for reelection to Council."),
        ),
        source="https://www.fairfaxva.gov/Government/Council/Mayor-and-Council-Members",
        verified=_D(2026, 10, 3),
    ),
    # seven seats appointed by Council to staggered four-year terms;
    # expirations from the City's boards and commissions roster
    "planning_commission": Terms(
        selection="appointed", appointed_by="City Council", term_years=4, staggered=True,
        members=(
            TermSeat("James E. Feather", _D(2027, 4, 9)),
            TermSeat("Kirsten S. Lockhart", _D(2029, 12, 21),
                     note="Also a candidate for Mayor on November 3 2026."),
            TermSeat("Tassos G. McCarthy", _D(2026, 12, 31)),
            TermSeat("Paul Cunningham", _D(2027, 12, 31)),
            TermSeat("Matthew T. Rice", _D(2028, 2, 11)),
            TermSeat("Daniel F. Drummond", _D(2028, 4, 9), note="Appointed September 22 2026."),
        ),
        note="One of the seven seats was vacant when checked.",
        source="https://fairfax.granicus.com/boards/w/85f2b8dc41dad80d/boards/17650",
        verified=_D(2026, 10, 3),
    ),
    # all five seats on the November 3 2026 ballot ("vote for not more than
    # five"); term length not yet pinned
    "school_board": Terms(
        selection="elected", next_election=_D(2026, 11, 3), seats_up="all five School Board seats",
        candidates=(("School Board (vote for not more than five)", (
            "Carolyn S. Pitches", "Amit Sarah Hickman", "Kristina M. Cecere",
            "Sarah M. Kelsey", "Lauren A. Bartelme")),),
        source=_BALLOT, verified=_D(2026, 10, 3),
    ),
}


def _seat(seats, name: str | None):
    """The seat entry for this member: by display name (initials dropped,
    so "Rachel McQuillen" finds "Rachel M. McQuillen"), else by last name
    when only one seat has it."""
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
    terms = TERMS.get(body_key or "")
    body = BODIES.get(body_key or "")
    if terms is None or body is None:
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
    terms = TERMS.get(body_key)
    if terms is None or body_key not in BODIES:
        return None
    out = term_for(body_key, None, today)
    out["candidates"] = [{"contest": contest, "names": list(names)}
                         for contest, names in terms.candidates]
    out["seats"] = [
        {"name": s.name, "term_ends": s.term_ends.isoformat() if s.term_ends else None,
         "on_ballot": s.on_ballot, "note": s.note}
        for s in terms.members
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
