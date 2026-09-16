"""The public bodies CouncilHound tracks, in one place.

Every layer that used to hardcode "city_council | planning_commission"
(scraper scope, roster seeding, subscription validation, email labels, the
front end's chips and dots) reads from here instead, so adding a body is a
registry entry plus whatever body-specific parsing it needs.

Keys are the values stored in meetings.body / upcoming_meetings.body and
used in API query strings and URLs, so they are stable identifiers: rename
the label, never the key.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Body:
    key: str
    label: str            # "School Board"
    short: str            # "school board" — for "Follow school board meetings"
    archive_section: str  # the <h3> this body's rows sit under on ViewPublisher
    # Granicus streams video/audio for some bodies only; the rest publish an
    # agenda and minutes (often PDFs) with no recording. Documentation only —
    # the pipeline discovers this per row from the presence of an MP3 link.
    recorded: bool = True


BODIES: dict[str, Body] = {b.key: b for b in (
    Body("city_council", "City Council", "council", "City Council Meetings"),
    # Planning Commission rows share a section with BAR/BZA; the scraper
    # filters that section on the row title.
    Body("planning_commission", "Planning Commission", "commission",
         "Community Development and Planning Meetings"),
    Body("school_board", "School Board", "school board", "School Board Meetings"),
    Body("prab", "Parks and Recreation Advisory Board", "parks board",
         "Park and Recreation Advisory Board Meetings", recorded=False),
    Body("hhcab", "Housing and Healthy Communities Advisory Board", "housing board",
         "Housing and Healthy Communities Advisory Board Meetings", recorded=False),
)}

BODY_KEYS: tuple[str, ...] = tuple(BODIES)
BODY_LABELS: dict[str, str] = {k: b.label for k, b in BODIES.items()}


def label(key: str | None) -> str:
    """Display name for a body key; unknown keys fall through unchanged."""
    if not key:
        return ""
    body = BODIES.get(key)
    return body.label if body else key


# The jurisdiction itself, and the bodies (tracked or not) that sit on its
# Granicus archive. None of these is a topic: a meeting that "discusses the
# City of Fairfax" or gets a "Planning Commission update" is talking about
# the actors, and letting them through as entities put "City of Fairfax" at
# the top of the School Board hot-topics ranking (2026-09-16).
JURISDICTION_NAMES: tuple[str, ...] = (
    "City of Fairfax", "Fairfax City", "Fairfax", "Fairfax, Virginia", "Fairfax County",
)
OTHER_BODY_NAMES: tuple[str, ...] = (
    "PRAB", "HHCAB", "Board of Architectural Review", "BAR", "Board of Zoning Appeals", "BZA",
    "Board of Equalization", "Commission for Women", "Commission on the Arts", "Electoral Board",
    "Environmental Sustainability Committee", "Fairfax Village in the City Advisory Board",
    "Human Services Committee", "Retirement Plan Administrative Committee",
)
_BODY_NAMES = frozenset(n.lower() for n in (*OTHER_BODY_NAMES, *(b.label for b in BODIES.values())))
_JURISDICTION = frozenset(n.lower() for n in JURISDICTION_NAMES)
_PREFIXES = ("city of fairfax ", "fairfax city ", "fairfax ")


def is_self_reference(name: str | None) -> bool:
    """Is this entity name the jurisdiction or one of its own bodies?
    Case-insensitive; tolerates a leading article and a jurisdiction prefix
    ("the City of Fairfax School Board", "Fairfax City Council")."""
    if not name:
        return False
    n = " ".join(name.lower().split()).strip(" .,;:")
    if n.startswith("the "):
        n = n[4:]
    if n in _JURISDICTION or n in _BODY_NAMES:
        return True
    for prefix in _PREFIXES:
        if n.startswith(prefix) and n[len(prefix):] in _BODY_NAMES:
            return True
    return False
