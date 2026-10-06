"""Project-document indexing: which listed files are worth reading, dates
from labels, and prose split into page-tagged passages (drawings skipped)."""
import datetime

import fitz

from councilhound import project_docs as pd


def test_drawings_appendices_and_huge_files_are_skipped():
    pdf = "https://x/a.pdf"
    assert pd.wanted({"url": pdf, "label": "July 3, 2023 Narrative (PDF, 232KB)"})
    assert pd.wanted({"url": pdf, "label": "July 3, 2023 Transportation Impact Study (PDF, 22MB)"})
    assert not pd.wanted({"url": pdf, "label": "July 3, 2023 Plan Sheets 1-26 (PDF, 18MB)"})
    assert not pd.wanted({"url": pdf, "label": "Transportation Impact Study Technical Appendix (PDF, 12MB)"})
    assert not pd.wanted({"url": pdf, "label": "Architectural Elevations (PDF, 4MB)"})
    assert not pd.wanted({"url": pdf, "label": "Everything (PDF, 90MB)"})
    assert not pd.wanted({"url": "https://x/page.html", "label": "Narrative"})


def test_label_dates_and_sizes():
    assert pd.label_date("July 3, 2023 Narrative (PDF, 232KB)") == datetime.date(2023, 7, 3)
    assert pd.label_date("Narrative") is None
    assert pd.listed_bytes("Study (PDF, 22MB)") == 22_000_000
    assert pd.listed_bytes("Narrative (PDF, 232KB)") == 232_000


def _pdf(tmp_path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(36, 36, 576, 806), text, fontsize=9)
    path = tmp_path / "doc.pdf"
    doc.save(path)
    return path


def test_prose_splits_into_page_tagged_passages(tmp_path):
    para = ("The applicant proposes an eight-story building with 79 condominium units, "
            "five of them affordable, and ground-floor retail along Main Street. ") * 4
    path = _pdf(tmp_path, [f"{para}\n\n{para}\n\n{para}", f"{para}\n\nThe study counts 292 morning trips."])
    found = pd.passages(path)
    assert [p for p, _ in found][:1] == [1] and found[-1][0] == 2
    assert all(len(t) <= pd.PASSAGE_CHARS * 1.5 for _, t in found)
    assert "292 morning trips" in found[-1][1]


def test_drawing_sets_read_as_nothing(tmp_path):
    path = _pdf(tmp_path, ["SHEET C-101", "SHEET C-102", "N"])
    assert pd.passages(path) == []
