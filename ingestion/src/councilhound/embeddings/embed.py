"""
Phase 4: embeddings for the RAG corpus.

Provider decision (2026-07-11): local sentence-transformers with
BAAI/bge-base-en-v1.5 (768 dims) — no extra API key, free backfill, and the
API can embed queries on CPU in ~10ms. Swapping providers later = change
EMBEDDING_MODEL/backend here + a migration to the new dimension + re-embed.

Corpus v1: transcript_chunks (timestamped video citations) and agenda_items
(label+title+description+outcome — precise per-meeting retrieval units).
Staff-report PDF chunks are a later addition.

BGE asymmetric convention: passages are embedded bare; queries get the
"Represent this sentence..." prefix via embed_query().
"""
import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import AgendaItem, TranscriptChunk

log = logging.getLogger(__name__)

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
EMBEDDING_DIM = 768
# 'cpu' default: bulk embedding often runs alongside MLX whisper, which owns
# the GPU; CPU throughput (~200 texts/s) is plenty. Set EMBEDDING_DEVICE=mps
# for a dedicated run.
EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "cpu")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        log.info("loading embedding model %s on %s", EMBEDDING_MODEL, EMBEDDING_DEVICE)
        _model = SentenceTransformer(EMBEDDING_MODEL, device=EMBEDDING_DEVICE)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed passages (documents/chunks)."""
    return _get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def embed_query(question: str) -> list[float]:
    """Embed a search query (BGE query prefix applied)."""
    return embed_texts([QUERY_PREFIX + question])[0]


def agenda_item_text(item: AgendaItem) -> str:
    parts = [f"Agenda item {item.label}"]
    for field in (item.title, item.description, item.outcome):
        if field:
            parts.append(field)
    return ". ".join(parts)


def embed_pending(session: Session, batch_size: int = 64, limit: int | None = None) -> dict:
    """Embed every transcript chunk and agenda item without an embedding.
    Batched commits — resumable, safe to run while Phase 2/3 jobs are still
    inserting rows (a later run sweeps up what they add)."""
    counts = {"transcript_chunks": 0, "agenda_items": 0}

    q = select(TranscriptChunk).where(TranscriptChunk.embedding.is_(None)).order_by(TranscriptChunk.id)
    if limit:
        q = q.limit(limit)
    chunks = session.scalars(q).all()
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        vectors = embed_texts([c.text for c in batch])
        for chunk, vec in zip(batch, vectors):
            chunk.embedding = vec
        session.commit()
        counts["transcript_chunks"] += len(batch)

    q = select(AgendaItem).where(AgendaItem.embedding.is_(None)).order_by(AgendaItem.id)
    if limit:
        q = q.limit(limit)
    items = session.scalars(q).all()
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        vectors = embed_texts([agenda_item_text(it) for it in batch])
        for item, vec in zip(batch, vectors):
            item.embedding = vec
        session.commit()
        counts["agenda_items"] += len(batch)

    log.info("embed_pending: %s", counts)
    return counts
