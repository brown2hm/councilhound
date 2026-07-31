"""Parcel-identifier normalization, shared by every PIN comparison.

A Fairfax tax map id reaches us in three incompatible spellings: documents
write "57-4-02-076", the GeoHub parcel layer stores "57 4 02    076" (padded
groups), and WebPro pads differently again. Comparing any two of those
requires collapsing to one canonical form, and the *only* safe canonical
form drops the separators entirely rather than normalizing whitespace.

This module exists because that was previously done twice, differently:
the parcel resolver collapsed whitespace only (so a hyphenated PIN matched
nothing and resolution silently fell through to a one-parcel address
geocode), while the extractor's quote firewall normalized on alnum. Every
comparison now goes through norm_pin.

Import discipline: stdlib only — the resolver, the WebPro client, and the
extractor all import it.
"""
from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[^0-9a-zA-Z]+")
# suffix letters are written attached in documents ("013C") but the GIS layer
# may store them detached ("013 C") — split every digit<->letter boundary so
# both spellings canonicalize identically
_ALNUM_BOUNDARY = re.compile(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)")


def norm_pin(pin: str) -> str:
    """Canonical PIN: alphanumeric groups joined by single spaces, uppercased,
    with letter suffixes split into their own group.

    >>> norm_pin("57-4-02-076")
    '57 4 02 076'
    >>> norm_pin("57 4 02    076") == norm_pin("57-4-02-076")
    True
    >>> norm_pin("58-3-02-013C") == norm_pin("58 3 02    013 C")
    True
    """
    spaced = _SEPARATORS.sub(" ", str(pin))
    return _ALNUM_BOUNDARY.sub(" ", spaced).strip().upper()


def pins_match(a: str, b: str) -> bool:
    return norm_pin(a) == norm_pin(b)


# Tax-map-shaped tokens as documents write them: three or four groups, the
# first two short, an optional trailing letter (condo/split suffix). Used to
# recover stated PINs from a document corpus; callers MUST filter hits
# against the parcel layer, since this also matches phone-ish digit runs.
PIN_TOKEN = re.compile(
    r"\b\d{2,3}[-\s]+\d{1,2}[-\s]+\d{1,2}(?:[-\s]+\d{1,3}[A-Z]?)?\b")


def candidate_pins(text: str) -> list[str]:
    """Normalized PIN-shaped tokens found in `text`, de-duplicated in order."""
    seen: dict[str, None] = {}
    for match in PIN_TOKEN.finditer(text):
        seen.setdefault(norm_pin(match.group(0)), None)
    return list(seen)
