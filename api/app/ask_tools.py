"""The knowledge /ask can reach, as tools Claude calls: the meeting record
(transcripts, agenda items with their roll calls, documents), the tracked
topic records built from it (profiles, timelines, wiki pages, official
project data, impact analyses), and the members (voting records, how they
line up with each other, and when their seats are next decided).

Every tool result is a list of numbered sources drawn from one registry
per question, so the [n] the model cites is the same [n] across tool calls
and the citation list is built only from what the model was actually
shown."""
import datetime
import re
from collections import Counter

from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from zoneinfo import ZoneInfo

from councilhound.bodies import BODIES, label as body_label
from councilhound.db.models import (
    AgendaItem, CityProject, Document, Entity, EntityAlias, EntityMention, EntityProfile,
    EntityUpdate, Meeting, ProjectEvaluation, TranscriptChunk, UpcomingMeeting, Vote, WikiPage,
)
from councilhound.embeddings.embed import embed_query

from app import terms
from app.links import clip_link
from app.routers import members as members_router
from app.routers.search import SEMANTIC_MAX_DISTANCE
from app.wiki import generated_at, trust_block

SEARCH_LIMIT = 10
TIMELINE_LIMIT = 25
TOPIC_VOTE_LIMIT = 15
MEMBER_VOTE_LIMIT = 12
SPLIT_LIMIT = 12
WIKI_PAGE_CHARS = 3500
REPORT_CHARS = 3000
AGENDA_CHARS = 2500
DOC_SNIPPET_CHARS = 800
# pipeline placeholder labels ("SPEAKER_01") name no one
LOCAL_TZ = ZoneInfo("America/New_York")
_ANON_SPEAKER = re.compile(r"^speaker[_ ]?\d+$", re.I)


def _clip(text: str | None, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


def _today() -> datetime.date:
    return datetime.datetime.now(LOCAL_TZ).date()


class Sources:
    """The numbered sources for one question. Adding the same record twice
    returns its existing number."""

    def __init__(self):
        self.items: list[dict] = []
        self._by_key: dict[tuple, int] = {}

    def add(self, key: tuple, *, kind: str, title: str, text: str,
            date: str | None = None, link: str | None = None, **meta) -> int:
        if key in self._by_key:
            return self._by_key[key]
        self.items.append({"kind": kind, "title": title, "text": text,
                           "date": date, "link": link, **meta})
        n = len(self.items)
        self._by_key[key] = n
        return n

    def get(self, n: int) -> dict | None:
        return self.items[n - 1] if 1 <= n <= len(self.items) else None

    def block(self, n: int) -> str:
        s = self.items[n - 1]
        return f"[{n}] ({s['kind']}, {s['date'] or 'undated'}, {s['title']})\n{s['text']}"


def _render(sources: Sources, numbers: list[int], header: str = "") -> str:
    seen, out = set(), []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            out.append(sources.block(n))
    if not out:
        return (header + "\n\n" if header else "") + "No matching sources."
    return (header + "\n\n" if header else "") + "\n\n".join(out)


def _body_label(key: str | None) -> str:
    return body_label(key) if key else ""


def _parse_date(value) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _topic_link(entity: Entity, official_slug: str | None) -> str:
    return f"/development/{official_slug}" if official_slug else f"/topics/{entity.canonical_slug}"


# ---------------------------------------------------------------- votes

def _tally_text(breakdown: dict | None) -> str:
    bd = breakdown or {}
    counts = Counter(bd.values())
    tally = f"{counts.get('yes', 0)}-{counts.get('no', 0)}"
    named = {cast: sorted(n for n, c in bd.items() if c == cast)
             for cast in ("no", "abstain", "absent")}
    extra = "; ".join(f"{cast}: {', '.join(names)}" for cast, names in named.items() if names)
    yes = ", ".join(sorted(n for n, c in bd.items() if c == "yes"))
    return f"{tally}" + (f" (yes: {yes}" + (f"; {extra}" if extra else "") + ")" if bd else "")


def _add_vote(sources: Sources, vote: Vote, meeting: Meeting, item: AgendaItem | None) -> int:
    subject = vote.description or (item.title if item else "") or "motion"
    where = f"{meeting.title}" + (f", item {item.label}" if item else "")
    text = (f"Roll call on {subject!r}" + (f" under agenda item {item.label} {item.title!r}" if item else "")
            + f": {vote.motion_result or 'result not recorded'}, {_tally_text(vote.vote_breakdown)}.")
    link = (clip_link(meeting.granicus_view_id, meeting.granicus_clip_id, item.start_seconds)
            if item and item.start_seconds is not None else None) \
        or meeting.minutes_url or f"/meetings/{meeting.id}"
    return sources.add(("vote", vote.id), kind="vote", title=f"{_body_label(meeting.body)}: {where}",
                       text=text, date=meeting.meeting_date.isoformat(), link=link,
                       meeting_id=meeting.id, agenda_item_id=item.id if item else None,
                       agenda_item_label=item.label if item else None)


def _votes_by_item(session: Session, item_ids: set[int]) -> dict[int, list[Vote]]:
    if not item_ids:
        return {}
    out: dict[int, list[Vote]] = {}
    for v in session.scalars(select(Vote).where(Vote.agenda_item_id.in_(item_ids)).order_by(Vote.id)):
        out.setdefault(v.agenda_item_id, []).append(v)
    return out


# ---------------------------------------------------------------- record search

def _add_chunk(sources: Sources, chunk: TranscriptChunk, meeting: Meeting,
               speaker: str | None) -> int:
    who = speaker if speaker and not _ANON_SPEAKER.match(speaker) else None
    text = (f"{who}: " if who else "") + chunk.text
    start = float(chunk.start_seconds) if chunk.start_seconds is not None else None
    return sources.add(("chunk", chunk.id), kind="transcript",
                       title=f"{_body_label(meeting.body)}: {meeting.title}",
                       text=text, date=meeting.meeting_date.isoformat(),
                       link=clip_link(meeting.granicus_view_id, meeting.granicus_clip_id, start or 0),
                       meeting_id=meeting.id, start_seconds=start)


def _add_item(sources: Sources, item: AgendaItem, meeting: Meeting, votes: list[Vote]) -> int:
    parts = [p for p in (item.title, item.description, f"Outcome: {item.outcome}" if item.outcome else None) if p]
    for v in votes:
        parts.append(f"Roll call ({v.description or 'motion'}): {v.motion_result or 'unrecorded'}, "
                     f"{_tally_text(v.vote_breakdown)}")
    link = (clip_link(meeting.granicus_view_id, meeting.granicus_clip_id, item.start_seconds)
            if item.start_seconds is not None else None) or meeting.minutes_url or meeting.agenda_url
    return sources.add(("item", item.id), kind="agenda_item",
                       title=f"{_body_label(meeting.body)}: {meeting.title}, item {item.label}",
                       text=". ".join(parts), date=meeting.meeting_date.isoformat(), link=link,
                       meeting_id=meeting.id, agenda_item_id=item.id, agenda_item_label=item.label)


def _record_filters(q, body: str | None, since, until):
    if body:
        q = q.where(Meeting.body == body)
    if since:
        q = q.where(Meeting.meeting_date >= since)
    if until:
        q = q.where(Meeting.meeting_date <= until)
    return q


def search_record(session: Session, sources: Sources, query: str, body: str | None = None,
                  since: str | None = None, until: str | None = None,
                  limit: int = SEARCH_LIMIT) -> list[int]:
    """Exact-phrase hits (newest first) then semantic neighbours within the
    distance the search page trusts, over transcripts and agenda items."""
    needle = (query or "").strip().lower()
    if not needle:
        return []
    since_d, until_d = _parse_date(since), _parse_date(until)
    if body and body not in BODIES:
        body = None
    hits: list[tuple] = []  # (kind, row, meeting, speaker)

    iq = (select(AgendaItem, Meeting).join(Meeting, AgendaItem.meeting_id == Meeting.id)
          .where(func.lower(func.coalesce(AgendaItem.title, "") + " "
                            + func.coalesce(AgendaItem.description, "") + " "
                            + func.coalesce(AgendaItem.outcome, "")).contains(needle, autoescape=True))
          .order_by(Meeting.meeting_date.desc()).limit(limit))
    for item, meeting in session.execute(_record_filters(iq, body, since_d, until_d)):
        hits.append(("item", item, meeting, None))
    cq = (select(TranscriptChunk, Meeting, Entity.name)
          .join(Meeting, TranscriptChunk.meeting_id == Meeting.id)
          .outerjoin(Entity, TranscriptChunk.speaker_entity_id == Entity.id)
          .where(func.lower(TranscriptChunk.text).contains(needle, autoescape=True))
          .order_by(Meeting.meeting_date.desc()).limit(limit))
    for chunk, meeting, speaker in session.execute(_record_filters(cq, body, since_d, until_d)):
        hits.append(("chunk", chunk, meeting, speaker or chunk.speaker_label))
    keyword = hits[: max(4, limit // 2)]

    vec = embed_query(query)
    semantic: list[tuple] = []
    sq = (select(TranscriptChunk, Meeting, Entity.name,
                 TranscriptChunk.embedding.cosine_distance(vec).label("d"))
          .join(Meeting, TranscriptChunk.meeting_id == Meeting.id)
          .outerjoin(Entity, TranscriptChunk.speaker_entity_id == Entity.id)
          .where(TranscriptChunk.embedding.isnot(None)).order_by("d").limit(limit))
    for chunk, meeting, speaker, d in session.execute(_record_filters(sq, body, since_d, until_d)):
        if float(d) <= SEMANTIC_MAX_DISTANCE:
            semantic.append((float(d), ("chunk", chunk, meeting, speaker or chunk.speaker_label)))
    aq = (select(AgendaItem, Meeting, AgendaItem.embedding.cosine_distance(vec).label("d"))
          .join(Meeting, AgendaItem.meeting_id == Meeting.id)
          .where(AgendaItem.embedding.isnot(None)).order_by("d").limit(limit))
    for item, meeting, d in session.execute(_record_filters(aq, body, since_d, until_d)):
        if float(d) <= SEMANTIC_MAX_DISTANCE:
            semantic.append((float(d), ("item", item, meeting, None)))
    semantic.sort(key=lambda t: t[0])

    chosen, seen = [], set()
    for h in keyword + [h for _, h in semantic]:
        key = (h[0], h[1].id)
        if key not in seen:
            seen.add(key)
            chosen.append(h)
        if len(chosen) == limit:
            break
    votes = _votes_by_item(session, {h[1].id for h in chosen if h[0] == "item"})
    out = []
    for kind, row, meeting, speaker in chosen:
        if kind == "item":
            out.append(_add_item(sources, row, meeting, votes.get(row.id, [])))
        else:
            out.append(_add_chunk(sources, row, meeting, speaker))
    return out


def search_documents(session: Session, sources: Sources, query: str,
                     body: str | None = None, limit: int = 5) -> list[int]:
    """Staff reports, minutes and packets: exact-phrase hits with the text
    around the first match."""
    needle = (query or "").strip().lower()
    if len(needle) < 3:
        return []
    q = (select(Document, Meeting).join(Meeting, Document.meeting_id == Meeting.id)
         .where(Document.raw_text.isnot(None),
                func.lower(Document.raw_text).contains(needle, autoescape=True))
         .order_by(Meeting.meeting_date.desc()).limit(limit))
    if body and body in BODIES:
        q = q.where(Meeting.body == body)
    out = []
    for doc, meeting in session.execute(q):
        text = doc.raw_text or ""
        at = text.lower().find(needle)
        lo = max(0, at - DOC_SNIPPET_CHARS // 2)
        snippet = ("… " if lo else "") + _clip(text[lo:lo + DOC_SNIPPET_CHARS], DOC_SNIPPET_CHARS)
        out.append(sources.add(
            ("doc", doc.id), kind="document",
            title=f"{_body_label(meeting.body)}: {doc.title or doc.doc_type.replace('_', ' ')} ({meeting.title})",
            text=re.sub(r"\s+", " ", snippet), date=meeting.meeting_date.isoformat(),
            link=doc.source_url, meeting_id=meeting.id))
    return out


# ---------------------------------------------------------------- topics

def _update_counts_subquery():
    return (select(EntityUpdate.entity_id, func.count().label("n"))
            .group_by(EntityUpdate.entity_id).subquery())


def match_topics(session: Session, name: str, limit: int = 5) -> list[Entity]:
    needle = (name or "").strip().lower()
    if len(needle) < 2:
        return []
    uc = _update_counts_subquery()
    rows = session.execute(
        select(Entity, func.coalesce(uc.c.n, 0))
        .outerjoin(uc, Entity.id == uc.c.entity_id)
        .where(Entity.entity_type != "person",
               or_(func.lower(Entity.name).contains(needle, autoescape=True),
                   Entity.canonical_slug == needle.replace(" ", "-"),
                   exists(select(EntityAlias.id).where(
                       EntityAlias.entity_id == Entity.id,
                       func.lower(EntityAlias.alias).contains(needle, autoescape=True)))))
        .order_by(func.coalesce(uc.c.n, 0).desc(), Entity.name)
        .limit(limit)
    ).all()
    # an exact name match beats a busier record that merely contains it
    rows.sort(key=lambda r: (r[0].name.lower() != needle, -r[1]))
    return [e for e, _n in rows]


def get_topic(session: Session, sources: Sources, name: str) -> tuple[list[int], str, int | None]:
    """(source numbers, header, entity id) for the best-matching tracked
    record: its synthesized profile, wiki pages, dated timeline, official
    project data, impact analysis, and the roll calls on its agenda items."""
    matches = match_topics(session, name)
    if not matches:
        return [], f"No tracked topic matches {name!r}.", None
    e = matches[0]
    others = [m.name for m in matches[1:]]
    cp = session.scalar(select(CityProject).where(CityProject.entity_id == e.id))
    official = cp.external_slug if cp else None
    link = _topic_link(e, official)
    header = (f"Topic: {e.name} ({e.entity_type}); current status: {e.current_status or 'unknown'}."
              + (f" Other records with similar names: {', '.join(others)}." if others else ""))
    out: list[int] = []

    profile = session.scalar(select(EntityProfile).where(EntityProfile.entity_id == e.id))
    if profile and (profile.summary or profile.open_questions or profile.member_commentary):
        through = session.get(Meeting, profile.through_meeting_id) if profile.through_meeting_id else None
        parts = [profile.summary or ""]
        if profile.open_questions:
            parts.append("Open questions: " + " | ".join(profile.open_questions))
        if profile.member_commentary:
            parts.append("Member positions: " + " | ".join(
                f"{c.get('member')}: {c.get('summary')}" for c in profile.member_commentary))
        out.append(sources.add(
            ("profile", e.id), kind="profile", title=f"{e.name}: summary of the record",
            text="\n".join(p for p in parts if p),
            date=through.meeting_date.isoformat() if through else None, link=link, entity_id=e.id))

    pages = session.scalars(select(WikiPage).where(
        WikiPage.entity_id == e.id, WikiPage.kind == "concept")).all()
    order = {"overview": 0, "history": 1, "positions": 2, "impact": 3}
    for page in sorted(pages, key=lambda p: order.get(p.page, 9)):
        if page.page not in order:
            continue
        trust = trust_block(page.frontmatter)
        flags = [trust["tier"]] + (["stale"] if trust["stale"] else [])
        title = (page.frontmatter or {}).get("title") or page.page.capitalize()
        out.append(sources.add(
            ("wiki", page.id), kind="wiki", title=f"{e.name} wiki: {title} ({', '.join(flags)})",
            text=_clip(page.body, WIKI_PAGE_CHARS),
            date=(generated_at(page.frontmatter) or "")[:10] or None,
            link=f"{link}#{page.page}" if official else link, entity_id=e.id))

    if cp:
        timeline = "; ".join(
            f"{t.get('date') or ''} {t.get('label') or t.get('event') or t.get('status') or ''}".strip()
            for t in (cp.official_timeline or []) if isinstance(t, dict))
        facts = [f"Official status: {cp.official_status}" if cp.official_status else None,
                 f"Type: {cp.project_type}" if cp.project_type else None,
                 f"Address: {cp.address}" if cp.address else None,
                 f"Applicant: {cp.applicant}" if cp.applicant else None,
                 f"Requests: {cp.requests}" if cp.requests else None,
                 f"Description: {_clip(cp.description, 1200)}" if cp.description else None,
                 f"Staff planner: {cp.planner_name}" if cp.planner_name else None,
                 f"Official timeline: {timeline}" if timeline else None]
        out.append(sources.add(
            ("project", cp.id), kind="project", title=f"{cp.name}: official project record",
            text="\n".join(f for f in facts if f),
            date=cp.synced_at.date().isoformat() if cp.synced_at else None,
            link=cp.detail_url, entity_id=e.id))
        ev = session.scalar(select(ProjectEvaluation).where(
            ProjectEvaluation.city_project_id == cp.id, ProjectEvaluation.report_markdown.isnot(None)))
        if ev:
            out.append(sources.add(
                ("impact", ev.id), kind="impact", title=f"{cp.name}: impact analysis (modelled estimates)",
                text=_clip(ev.report_markdown, REPORT_CHARS),
                date=(ev.synthesized_at or ev.updated_at).date().isoformat() if (ev.synthesized_at or ev.updated_at) else None,
                link=f"/development/{cp.external_slug}", entity_id=e.id))

    updates = session.execute(
        select(EntityUpdate, Meeting, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id == e.id)
        .order_by(Meeting.meeting_date, EntityUpdate.id)
    ).all()
    # the first appearance and the most recent run, in date order
    shown = updates if len(updates) <= TIMELINE_LIMIT else updates[:1] + updates[-(TIMELINE_LIMIT - 1):]
    for u, meeting, item in shown:
        out.append(sources.add(
            ("update", u.id), kind="timeline",
            title=f"{e.name} at {_body_label(meeting.body)}: {meeting.title}"
                  + (f", item {item.label}" if item else ""),
            text=u.update_text + (f" (status after: {u.status_after})" if u.status_after else ""),
            date=meeting.meeting_date.isoformat(),
            link=(clip_link(meeting.granicus_view_id, meeting.granicus_clip_id, item.start_seconds)
                  if item and item.start_seconds is not None else None) or f"/meetings/{meeting.id}",
            meeting_id=meeting.id, agenda_item_id=item.id if item else None,
            agenda_item_label=item.label if item else None, entity_id=e.id))
    if len(updates) > len(shown):
        header += f" Timeline: {len(updates)} entries; the first and the latest {TIMELINE_LIMIT - 1} are shown."

    item_ids = {u.agenda_item_id for u, _, _ in updates if u.agenda_item_id}
    item_ids |= set(session.scalars(select(EntityMention.agenda_item_id).where(
        EntityMention.entity_id == e.id, EntityMention.agenda_item_id.isnot(None))))
    if item_ids:
        vote_rows = session.execute(
            select(Vote, Meeting, AgendaItem)
            .join(Meeting, Vote.meeting_id == Meeting.id)
            .join(AgendaItem, Vote.agenda_item_id == AgendaItem.id)
            .where(Vote.agenda_item_id.in_(item_ids))
            .order_by(Meeting.meeting_date.desc(), Vote.id.desc())
            .limit(TOPIC_VOTE_LIMIT)
        ).all()
        for v, meeting, item in reversed(vote_rows):
            out.append(_add_vote(sources, v, meeting, item))
    return out, header, e.id


# ---------------------------------------------------------------- members

def _roster_people(session: Session) -> list[dict]:
    """Everyone with a title alias, with their body and whether they sit now."""
    current = members_router._current_slugs(session)
    out = []
    for m in members_router._roster(session).values():
        roles = members_router._sorted_roles(m["roles"])
        out.append({"entity": m["entity"], "roles": roles,
                    "body": members_router._body_for(roles, Counter()),
                    "is_current": m["entity"].canonical_slug in current})
    return out


def match_member(session: Session, name: str) -> tuple[dict | None, list[str]]:
    """The roster person a name refers to (full name, alias, or last name),
    preferring sitting members; plus the other candidates when ambiguous."""
    needle = re.sub(r"^(mayor|councilmember|council member|commissioner|chair(man)?|vice[- ]chair|"
                    r"supervisor|school board (member|chair))\s+", "", (name or "").strip().lower())
    if not needle:
        return None, []
    people = _roster_people(session)
    aliases: dict[int, list[str]] = {}
    for eid, alias in session.execute(select(EntityAlias.entity_id, EntityAlias.alias).where(
            EntityAlias.entity_id.in_([p["entity"].id for p in people]))):
        aliases.setdefault(eid, []).append(alias.lower())

    def score(p) -> int:
        e = p["entity"]
        full = e.name.lower()
        last = members_router.last_name(e.name).lower()
        if needle in (full, e.canonical_slug):
            return 3
        if needle == last or any(a.endswith(" " + needle) for a in aliases.get(e.id, [])):
            return 2
        if needle in full or any(needle in a for a in aliases.get(e.id, [])):
            return 1
        return 0

    scored = sorted(((score(p), p["is_current"], p) for p in people if score(p)),
                    key=lambda t: (-t[0], not t[1], t[2]["entity"].name))
    if not scored:
        scored = _fallback_by_last_name(people, needle)
    if not scored:
        return None, []
    best = scored[0]
    others = [p["entity"].name for s, cur, p in scored[1:] if s == best[0]]
    return best[2], others


def _fallback_by_last_name(people: list[dict], needle: str) -> list[tuple]:
    """For a nickname or a misspelt first name ("Tom Peterson", "Kristen
    Lockhart"): match the last word as the last name; when several people
    share it, keep those whose first name starts with the same letter."""
    words = needle.replace(",", " ").split()
    if not words:
        return []
    last = words[-1]
    hits = [p for p in people if members_router.last_name(p["entity"].name).lower() == last]
    if len(hits) > 1 and len(words) > 1:
        initial = [p for p in hits if p["entity"].name.lower().startswith(words[0][0])]
        hits = initial or hits
    return sorted(((1, p["is_current"], p) for p in hits),
                  key=lambda t: (not t[1], t[2]["entity"].name))


def _member_term(person: dict) -> dict | None:
    return terms.term_for(person["body"], person["entity"].name, _today())


def _add_term(sources: Sources, person: dict, term: dict | None) -> int | None:
    if term is None:
        return None
    e = person["entity"]
    return sources.add(("term", e.id), kind="term", title=f"{e.name}: seat and term",
                       text=f"{e.name} ({', '.join(person['roles'])}). {terms.describe(term)}",
                       date=term["verified"], link=term["source"], entity_id=e.id)


def _member_detail(session: Session, person: dict) -> dict | None:
    try:
        return members_router.get_member(person["entity"].canonical_slug, session)
    except HTTPException:
        return None


def _member_summary_text(person: dict, d: dict) -> str:
    r = d["record"]
    vs = d["vote_stats"]
    lines = [
        f"{d['name']}: {', '.join(d['roles']) or 'member'} of the {_body_label(d['body'])}"
        + ("" if d["is_current"] else " (former member)") + ".",
        f"Roll calls in the indexed record: {r['votes']} across {r['meetings']} meetings "
        f"({r['first_vote']} to {r['last_vote']}); yes {vs.get('yes', 0)}, no {vs.get('no', 0)}, "
        f"abstain {vs.get('abstain', 0)}, absent {vs.get('absent', 0)}.",
        f"Contested votes (at least one no): {r['contested']}; on the losing side {r['minority']['total']} times "
        f"({r['minority']['no_on_passed']} no votes on motions that passed, "
        f"{r['minority']['yes_on_failed']} yes votes on motions that failed); lone no vote {r['lone_no']} times; "
        f"voted with the outcome {r['with_outcome_pct']}% of decided votes."
        if r["votes"] else "No roll calls for this member in the indexed record.",
    ]
    if not r["comparisons"] and r["votes"]:
        lines.append(f"Note: fewer than {members_router.MIN_CONTESTED_FOR_COMPARISONS} contested votes, "
                     "so alignment figures rest on a small sample.")
    cats = [c for c in d["categories"] if c["no"] or c["votes"] >= 3][:8]
    if cats:
        lines.append("By kind of item (votes / no votes): "
                     + "; ".join(f"{c['label']} {c['votes']}/{c['no']}" for c in cats) + ".")
    if d["colleagues"]:
        lines.append("Agreement with sitting colleagues on contested votes: " + "; ".join(
            f"{c['name']} {c['agree_pct']}% of {c['agree_n']}" for c in d["colleagues"] if c["agree_pct"] is not None) + ".")
    if d["matters"]:
        lines.append("Matters voted on most: " + "; ".join(
            f"{m['name']} ({m['n']} votes: " + ", ".join(f"{k} {v}" for k, v in m["votes"].items()) + ")"
            for m in d["matters"][:8]) + ".")
    if d["record"]["absent_meetings"]:
        lines.append(f"Absent for every roll call at {len(d['record']['absent_meetings'])} meetings.")
    lines += _tendency_lines(d)
    return "\n".join(lines)


# land-use actions: what a Planning Commission recommends on and a Council decides
_LAND_USE = re.compile(
    r"rezon|special (exception|use)|\bgdp\b|general development plan|site plan|subdivision|"
    r"certificate of appropriateness|zoning map|comprehensive plan amendment|"
    r"recommend (approval|denial)|\bvariance\b", re.I)
_DENIAL = re.compile(r"\bden(y|ial)\b", re.I)


def _against_application(v: dict) -> bool | None:
    """Did this cast oppose the application? A no on an approval motion, or
    a yes on a denial motion; None when the cast took no side."""
    if v["vote"] not in ("yes", "no"):
        return None
    denial = bool(_DENIAL.search(v["description"] or ""))
    return (v["vote"] == "no") != denial


def _tendency_lines(d: dict) -> list[str]:
    """Rates that mean the same thing whichever body the member sits on,
    so a commissioner and a councilmember can be set side by side: how
    often they opposed a land-use application, how often they were on the
    losing side, and how often they missed a roll call. Each carries its
    count, and the advisory nature of a recommending body is stated."""
    votes = d["votes"]
    if not votes:
        return []
    out = []
    land = [v for v in votes if _LAND_USE.search(f"{v['item_title'] or ''} {v['description'] or ''}")]
    sided = [v for v in land if _against_application(v) is not None]
    if sided:
        against = sum(_against_application(v) for v in sided)
        out.append(f"Land-use applications (rezonings, special exceptions, site plans and the like): "
                   f"opposed {against} of {len(sided)} roll calls where they took a side"
                   + (" (as recommendations; the Planning Commission advises and Council decides)"
                      if d["body"] == "planning_commission" else "") + ".")
    cast = [v for v in votes if v["vote"] in ("yes", "no")]
    if cast:
        losing = sum(v["in_minority"] for v in cast)
        out.append(f"On the losing side of {losing} of {len(cast)} yes/no votes "
                   f"({round(100 * losing / len(cast))}%); {sum(v['contested'] for v in votes)} of "
                   f"{len(votes)} roll calls they sat for had at least one no vote.")
    absent = sum(v["vote"] == "absent" for v in votes)
    out.append(f"Absent for {absent} of {len(votes)} roll calls ({round(100 * absent / len(votes))}%).")
    return out


def _add_member_record(sources: Sources, person: dict, d: dict) -> int:
    return sources.add(("member", person["entity"].id), kind="member",
                       title=f"{d['name']}: voting record (from roll calls in the minutes)",
                       text=_member_summary_text(person, d), date=d["record"]["last_vote"],
                       link=f"/members/{d['slug']}", entity_id=person["entity"].id)


def _vote_rows_for(session: Session, d: dict, limit: int, only=None) -> list[tuple]:
    """(Vote, Meeting, AgendaItem) for the member-detail vote dicts chosen."""
    picked = [v for v in d["votes"] if only is None or only(v)][:limit]
    if not picked:
        return []
    keys = {(v["meeting_id"], v["item_label"], v["description"]) for v in picked}
    rows = session.execute(
        select(Vote, Meeting, AgendaItem)
        .join(Meeting, Vote.meeting_id == Meeting.id)
        .outerjoin(AgendaItem, Vote.agenda_item_id == AgendaItem.id)
        .where(Vote.meeting_id.in_({k[0] for k in keys}))
        .order_by(Meeting.meeting_date.desc(), Vote.id.desc())
    ).all()
    return [(v, m, i) for v, m, i in rows
            if (m.id, i.label if i else None, v.description) in keys][:limit]


def get_member(session: Session, sources: Sources, name: str) -> tuple[list[int], str, int | None]:
    person, others = match_member(session, name)
    if person is None:
        return [], f"No current or former member matches {name!r}.", None
    header = f"Member: {person['entity'].name}." + (
        f" Other people matching {name!r}: {', '.join(others)}." if others else "")
    out: list[int] = []
    d = _member_detail(session, person)
    term = _member_term(person)
    if d:
        out.append(_add_member_record(sources, person, d))
    t = _add_term(sources, person, term)
    if t:
        out.append(t)
    elif person["body"]:
        header += f" No term or election schedule is on file for the {_body_label(person['body'])}."
    if d:
        for c in d["commentary"][:8]:
            out.append(sources.add(
                ("commentary", person["entity"].id, c["topic_slug"]), kind="commentary",
                title=f"{d['name']} on {c['topic_name']}", text=c["summary"],
                link=f"/topics/{c['topic_slug']}"))
        # the votes that say most: losing-side and contested ones, newest first
        for v, m, i in _vote_rows_for(session, d, MEMBER_VOTE_LIMIT, lambda v: v["contested"]):
            out.append(_add_vote(sources, v, m, i))
    return out, header, person["entity"].id


SHARED_TOPIC_LIMIT = 10
_INSTRUMENTS = ("ordinance", "resolution")


def _acts_by_topic(d: dict) -> dict[str, dict]:
    """slug -> {name, slug, votes, said} for every topic a member voted on
    or spoke to, from their member record."""
    acts: dict[str, dict] = {}
    for v in d["votes"]:
        for t in v["topics"]:
            if t["entity_type"] in _INSTRUMENTS:
                continue
            acts.setdefault(t["slug"], {"name": t["name"], "slug": t["slug"], "votes": [], "said": None})["votes"].append(v)
    for c in d["commentary"]:
        acts.setdefault(c["topic_slug"], {"name": c["topic_name"], "slug": c["topic_slug"], "votes": [], "said": None})["said"] = c["summary"]
    return acts


def _act_lines(name: str, body: str | None, act: dict | None) -> list[str]:
    if act is None:
        return [f"{name}: no recorded vote or remark."]
    lines = []
    for v in sorted(act["votes"], key=lambda v: v["date"])[:4]:
        t = v["tally"]
        lines.append(f"{name} ({_body_label(v['body'])}, {v['date']}"
                     + (f", item {v['item_label']}" if v["item_label"] else "") + f"): voted {v['vote']} on "
                     f"{(v['description'] or v['item_title'] or 'the motion')!r}; "
                     f"{v['motion_result'] or 'result not recorded'} {t.get('yes', 0)}-{t.get('no', 0)}.")
    if len(act["votes"]) > 4:
        lines.append(f"{name}: {len(act['votes']) - 4} more roll calls on this topic.")
    if act["said"]:
        lines.append(f"{name}, from the topic's summary of the record: {act['said']}")
    return lines


def _shared_topics(sources: Sources, a: dict, da: dict, b: dict, db: dict) -> tuple[list[int], str]:
    """Members who never cast a vote together can still be compared where
    the same matter passed through both of them: a land-use case the
    Planning Commission recommends on and Council then decides, a plan both
    bodies review. One source per matter (topics naming the same agenda
    items are merged), each member's votes and stated position in date
    order; plus the matters only one of them acted on."""
    acts_a, acts_b = _acts_by_topic(da), _acts_by_topic(db)
    shared = set(acts_a) & set(acts_b)

    def item_keys(act):
        return frozenset((v["meeting_id"], v["item_label"]) for v in act["votes"])

    # topics that name overlapping agenda items on both sides are one matter
    # ("Accessory Dwelling Units" and "Detached Accessory Dwelling Units")
    merged: list[dict] = []
    for slug in sorted(shared):
        ka, kb = item_keys(acts_a[slug]), item_keys(acts_b[slug])
        home = next((g for g in merged if ka and kb and g["ka"] & ka and g["kb"] & kb), None)
        if home is None:
            merged.append({"ka": set(ka), "kb": set(kb), "slugs": [slug]})
        else:
            home["ka"] |= ka
            home["kb"] |= kb
            home["slugs"].append(slug)
    groups = {i: g["slugs"] for i, g in enumerate(merged)}

    def rank(slugs):
        x, y = acts_a[slugs[0]], acts_b[slugs[0]]
        both_said = bool(x["said"]) and bool(y["said"])
        both_voted = bool(x["votes"]) and bool(y["votes"])
        latest = max([v["date"] for v in x["votes"] + y["votes"]] or [""])
        return (not both_said, not both_voted, -(len(x["votes"]) + len(y["votes"])), latest)

    an, bn = a["entity"].name, b["entity"].name
    out = []
    for slugs in sorted(groups.values(), key=rank)[:SHARED_TOPIC_LIMIT]:
        slugs.sort(key=lambda s_: -(len(acts_a[s_]["votes"]) + len(acts_b[s_]["votes"])))
        lead = slugs[0]
        label = " / ".join(acts_a[s_]["name"] for s_ in slugs)
        lines = [f"Matter: {label}."]
        lines += _act_lines(an, a["body"], acts_a[lead])
        lines += _act_lines(bn, b["body"], acts_b[lead])
        dates = [v["date"] for v in acts_a[lead]["votes"] + acts_b[lead]["votes"]]
        out.append(sources.add(
            ("shared", a["entity"].id, b["entity"].id, lead), kind="shared_topic",
            title=f"{an} and {bn} on {label}", text="\n".join(lines),
            date=max(dates) if dates else None, link=f"/topics/{lead}"))

    def only(acts, other):
        rows = sorted((x for k, x in acts.items() if k not in other),
                      key=lambda x: -(len(x["votes"]) + (2 if x["said"] else 0)))[:8]
        return ", ".join(f"{x['name']} ({len(x['votes'])} votes{', remarks' if x['said'] else ''})" for x in rows)

    summary = (f"{an} and {bn} both acted on {len(groups)} matter(s) in the indexed record."
               + (f" Only {an}: {only(acts_a, acts_b)}." if set(acts_a) - shared else "")
               + (f" Only {bn}: {only(acts_b, acts_a)}." if set(acts_b) - shared else ""))
    return out, summary


def compare_members(session: Session, sources: Sources, names: list[str]) -> tuple[list[int], str]:
    people, notes = [], []
    for name in names[:6]:
        p, others = match_member(session, name)
        if p is None:
            notes.append(f"No member matches {name!r}.")
        elif p["entity"].id not in {q["entity"].id for q in people}:
            people.append(p)
            if others:
                notes.append(f"{name!r} also matches {', '.join(others)}; using {p['entity'].name}.")
    if len(people) < 2:
        return [], " ".join(notes + ["Need at least two members to compare."])

    out: list[int] = []
    details = {}
    for p in people:
        d = _member_detail(session, p)
        details[p["entity"].id] = d
        if d:
            out.append(_add_member_record(sources, p, d))
        t = _add_term(sources, p, _member_term(p))
        if t:
            out.append(t)
        elif p["body"]:
            notes.append(f"No term or election schedule is on file for the {_body_label(p['body'])}.")

    # head to head: every roll call both cast yes/no on, contested or not;
    # members on different bodies are compared on the matters both touched
    lines = []
    shared_out: list[int] = []
    split_keys: set[tuple] = set()
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            da, keys_b = details[a["entity"].id], members_router._cast_keys(b["entity"].name)
            if not da:
                continue
            both = agree = c_both = c_agree = 0
            for v in da["votes"]:
                theirs = members_router._cast_for(v["breakdown"], keys_b)
                if v["vote"] not in ("yes", "no") or theirs not in ("yes", "no"):
                    continue
                both += 1
                agree += theirs == v["vote"]
                if v["contested"]:
                    c_both += 1
                    c_agree += theirs == v["vote"]
                    if theirs != v["vote"]:
                        split_keys.add((v["meeting_id"], v["item_label"], v["description"]))
            an, bn = a["entity"].name, b["entity"].name
            db_ = details[b["entity"].id]
            if a["body"] != b["body"] and db_:
                nums, summary = _shared_topics(sources, a, da, b, db_)
                shared_out.extend(nums)
                lines.append(f"{an} sits on the {_body_label(a['body'])} and {bn} on the "
                             f"{_body_label(b['body'])}, so they are compared on the matters both acted on, "
                             f"not on shared roll calls. " + summary)
                if both == 0:
                    continue
            if both == 0:
                lines.append(f"{an} and {bn}: no roll calls in common.")
            else:
                lines.append(f"{an} and {bn}: voted the same way on {agree} of {both} shared roll calls; "
                             f"on contested ones, {c_agree} of {c_both}"
                             + (f" ({round(100 * c_agree / c_both)}%)." if c_both else "."))
    if lines:
        out.append(sources.add(("compare", tuple(sorted(p["entity"].id for p in people))), kind="comparison",
                               title="Head-to-head (computed from the minutes and topic records)",
                               text="\n".join(lines), link="/members",
                               date=max((d["record"]["last_vote"] or "" for d in details.values() if d), default=None) or None))
    out.extend(shared_out)
    first = details[people[0]["entity"].id]
    if first and split_keys:
        for v, m, it in _vote_rows_for(session, first, SPLIT_LIMIT,
                                       lambda v: (v["meeting_id"], v["item_label"], v["description"]) in split_keys):
            out.append(_add_vote(sources, v, m, it))
    header = "Comparing " + ", ".join(p["entity"].name for p in people) + "." + (
        " " + " ".join(notes) if notes else "")
    return out, header


def list_members(session: Session, sources: Sources, body: str | None = None) -> list[int]:
    """Sitting members by body, each with their seat's term, plus the body's
    election schedule and official candidate list."""
    people = [p for p in _roster_people(session) if p["is_current"]]
    bodies = [body] if body in BODIES else sorted({p["body"] for p in people if p["body"]},
                                                          key=lambda k: list(BODIES).index(k))
    out = []
    for key in bodies:
        seated = sorted((p for p in people if p["body"] == key),
                        key=lambda p: (members_router._ROLE_ORDER.get(p["roles"][0], 9) if p["roles"] else 9,
                                       p["entity"].name))
        sched = terms.body_terms(key, _today())
        lines = []
        for p in seated:
            t = terms.term_for(key, p["entity"].name, _today())
            bits = [", ".join(p["roles"])]
            if t and t["term_ends"]:
                bits.append(f"term ends {t['term_ends']}")
            if t and t["on_ballot"] is not None:
                bits.append("on the ballot" if t["on_ballot"] else "not on the ballot")
            seat_note = t["note"] if t and t["on_ballot"] is not None else None
            if seat_note:
                bits.append(seat_note.rstrip("."))
            lines.append(f"- {p['entity'].name} ({'; '.join(bits)})")
        if sched:
            lines.append(terms.describe(sched))
            for c in sched["candidates"]:
                lines.append(f"On the official ballot for {c['contest']}: " + ", ".join(c["names"]) + ".")
        else:
            lines.append("No term or election schedule is on file for this body.")
        out.append(sources.add(("roster", key), kind="roster", title=f"{_body_label(key)}: current members",
                               text="\n".join(lines), date=sched["verified"] if sched else None,
                               link=sched["source"] if sched else "/members"))
    return out


def get_upcoming(session: Session, sources: Sources, body: str | None = None, limit: int = 4) -> list[int]:
    now = datetime.datetime.now(LOCAL_TZ).replace(tzinfo=None)
    q = (select(UpcomingMeeting)
         .where(UpcomingMeeting.body.isnot(None),
                or_(UpcomingMeeting.in_progress.is_(True), UpcomingMeeting.starts_at >= now - datetime.timedelta(hours=6)))
         .order_by(UpcomingMeeting.in_progress.desc(), UpcomingMeeting.starts_at.asc().nulls_last())
         .limit(limit))
    if body and body in BODIES:
        q = q.where(UpcomingMeeting.body == body)
    out = []
    for u in session.scalars(q):
        when = u.starts_at.strftime("%Y-%m-%d %H:%M") if u.starts_at else "in progress"
        out.append(sources.add(
            ("upcoming", u.id), kind="upcoming", title=f"{_body_label(u.body)}: {u.title} ({when})",
            text=_clip(u.agenda_text, AGENDA_CHARS) or "Agenda not yet posted.",
            date=u.starts_at.date().isoformat() if u.starts_at else None, link=u.agenda_url))
    return out


# ---------------------------------------------------------------- entity linking

def link_question(session: Session, question: str) -> dict:
    """Tracked topics and members the question names outright, so the
    first turn can point the model at the right lookups."""
    q = f" {question.lower()} "
    uc = _update_counts_subquery()
    name_hit = func.strpos(q, func.lower(Entity.name)) > 0
    alias_hit = exists(select(EntityAlias.id).where(
        EntityAlias.entity_id == Entity.id, func.length(EntityAlias.alias) >= 5,
        func.strpos(q, func.lower(EntityAlias.alias)) > 0))
    topics = [e.name for e, _ in session.execute(
        select(Entity, func.coalesce(uc.c.n, 0)).outerjoin(uc, Entity.id == uc.c.entity_id)
        .where(Entity.entity_type != "person", func.length(Entity.name) >= 5, or_(name_hit, alias_hit))
        .order_by(func.coalesce(uc.c.n, 0).desc()).limit(3))]
    members, seen = [], set()
    for p in _roster_people(session):
        e = p["entity"]
        last = members_router.last_name(e.name).lower()
        if len(last) >= 3 and re.search(rf"\b{re.escape(last)}\b", q) and e.id not in seen:
            seen.add(e.id)
            members.append(f"{e.name} ({', '.join(p['roles'])}"
                           + ("" if p["is_current"] else ", former") + ")")
    return {"topics": topics, "members": members}
