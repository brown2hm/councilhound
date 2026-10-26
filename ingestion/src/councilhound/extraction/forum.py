"""
Candidate forums posted on YouTube, as verbatim, timestamped turns for the
API's pinned forum files (api/app/forum_transcripts/<key>.json).

A one-off local job per forum, outside the meetings pipeline:

  forum-transcribe URL raw.json   download the audio (yt-dlp), whisper + pyannote
  forum-runs raw.json             print the speaker runs, to write the plan
  forum-build raw.json plan.json out.json

The plan is written by hand from watching the video: which diarization label
is which candidate (the emcee calls each by name), where each moderator
question starts, and any words the diarizer gave the wrong speaker (a
moderator's "Kirsten, two minutes" at the head of her answer) or whisper
invented in a pause. Those are cut by exact text from a turn's ends, so what
remains is contiguous; the only edits inside a turn are listed fixes for
names whisper misspelled, and for words where YouTube's captions or a second
whisper pass agree against it ("for votes" -> "Four votes"). Mic checks can
be dropped whole. Nothing a candidate said is reworded.
"""
import json
import logging
import os
import subprocess
import tempfile

from councilhound.extraction import diarize, transcript

log = logging.getLogger(__name__)

MODERATOR = "moderator"
MIN_TURN_SECONDS = 15  # "Thank you." and mic checks are not turns


def download_audio(url: str, out_dir: str) -> str:
    """Best audio track of a YouTube video as m4a. Needs a current yt-dlp
    and a JS runtime (YouTube returns 403 to older builds)."""
    cmd = [os.environ.get("YT_DLP", "yt-dlp"), "--js-runtimes", "node", "-f", "bestaudio",
           "-x", "--audio-format", "m4a", "-o", os.path.join(out_dir, "%(id)s.%(ext)s"),
           "--print", "after_move:filepath", url]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1]


def transcribe_video(url: str) -> dict:
    """{'segments', 'turns'}: whisper segments with word times, and the
    pyannote speaker turns, for one video."""
    with tempfile.TemporaryDirectory() as tmp:
        path = download_audio(url, tmp)
        return {"url": url, "segments": transcript.transcribe_audio(path, hallucination_silence=None),
                "turns": diarize.diarize(path)}


def speaker_runs(raw: dict) -> list[dict]:
    """Consecutive words of one diarization label, as one run; its parts
    are whisper's segments (about a sentence each), with their start times."""
    runs: list[dict] = []
    for p in transcript.assign_speakers(raw["segments"], raw["turns"]):
        part = {"start": p["start"], "text": p["text"]}
        if runs and runs[-1]["label"] == p["speaker"]:
            runs[-1]["end"] = p["end"]
            runs[-1]["text"] += " " + p["text"]
            runs[-1]["parts"].append(part)
        else:
            runs.append({"start": p["start"], "end": p["end"], "label": p["speaker"],
                         "text": p["text"], "parts": [part]})
    return runs


def _cut(parts: list[dict], prefix: str | None, suffix: str | None) -> list[dict]:
    """The parts with an exact leading and trailing piece of their joined
    text removed (whole parts dropped, a split part keeps its start)."""
    text = " ".join(p["text"] for p in parts)
    if prefix and not text.startswith(prefix):
        raise ValueError(f"turn does not start with {prefix!r}: {text[:80]!r}")
    if suffix and not text.endswith(suffix):
        raise ValueError(f"turn does not end with {suffix!r}: {text[-80:]!r}")
    lo, hi = len(prefix or ""), len(text) - len(suffix or "")
    out, pos = [], 0
    for p in parts:
        a, b = pos, pos + len(p["text"])
        pos = b + 1
        piece = p["text"][max(lo, a) - a:max(min(hi, b) - a, 0)].strip()
        if piece and b > lo and a < hi:
            out.append({"start": p["start"], "text": piece})
    return out


def _fix(parts: list[dict], fixes: list[dict]) -> list[dict]:
    """Words whisper misheard, corrected from a second source (names, numbers): each fix
    replaces every occurrence in the turn, and must find one."""
    for f in fixes:
        hits = [p for p in parts if f["from"] in p["text"]]
        if not hits:
            raise ValueError(f"fix {f['from']!r} matches 0 parts")
        for p in hits:
            p["text"] = p["text"].replace(f["from"], f["to"])
    return parts


def build(raw: dict, plan: dict) -> dict:
    """The forum file: the moderator's questions as asked, and each
    candidate's turns in order with the question they answer."""
    speakers = plan["speakers"]          # label -> ballot name | 'moderator' | 'host'
    cuts = {int(k): v for k, v in plan.get("cuts", {}).items()}  # run start (s) -> {prefix, suffix}
    drop = set(plan.get("drop", []))  # run starts that are mic checks, not turns
    runs = speaker_runs(raw)
    for r in runs:
        r["speaker"] = speakers.get(r["label"])
        r["key"] = int(r["start"])

    questions = []
    for q in plan["questions"]:
        asked = None
        if q.get("asked_at") is not None:
            hit = [r for r in runs if r["key"] == q["asked_at"]]
            if not hit or hit[0]["speaker"] != MODERATOR:
                raise ValueError(f"no moderator run starts at {q['asked_at']}s")
            c = cuts.get(q["asked_at"], {})
            asked = " ".join(p["text"] for p in _cut(hit[0]["parts"], c.get("prefix"), c.get("suffix")))
        questions.append({"id": q["id"], "topic": q["topic"], "start": q["start"], "asked": asked})

    turns = []
    for r in runs:
        if (r["speaker"] in (None, MODERATOR, "host") or r["end"] - r["start"] < MIN_TURN_SECONDS
                or r["key"] in drop):
            continue
        c = cuts.get(r["key"], {})
        parts = _fix(_cut(r["parts"], c.get("prefix"), c.get("suffix")), c.get("fixes", []))
        open_q = [q for q in questions if q["start"] <= r["start"]]
        turns.append({"start": int(r["start"]), "end": int(r["end"] + 0.999), "speaker": r["speaker"],
                      "question": open_q[-1]["id"] if open_q else None,
                      "parts": [{"start": int(p["start"]), "text": p["text"]} for p in parts]})
    used = (set(cuts) | drop) - {q.get("asked_at") for q in plan["questions"]}
    missing = used - {r["key"] for r in runs}
    if missing:
        raise ValueError(f"cuts name runs that do not exist: {sorted(missing)}")
    return {"key": plan["key"], "url": raw.get("url"), "questions": questions, "turns": turns}


def write(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
