"""
Phase 4: RAG query endpoint.

Given a natural-language question, retrieve relevant transcript_chunks
(via embedding similarity) + relevant entity summaries, then ask Claude to
answer using only that retrieved context, citing meeting_id/document_id for
each claim so the front end can link back to the source clip/document.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class AskRequest(BaseModel):
    question: str


@router.post("/")
def ask(req: AskRequest):
    """TODO: embed req.question, similarity search transcript_chunks,
    pull matching entity summaries, call Claude with retrieved context only,
    return answer + citations."""
    return {"todo": "implement in Phase 4", "question": req.question}
