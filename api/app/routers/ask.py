"""
Phase 4: RAG query endpoint.

Pipeline: embed the question (local bge model) -> cosine search over
transcript_chunks and agenda_items (pgvector HNSW) -> hand the retrieved,
numbered sources to Claude with answer-from-context-only instructions ->
return the answer plus the source list, each with links back to the
original Granicus clip timestamp or document.

Grounding contract: every source given to the model carries an index; the
model cites [n]. Sources the model didn't receive can't be cited, and if
retrieval comes back empty we say so instead of calling the model.
"""
import os
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.config import ANTHROPIC_API_KEY
from councilhound.db.models import AgendaItem, Meeting, TranscriptChunk
from councilhound.embeddings.embed import embed_query

from app.db import db_session
from app.links import clip_link
from app.ratelimit import check_ask_rate

router = APIRouter()

ASK_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
TOP_K = 8

ANSWER_SYSTEM = """\
You answer questions about city council and planning commission activity \
using ONLY the numbered sources provided. Rules:
- Every factual claim must cite its source(s) inline as [n].
- If the sources don't contain the answer, say so plainly — never fill gaps \
from general knowledge.
- Prefer agenda-item sources for outcomes/votes and transcript sources for \
what was said. Dates matter: make clear when each cited event happened.
- Format the answer as Markdown (the frontend renders it): short paragraphs, \
**bold** for key outcomes, bullet lists where they aid scanning. No headings \
unless the answer genuinely has multiple sections."""


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _retrieve(session: Session, vec: list[float]) -> list[dict]:
    sources = []

    chunk_rows = session.execute(
        select(TranscriptChunk, Meeting,
               TranscriptChunk.embedding.cosine_distance(vec).label("d"))
        .join(Meeting, TranscriptChunk.meeting_id == Meeting.id)
        .where(TranscriptChunk.embedding.isnot(None))
        .order_by("d")
        .limit(TOP_K)
    ).all()
    for chunk, meeting, dist in chunk_rows:
        sources.append({
            "kind": "transcript",
            "distance": float(dist),
            "meeting_id": meeting.id,
            "meeting_title": meeting.title,
            "date": meeting.meeting_date.isoformat(),
            "text": chunk.text,
            "start_seconds": float(chunk.start_seconds) if chunk.start_seconds is not None else None,
            "link": clip_link(meeting.granicus_view_id, meeting.granicus_clip_id,
                              float(chunk.start_seconds or 0)),
        })

    item_rows = session.execute(
        select(AgendaItem, Meeting,
               AgendaItem.embedding.cosine_distance(vec).label("d"))
        .join(Meeting, AgendaItem.meeting_id == Meeting.id)
        .where(AgendaItem.embedding.isnot(None))
        .order_by("d")
        .limit(TOP_K)
    ).all()
    for item, meeting, dist in item_rows:
        text = ". ".join(p for p in (item.title, item.description, item.outcome) if p)
        sources.append({
            "kind": "agenda_item",
            "distance": float(dist),
            "meeting_id": meeting.id,
            "meeting_title": meeting.title,
            "date": meeting.meeting_date.isoformat(),
            "agenda_item_label": item.label,
            "text": text,
            "link": meeting.minutes_url or meeting.agenda_url,
        })

    sources.sort(key=lambda s: s["distance"])
    return sources[:TOP_K + 4]


def _answer(question: str, sources: list[dict]) -> str:
    import anthropic

    numbered = []
    for i, s in enumerate(sources, 1):
        prefix = (f"[{i}] ({s['kind']}, {s['date']}, {s['meeting_title']}"
                  + (f", item {s['agenda_item_label']}" if s.get("agenda_item_label") else "")
                  + ")")
        numbered.append(f"{prefix}\n{s['text']}")
    prompt = (f"Question: {question}\n\nSources:\n\n" + "\n\n".join(numbered))

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=ASK_MODEL,
        max_tokens=1500,
        system=ANSWER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


@router.post("/", dependencies=[Depends(check_ask_rate)])
def ask(req: AskRequest, session: Session = Depends(db_session)):
    vec = embed_query(req.question)
    sources = _retrieve(session, vec)
    if not sources:
        return {"answer": "No indexed meeting content matched this question yet.",
                "citations": []}

    answer = _answer(req.question, sources)

    cited_indexes = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    citations = [
        {
            "index": i,
            "kind": s["kind"],
            "date": s["date"],
            "meeting_id": s["meeting_id"],
            "meeting_title": s["meeting_title"],
            "agenda_item_label": s.get("agenda_item_label"),
            "start_seconds": s.get("start_seconds"),
            "link": s["link"],
            "excerpt": s["text"][:300],
        }
        for i, s in enumerate(sources, 1)
        if i in cited_indexes
    ]
    return {"answer": answer, "citations": citations}
