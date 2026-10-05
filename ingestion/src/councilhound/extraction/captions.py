"""WebVTT captions as a transcript source.

Some Granicus tenants publish real captions (the County's clips carry
English closed captions; the City's caption endpoint 404s), served at
/videos/<clip_id>/captions.vtt. Cues are short (a line or two, a second or
two each), so they are merged into the same ~700-char chunks whisper
segments would be, with the covered time span, and land in
transcript_chunks like any transcript."""
from __future__ import annotations

import re

_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d{1,3})|(\d\d):(\d\d)[.,](\d{1,3})")
_CUE = re.compile(r"^\s*(?P<start>[\d:.,]+)\s*-->\s*(?P<end>[\d:.,]+)")
_TAG = re.compile(r"<[^>]+>")


def _seconds(stamp: str) -> float | None:
    m = _TIME.match(stamp.strip())
    if not m:
        return None
    if m.group(1) is not None:
        h, mi, s, ms = m.group(1), m.group(2), m.group(3), m.group(4)
    else:
        h, mi, s, ms = "0", m.group(5), m.group(6), m.group(7)
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


TURN_PREFIX = "TURN_"
_MARK = ">>"


def turn_label(n: int) -> str:
    return f"{TURN_PREFIX}{n:04d}"


def parse_vtt(text: str) -> list[dict]:
    """[{'start', 'end', 'text', 'speaker'}] per cue, in file order.

    Captioners mark each change of speaker with '>>'. Each marker starts a
    new turn, labelled TURN_0001, TURN_0002, ... (text before the first
    marker is TURN_0000). A turn is one uninterrupted stretch of speech,
    not one person: the same person speaks under many turn labels. A
    marker in the middle of a cue splits it, the time divided in proportion
    to the text on either side. A file with no markers gives speaker None
    throughout. Positioning tags and cue identifiers are dropped; empty or
    non-VTT input yields []."""
    if not text or "-->" not in text:
        return []
    raw_cues: list[dict] = []
    current: dict | None = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        m = _CUE.match(line)
        if m:
            if current and current["text"]:
                raw_cues.append(current)
            start, end = _seconds(m.group("start")), _seconds(m.group("end"))
            current = ({"start": start, "end": end, "text": ""}
                       if start is not None and end is not None else None)
            continue
        if not line:
            if current and current["text"]:
                raw_cues.append(current)
            current = None
            continue
        if current is None:
            continue  # header, NOTE blocks, cue identifiers
        piece = _TAG.sub("", line).strip()
        if piece:
            current["text"] = (current["text"] + " " + piece).strip()
    if current and current["text"]:
        raw_cues.append(current)

    marked = any(_MARK in c["text"] for c in raw_cues)
    cues: list[dict] = []
    turn = 0
    for c in raw_cues:
        parts = c["text"].split(_MARK)
        total = sum(len(p.strip()) for p in parts) or 1
        t, span = c["start"], max(0.0, c["end"] - c["start"])
        for i, part in enumerate(parts):
            if i > 0:
                turn += 1  # every marker is a change of speaker
            piece = part.strip()
            if not piece:
                continue
            dur = span * len(piece) / total
            cues.append({"start": round(t, 3), "end": round(t + dur, 3), "text": piece,
                         "speaker": turn_label(turn) if marked else None})
            t += dur
    return cues


def is_real_captions(text: str, min_cues: int = 20) -> bool:
    """A tenant may serve an empty or placeholder VTT; only a file with a
    meaningful number of cues counts as a transcript source."""
    return len(parse_vtt(text)) >= min_cues
