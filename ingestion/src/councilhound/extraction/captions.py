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


def parse_vtt(text: str) -> list[dict]:
    """[{'start', 'end', 'text'}] per cue, in file order. Speaker-change
    markers ('>>') become sentence breaks; positioning tags and cue
    identifiers are dropped. Empty or non-VTT input yields []."""
    if not text or "-->" not in text:
        return []
    cues: list[dict] = []
    current: dict | None = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        m = _CUE.match(line)
        if m:
            if current and current["text"]:
                cues.append(current)
            start, end = _seconds(m.group("start")), _seconds(m.group("end"))
            current = ({"start": start, "end": end, "text": ""}
                       if start is not None and end is not None else None)
            continue
        if not line:
            if current and current["text"]:
                cues.append(current)
            current = None
            continue
        if current is None:
            continue  # header, NOTE blocks, cue identifiers
        piece = _TAG.sub("", line).replace(">>", " ").strip()
        if piece:
            current["text"] = (current["text"] + " " + piece).strip()
    if current and current["text"]:
        cues.append(current)
    return cues


def is_real_captions(text: str, min_cues: int = 20) -> bool:
    """A tenant may serve an empty or placeholder VTT; only a file with a
    meaningful number of cues counts as a transcript source."""
    return len(parse_vtt(text)) >= min_cues
