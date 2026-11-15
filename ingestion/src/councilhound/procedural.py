"""
Procedural topics: agenda furniture the extractor tracks as a topic because
it recurs at nearly every meeting (closed-session personnel matters, the
remote-attendance motion, the minutes), but which is never the news. They
keep their pages and stay searchable; they are left out of rankings and
feeds, where sheer recurrence would otherwise put them first ("Personnel
Matters" was the most active topic in the directory, Nov 2026).

One pattern, written without \\b so the same string works in Python and in
Postgres (`~*`).
"""
import re

_EDGE_L = r"(^|[^a-z])"
_EDGE_R = r"($|[^a-z])"

PROCEDURAL_TOPIC_PATTERN = _EDGE_L + (
    r"(personnel matters?"
    r"|closed (session|meeting)"
    r"|remote participation"
    r"|electronic participation"
    r"|(approval|adoption) of (the )?(minutes|agenda)"
    r"|minutes"
    r"|consent agenda"
    r"|roll call"
    r"|call to order"
    r"|pledge of allegiance"
    r"|adjournment)"
) + _EDGE_R

_PROCEDURAL_TOPIC = re.compile(PROCEDURAL_TOPIC_PATTERN, re.I)

# An update that says nothing happened cannot be what moved a status: the
# structuring pass sometimes files a topic under the consent item with the
# status it reached later in the same meeting.
_NO_ACTION = re.compile(r"^\s*(\[[^\]]*\]\s*)?no (formal |specific )?action (specific|was taken|taken)", re.I)


def is_procedural_topic(name: str | None) -> bool:
    return bool(name) and _PROCEDURAL_TOPIC.search(name) is not None


def says_no_action(update_text: str | None) -> bool:
    return bool(update_text) and _NO_ACTION.search(update_text) is not None
