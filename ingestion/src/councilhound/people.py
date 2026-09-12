"""Member-name helpers shared by the API's members router and the notifier.
Vote breakdowns key members by the last name the minutes use ("Read":
"yes"), so both sides need the same reduction from a full name."""

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def last_name(name: str) -> str:
    tokens = [t for t in name.replace(",", " ").split()
              if t.lower().rstrip(".") not in _SUFFIXES]
    return tokens[-1] if tokens else ""


def vote_cast_by(breakdown: dict | None, name: str) -> str | None:
    """The member's recorded vote in a breakdown, matched on last name."""
    key = last_name(name).lower()
    for member, vote in (breakdown or {}).items():
        if member.lower() == key:
            return vote
    return None
