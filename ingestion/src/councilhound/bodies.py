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
