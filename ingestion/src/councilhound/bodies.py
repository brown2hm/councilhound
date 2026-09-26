"""The public bodies CouncilHound tracks, in one place — read from the
jurisdiction config (councilhound.jurisdiction), never hard-coded.

Every layer that used to hardcode "city_council | planning_commission"
(scraper scope, roster seeding, subscription validation, email labels, the
front end's chips and dots) reads from here instead, so adding a body is a
config entry plus whatever body-specific parsing it needs.

Keys are the values stored in meetings.body / upcoming_meetings.body and
used in API query strings and URLs, so they are stable identifiers: rename
the label, never the key.

Module globals (BODIES, BODY_KEYS, BODY_LABELS, label, is_self_reference)
are the process's jurisdiction; tests build a Registry from any config.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from councilhound.jurisdiction import JurisdictionConfig, Roster, current


@dataclass(frozen=True)
class Body:
    key: str
    label: str            # "School Board"
    short: str            # "school board" — for "Follow school board meetings"
    # the <h3> this body's rows sit under on a sections-layout ViewPublisher;
    # None for a body that owns a whole view (layout: single)
    archive_section: str | None = None
    # Granicus streams video/audio for some bodies only; the rest publish an
    # agenda and minutes (often PDFs) with no recording. Documentation only —
    # the pipeline discovers this per row from the presence of an MP3 link.
    recorded: bool = True
    # rows in a shared section belong to this body only if the title has one
    title_must_contain: tuple[str, ...] = ()
    # ordered (lowercased substring -> meeting_type); first match wins
    meeting_types: tuple[tuple[str, str], ...] = ()
    default_meeting_type: str = ""
    upcoming_starts_with: tuple[str, ...] = ()
    upcoming_contains: tuple[str, ...] = ()
    upcoming_default_for_view: str | None = None
    color: int = 0                  # palette index for the front end
    hot: bool = False               # gets a hot-topics panel
    recommends: bool = False        # advisory: outcomes are recommendations
    agenda_has_outcomes: bool = False   # the agenda doc carries official outcomes
    agenda_url_template: str | None = None   # strftime template when rows link no agenda
    roster: Roster | None = field(default=None, compare=False, hash=False)

    def seed_titles(self, role_key: str) -> list[str]:
        """Title aliases seeded for a person in this role: the role's own
        forms plus those of the roles it `also` holds (a chair is a
        commissioner)."""
        if not self.roster or role_key not in self.roster.roles:
            return []
        role = self.roster.roles[role_key]
        titles = list(role.aliases)
        for other in role.also:
            titles += [t for t in self.roster.roles[other].aliases if t not in titles]
        return titles


def _body_from_config(b) -> Body:
    return Body(
        key=b.key, label=b.label, short=b.short,
        archive_section=b.archive_section, recorded=b.recorded,
        title_must_contain=tuple(s.lower() for s in b.title_must_contain),
        meeting_types=tuple((r.contains.lower(), r.type) for r in b.meeting_types),
        default_meeting_type=b.default_meeting_type or f"{b.key}_meeting",
        upcoming_starts_with=tuple(s.lower() for s in b.upcoming.starts_with),
        upcoming_contains=tuple(s.lower() for s in b.upcoming.contains),
        upcoming_default_for_view=b.upcoming.default_for_view,
        color=b.color if b.color is not None else 0,
        hot=b.hot, recommends=b.recommends, agenda_has_outcomes=b.agenda_has_outcomes,
        agenda_url_template=b.agenda_url_template, roster=b.roster,
    )


def _norm(name: str) -> str:
    n = " ".join(name.lower().split()).strip(" .,;:")
    return n[4:] if n.startswith("the ") else n


class Registry:
    """The tracked bodies of one jurisdiction plus its self-reference stoplist."""

    def __init__(self, bodies: list[Body], self_names: tuple[str, ...] = (),
                 self_prefixes: tuple[str, ...] = (), other_body_names: tuple[str, ...] = ()):
        self.bodies: dict[str, Body] = {b.key: b for b in bodies}
        self.keys: tuple[str, ...] = tuple(self.bodies)
        self.labels: dict[str, str] = {k: b.label for k, b in self.bodies.items()}
        self.self_names = tuple(self_names)
        self.other_body_names = tuple(other_body_names)
        self._body_names = frozenset(
            n.lower() for n in (*other_body_names, *(b.label for b in bodies)))
        self._jurisdiction = frozenset(_norm(n) for n in self_names)
        self._prefixes = tuple(p.lower() for p in self_prefixes)

    @classmethod
    def from_config(cls, cfg: JurisdictionConfig) -> "Registry":
        return cls([_body_from_config(b) for b in cfg.bodies],
                   self_names=tuple(cfg.identity.self_names),
                   self_prefixes=tuple(cfg.identity.self_prefixes),
                   other_body_names=tuple(cfg.identity.other_body_names))

    def label(self, key: str | None) -> str:
        """Display name for a body key; unknown keys fall through unchanged."""
        if not key:
            return ""
        body = self.bodies.get(key)
        return body.label if body else key

    def is_self_reference(self, name: str | None) -> bool:
        """Is this entity name the jurisdiction or one of its own bodies?
        Case-insensitive; tolerates a leading article and a jurisdiction
        prefix ("the City of Fairfax School Board", "Fairfax City Council").
        None of these is a topic: a meeting that "discusses the City of
        Fairfax" or gets a "Planning Commission update" is talking about the
        actors, and letting them through as entities put "City of Fairfax" at
        the top of the School Board hot-topics ranking (2026-09-16)."""
        if not name:
            return False
        n = _norm(name)
        if n in self._jurisdiction or n in self._body_names:
            return True
        for prefix in self._prefixes:
            if n.startswith(prefix) and n[len(prefix):] in self._body_names:
                return True
        return False

    def title_prefixes(self) -> tuple[str, ...]:
        """Lowercased 'title ' prefixes of every roster alias, longest first —
        an alias that starts with one is a title alias ("Mayor Read")."""
        prefixes = {a.lower() + " " for b in self.bodies.values() if b.roster
                    for role in b.roster.roles.values() for a in role.aliases}
        return tuple(sorted(prefixes, key=lambda p: (-len(p), p)))

    def title_roles(self) -> list[tuple[str, str, str]]:
        """(prefix, role title, body key) for every roster alias, longest
        prefix first so a body-qualified title ("school board chair ") wins
        over the bare one ("chair ")."""
        rows = []
        for b in self.bodies.values():
            if not b.roster:
                continue
            for role in b.roster.roles.values():
                for alias in role.aliases:
                    rows.append((alias.lower() + " ", role.title, b.key))
        rows.sort(key=lambda r: (-len(r[0]), r[0]))
        return rows

    def role_order(self) -> dict[str, int]:
        """Display rank of each role title: body order, then role order."""
        order: dict[str, int] = {}
        for b in self.bodies.values():
            if not b.roster:
                continue
            for role in b.roster.roles.values():
                order.setdefault(role.title, len(order))
        return order


REGISTRY = Registry.from_config(current())

BODIES: dict[str, Body] = REGISTRY.bodies
BODY_KEYS: tuple[str, ...] = REGISTRY.keys
BODY_LABELS: dict[str, str] = REGISTRY.labels
JURISDICTION_NAMES: tuple[str, ...] = REGISTRY.self_names
OTHER_BODY_NAMES: tuple[str, ...] = REGISTRY.other_body_names


def label(key: str | None) -> str:
    return REGISTRY.label(key)


def is_self_reference(name: str | None) -> bool:
    return REGISTRY.is_self_reference(name)
