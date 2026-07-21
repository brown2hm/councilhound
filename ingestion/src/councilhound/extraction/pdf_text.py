"""
Phase 2: raw text extraction for fetched documents.

Sweeps documents rows that have a file on disk (local_path) but no raw_text
yet, so it can run concurrently with (and incrementally after) the Phase 1
backfill. PDFs go through pymupdf; Granicus HTML (agendas, minutes, actions
reports) is stripped to text with BeautifulSoup.
"""
import logging
import os
import re

import fitz  # pymupdf
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import Document

log = logging.getLogger(__name__)


def pdf_to_text(path: str) -> str:
    parts = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return _sanitize("\n".join(parts))


def _sanitize(text: str) -> str:
    """Make extracted text Postgres-safe and reject encoding garbage.
    Some Fairfax PDFs have broken font encodings and 'extract' as control
    characters — those come back as "" so they land in the OCR bucket."""
    text = text.replace("\x00", "")
    if not text.strip():
        return ""
    printable = sum(ch.isprintable() or ch in "\n\t " for ch in text)
    if printable / len(text) < 0.85:
        return ""
    # strip remaining control chars (keep newline/tab)
    text = re.sub(r"[\x01-\x08\x0b-\x1f\x7f]", "", text)
    return text.strip()


def html_to_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\xa0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_document(doc: Document) -> str | None:
    if doc.local_path.endswith(".pdf"):
        return pdf_to_text(doc.local_path)
    if doc.local_path.endswith(".html"):
        return html_to_text(doc.local_path)
    log.warning("document %s: unknown file type %s", doc.id, doc.local_path)
    return None


def extract_pending(session: Session, limit: int | None = None) -> dict:
    """Extract raw_text for every document that has a file but no text yet.
    Commits per document so a killed run loses nothing."""
    q = (
        select(Document)
        .where(Document.local_path.isnot(None), Document.raw_text.is_(None))
        .order_by(Document.id)
    )
    if limit:
        q = q.limit(limit)
    docs = session.scalars(q).all()

    done = failed = empty = missing = 0
    for doc in docs:
        # local_path may belong to another machine (jobs VMs have ephemeral
        # disks; some docs are fetched locally) — skip, don't traceback.
        if not os.path.exists(doc.local_path):
            missing += 1
            continue
        try:
            text = extract_document(doc)
            if not text:
                # Scanned/image-only or encoding-garbage PDF. Leave raw_text
                # NULL so an OCR pass can find these later.
                empty += 1
                continue
            doc.raw_text = text
            session.commit()
            done += 1
        except Exception:
            session.rollback()
            log.exception("extraction failed for document %s (%s)", doc.id, doc.local_path)
            failed += 1

    result = {"extracted": done, "empty_or_scanned": empty, "failed": failed,
              "file_elsewhere": missing, "candidates": len(docs)}
    log.info("extract_pending: %s", result)
    return result
