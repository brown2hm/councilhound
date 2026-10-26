"""What the candidates said at the 2026 candidate forums, in their own
words: each forum's video, the moderator's questions as asked, and every
candidate's turn, verbatim and timestamped, so a quote can be played back
at the moment it was said.

The words are an automatic transcript (whisper, with speakers separated by
pyannote and put to names by hand from the emcee's introductions), cut
only at a turn's ends where another voice or a mic check crept in, with
misspelled names and a few misheard words corrected where YouTube's
captions or a second whisper pass disagree with it. The plan behind
each file is in ingestion/forums/; councilhound.extraction.forum builds it.

Turns are quotations to report, never paraphrased into findings. Pinned
like app.candidates, and retired with it after the election."""
import datetime
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app import candidates

_D = datetime.date
_DATA = Path(__file__).parent / "forum_transcripts"

TRANSCRIPT_NOTE = ("Automatic transcript of the video: it can mishear or drop a word, so check a "
                   "quote against the video before relying on its exact wording.")


@dataclass(frozen=True)
class Question:
    id: str
    topic: str
    start: int
    asked: str | None             # the moderator's words, verbatim; None for opening statements


@dataclass(frozen=True)
class Turn:
    speaker: str                  # ballot name, as in app.candidates
    question: str | None          # Question.id
    start: int
    end: int
    parts: tuple[tuple[int, str], ...]  # (start second, verbatim text), about a sentence each

    @property
    def text(self) -> str:
        return " ".join(t for _, t in self.parts)


@dataclass(frozen=True)
class Forum:
    key: str
    title: str
    held_on: datetime.date
    hosts: str
    venue: str
    video: str                    # YouTube watch URL
    posted_by: str
    contests: tuple[str, ...]     # app.candidates.CONTESTS keys
    format: str
    absent: tuple[tuple[str, str], ...] = ()  # (ballot name, what the event said)
    questions: tuple[Question, ...] = ()
    turns: tuple[Turn, ...] = ()

    def link(self, seconds: int) -> str:
        return f"{self.video}&t={max(int(seconds), 0)}s"

    def speakers(self) -> list[str]:
        """Ballot names of everyone who spoke, in ballot order."""
        said = {t.speaker for t in self.turns}
        return [c.ballot_name for c in candidates.CANDIDATES if c.ballot_name in said]

    def question(self, qid: str | None) -> Question | None:
        return next((q for q in self.questions if q.id == qid), None)


def _load(meta: Forum) -> Forum:
    data = json.loads((_DATA / f"{meta.key}.json").read_text())
    qs = tuple(Question(q["id"], q["topic"], q["start"], q.get("asked")) for q in data["questions"])
    ts = tuple(Turn(t["speaker"], t["question"], t["start"], t["end"],
                    tuple((p["start"], p["text"]) for p in t["parts"])) for t in data["turns"])
    return Forum(**{**meta.__dict__, "questions": qs, "turns": ts})


FORUMS: tuple[Forum, ...] = tuple(_load(f) for f in (
    Forum(
        "candidates_night_2026_09_30", "Candidates Night", _D(2026, 9, 30),
        "Central Fairfax Chamber of Commerce and League of Women Voters of the Fairfax Area",
        "Katherine Johnson Middle School",
        "https://www.youtube.com/watch?v=rN5Hu2BLf4w", "Fairfax Public Access",
        ("mayor", "city_council"),
        "Each Mayor and City Council candidate gave a two-minute opening statement, in ballot "
        "order; there were no questions. School Board candidates met voters afterward but did "
        "not speak.",
        absent=(("Stephen S. Kim", "The emcee said Stephen Kim was not able to attend."),),
    ),
    Forum(
        "mayoral_forum_2026_10_07", "Mayoral Candidate Forum", _D(2026, 10, 7),
        "Central Fairfax Chamber of Commerce", "Sherwood Center",
        "https://www.youtube.com/watch?v=OZgATGnljDM", "City of Fairfax",
        ("mayor",),
        "A moderated forum: opening statements, the moderator's questions on growth and "
        "development, the environment, taxes and revenue and community safety, with timed "
        "answers and follow-ups, then closing statements.",
    ),
))


def in_contest(contest: str) -> list[Forum]:
    """The race's own forums first (the mayoral forum before Candidates
    Night on the Mayor tab), then by date."""
    return sorted((f for f in FORUMS if contest in f.contests), key=lambda f: (len(f.contests), f.held_on))


def appearances(ballot_name: str) -> list[tuple[Forum, list[Turn]]]:
    out = []
    for f in FORUMS:
        turns = [t for t in f.turns if t.speaker == ballot_name]
        if turns:
            out.append((f, turns))
    return out


def absences(ballot_name: str) -> list[tuple[Forum, str]]:
    return [(f, note) for f in FORUMS for name, note in f.absent if name == ballot_name]


# ---------------------------------------------------------------- search

PASSAGE_CHARS = 600
_STOP = {"the", "and", "for", "that", "this", "with", "what", "you", "your", "are", "was", "have",
         "about", "they", "their", "from", "would", "will", "said", "say", "does", "did", "how",
         "city", "fairfax", "candidate", "candidates", "think", "she", "her", "his", "him",
         "forum", "debate", "mayor", "council", "who", "our", "them", "there"}


def _stem(w: str) -> str:
    """Enough to match 'taxes' to 'tax' and 'trees' to 'tree'."""
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith(("xes", "ches", "shes", "sses")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOP}


@dataclass(frozen=True)
class Passage:
    forum: Forum
    turn: Turn
    start: int
    text: str


def passages(turn: Turn, forum: Forum) -> list[Passage]:
    """A turn in consecutive windows of whole sentences, each starting at
    its first sentence's second."""
    out, start, buf = [], None, []
    for s, t in turn.parts:
        if start is None:
            start = s
        buf.append(t)
        if sum(len(b) + 1 for b in buf) >= PASSAGE_CHARS:
            out.append(Passage(forum, turn, start, " ".join(buf)))
            start, buf = None, []
    if buf:
        out.append(Passage(forum, turn, start, " ".join(buf)))
    return out
