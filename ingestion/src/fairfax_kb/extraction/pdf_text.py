"""Phase 2: extract raw text from downloaded agenda/minutes PDFs."""
import fitz  # pymupdf


def extract_pdf_text(path: str) -> str:
    """Extract plain text from a PDF at `path`. Returns "" on failure
    rather than raising, so a bad PDF doesn't kill a batch run - log it
    instead and let a human/agent flag it for OCR fallback."""
    try:
        doc = fitz.open(path)
        return "\n".join(page.get_text() for page in doc)
    except Exception as e:
        print(f"[extract_pdf_text] failed for {path}: {e}")
        return ""
