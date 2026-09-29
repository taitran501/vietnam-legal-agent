from __future__ import annotations

import fitz
from scripts.extract_appendix_xxii import (
    _APPENDIX,
    _NEXT_APPENDIX,
    _appendix_pages,
    _has_appendix_heading,
    _normalize_pdf_cell,
    _row_text,
)


def test_appendix_heading_requires_a_standalone_line() -> None:
    assert not _has_appendix_heading("Article 77 refers to PHU LUC XXII for rates.", _APPENDIX)
    assert _has_appendix_heading("PHU LUC XXII\nTable title", _APPENDIX)
    assert not _has_appendix_heading("Article 82 refers to PHU LUC XXIII.", _NEXT_APPENDIX)


def test_appendix_row_text_matches_the_cell_provenance_audit() -> None:
    assert _row_text(["  rate  ", "", "recycling method"]) == "rate recycling method"
    assert _normalize_pdf_cell("máy ảnh (kể cả đèn falsh)") == "máy ảnh (kể cả đèn flash)"


def test_appendix_pages_skip_cross_references_and_stop_at_next_heading(tmp_path) -> None:
    source = tmp_path / "appendix-headings.pdf"
    pdf = fitz.open()
    for text in (
        "Article 77 refers to PHU LUC XXII.",
        "PHU LUC XXII\nAppendix content starts here.",
        "Appendix continuation page.",
        "PHU LUC XXIII\nNext appendix starts here.",
    ):
        page = pdf.new_page()
        page.insert_text((72, 72), text)
    pdf.save(source)
    pdf.close()

    document, pages = _appendix_pages(source)
    try:
        assert [page + 1 for page in pages] == [2, 3]
    finally:
        document.close()
