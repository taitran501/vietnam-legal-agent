"""Unit tests for Deer-Flow Citation Sources Architecture."""

from __future__ import annotations

import pytest
from epr_agent.domain.models import DocumentRecord, CitationSource, CitationOccurrence
from epr_agent.tools.evidence import (
    extract_citation_sources,
    format_citation_markdown_reference,
    mask_citation_code,
)


def test_mask_citation_code_ignores_codeblocks_and_inlines() -> None:
    """Ensure citation parser masks code regions with spaces so [1] in code is ignored."""
    text = (
        "Căn cứ quy định [1], ta có hàm:\n"
        "```python\n"
        "arr = [1, 2, 3]\n"
        "val = arr[2]\n"
        "```\n"
        "Theo đó [2], kết quả trả về `item[1]` hợp lệ."
    )
    masked = mask_citation_code(text)
    # Citations in prose remain intact
    assert "[1]" in masked
    assert "[2]" in masked
    # Brackets inside code blocks are masked with whitespace
    assert "[1, 2, 3]" not in masked
    assert "item[1]" not in masked


def test_extract_citation_sources_aggregates_occurrences() -> None:
    """Test extract_citation_sources correctly counts and aggregates source metadata."""
    docs = [
        DocumentRecord(
            content="Quy định về thời hạn báo trước và bồi thường khi đơn phương chấm dứt HĐLĐ.",
            metadata={
                "source_title": "Bộ luật Lao động 2019",
                "source_file": "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Bo-luat-Lao-dong-2019-333670.aspx",
                "Dieu": "Điều 36",
            },
            document_id="blld-36",
            score=0.92,
            source="Bộ luật Lao động 2019",
        ),
        DocumentRecord(
            content="Nghĩa vụ của người sử dụng lao động khi chấm dứt hợp đồng trái luật.",
            metadata={
                "source_title": "Bộ luật Lao động 2019",
                "source_file": "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Bo-luat-Lao-dong-2019-333670.aspx",
                "Dieu": "Điều 41",
            },
            document_id="blld-41",
            score=0.90,
            source="Bộ luật Lao động 2019",
        ),
    ]

    answer = (
        "Theo quy định [1], NSDLĐ phải báo trước ít nhất 30 ngày. "
        "Nếu vi phạm [1], NSDLĐ phải bồi thường theo quy định [2]."
    )

    sources = extract_citation_sources(answer, docs)
    assert len(sources) == 2

    s1 = sources[0]
    assert s1.doc_id == "blld-36"
    assert s1.count == 2
    assert len(s1.occurrences) == 2
    assert s1.occurrences[0].index == 1
    assert s1.occurrences[1].index == 1
    assert s1.title == "Điều 36"
    assert s1.domain == "thuvienphapluat.vn"
    assert "thời hạn báo trước" in s1.excerpt

    s2 = sources[1]
    assert s2.doc_id == "blld-41"
    assert s2.count == 1
    assert len(s2.occurrences) == 1
    assert s2.occurrences[0].index == 2
    assert s2.domain == "thuvienphapluat.vn"


def test_format_citation_markdown_reference() -> None:
    """Test formatting citations as markdown reference footer."""
    sources = [
        CitationSource(
            id="doc-1",
            title="Bộ luật Lao động 2019",
            url="https://thuvienphapluat.vn/doc1",
            domain="thuvienphapluat.vn",
            count=1,
            occurrences=[CitationOccurrence(index=1, title="Điều 36")],
            excerpt="Trích dẫn điều 36...",
        )
    ]
    md = format_citation_markdown_reference(sources)
    assert "### 📚 Nguồn căn cứ pháp lý & Tài liệu tham chiếu" in md
    assert "[1] [Bộ luật Lao động 2019](https://thuvienphapluat.vn/doc1)" in md
    assert "(thuvienphapluat.vn)" in md

    # Single source
    single_md = format_citation_markdown_reference(sources[0])
    assert single_md == "[Bộ luật Lao động 2019](https://thuvienphapluat.vn/doc1)"
