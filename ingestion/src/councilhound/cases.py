"""Case numbers in extracted entity names.

Agendas name land-use cases in compound forms the extractor copies
verbatim, and a verbatim compound never matches the official record of any
one case:

  "RZ-2017-HM-020 (RZPA-2025-HM-00031)"   a case plus its umbrella application
  "PCA-84-L-020-29/CDPA-84-L-020-10"      two cases heard together
  "PCA/CDPA-2018-HM-020"                  shorthand for PCA-2018-HM-020 + CDPA-2018-HM-020
  "SE 2025-FR-00037"                      a space where the record has a hyphen

`split_case_name` turns such a name into the cases it lists (written the
way the official record writes them, PREFIX-BODY) and the umbrella
application numbers in it (`parent_prefixes`, the County's RZPA). It
returns None for anything that is not purely a list of case numbers —
"SSPA 2023-I-1A Gallows Road Annandale Planning District" is a plan, not a
case list, and is left alone.

Per jurisdiction: extraction.case_numbers in the YAML switches it on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# PREFIX, then a body that starts with digits and runs through hyphenated
# segments: 2017-HM-020, 84-L-020-29, 86-C-121-14-02, 2025-FR-00035
_BODY = r"\d{2,4}(?:-[A-Z0-9]{1,6})+"
_SINGLE = re.compile(rf"\b([A-Z]{{1,5}})[\s-]*({_BODY})\b")
# PCA/CDPA-2018-HM-020, RZ/FDP 2025-DR-00021: several prefixes, one body
_SHORTHAND = re.compile(rf"\b((?:[A-Z]{{1,5}}/)+[A-Z]{{1,5}})[\s-]*({_BODY})\b")
# what may sit between case numbers in a pure list
_GLUE = re.compile(r"^(?:[\s/,&;.:]|\band\b|\bcon\b|\bw\b|\bwith\b|\bconcurrent(?:ly)?\b)*$",
                   re.IGNORECASE)


@dataclass
class CaseRef:
    primaries: list[str] = field(default_factory=list)  # the cases, in order
    parents: list[str] = field(default_factory=list)    # umbrella applications


def _canonical(prefix: str, body: str) -> str:
    return f"{prefix.upper()}-{body.upper()}"


def _scan(text: str) -> tuple[list[str], str]:
    """Case numbers in `text`, in order, and the text with them removed."""
    found: list[tuple[int, str]] = []
    rest = text
    for m in _SHORTHAND.finditer(text):
        for i, prefix in enumerate(m.group(1).split("/")):
            found.append((m.start() + i, _canonical(prefix, m.group(2))))
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    for m in _SINGLE.finditer(rest):
        found.append((m.start(), _canonical(m.group(1), m.group(2))))
    found.sort()
    stripped = _SINGLE.sub(" ", rest)
    return [c for _pos, c in found], stripped


def split_case_name(name: str | None, parent_prefixes: list[str] | tuple[str, ...] = ()) -> CaseRef | None:
    """The cases (and umbrella applications) a name lists, or None when the
    name is not purely a list of case numbers."""
    if not name:
        return None
    text = re.sub(r"\s*-\s*", "-", name.strip())  # "2025- DR-00046" -> "2025-DR-00046"
    # agenda titles get cut mid-parenthesis ("... (RZPA-2025-DR-00049")
    text += ")" * max(0, text.count("(") - text.count(")"))
    outside = re.sub(r"\([^)]*\)", " ", text)
    inside = " ".join(re.findall(r"\(([^)]*)\)", text))
    out_cases, out_rest = _scan(outside)
    in_cases, in_rest = _scan(inside)
    if not out_cases and not in_cases:
        return None
    if not _GLUE.match(out_rest) or not _GLUE.match(in_rest):
        return None  # words other than list glue: a named thing, not a case list
    parents_set = {p.upper() for p in parent_prefixes}
    ref = CaseRef()
    for case in out_cases + in_cases:
        bucket = ref.parents if case.split("-", 1)[0] in parents_set else ref.primaries
        if case not in bucket:
            bucket.append(case)
    return ref


def case_parent_pairs(text: str | None, parent_prefixes: list[str] | tuple[str, ...]) -> list[tuple[list[str], str]]:
    """(cases, umbrella) for each umbrella application printed in running
    text right after the cases it covers:

      "Public Hearing on PCA-2023-PR-00010 (RZPA-2026-PR-00013) (Tri Pointe ...)"
        -> [(["PCA-2023-PR-00010"], "RZPA-2026-PR-00013")]
      "... (Concurrent with PCA-85-C-008-04 (RZPA-2025-DR-00087))"
        -> [(["PCA-85-C-008-04"], "RZPA-2025-DR-00087")]

    Agenda item titles carry these pairs even when the extractor names the
    umbrella number on its own."""
    if not text or not parent_prefixes:
        return []
    text = re.sub(r"\s*-\s*", "-", text)
    prefixes = "|".join(re.escape(p.upper()) for p in parent_prefixes)
    pairs = []
    for m in re.finditer(rf"\(\s*(?:{prefixes})[\s-]*({_BODY})\s*\)", text):
        parent = _canonical(m.group(0).strip("() ").split("-", 1)[0].strip(), m.group(1))
        before = text[:m.start()]
        # the case numbers in the run of list glue that ends at this "("
        tokens = [(t.start(), t.end(), t) for t in _SHORTHAND.finditer(before)]
        covered = [(a, b) for a, b, _t in tokens]
        for t in _SINGLE.finditer(before):
            if not any(a <= t.start() < b for a, b in covered):
                tokens.append((t.start(), t.end(), t))
        tokens.sort(key=lambda x: x[0])
        run, cursor = [], len(before)
        for start, end, t in reversed(tokens):
            if not _GLUE.match(before[end:cursor]):
                break
            if t.re is _SHORTHAND:
                run[:0] = [_canonical(pfx, t.group(2)) for pfx in t.group(1).split("/")]
            else:
                run.insert(0, _canonical(t.group(1), t.group(2)))
            cursor = start
        if run:
            pairs.append((run, parent))
    return pairs
