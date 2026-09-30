from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.evidence import legal_claim_segments
from vietnam_legal_agent.tools.generation import (
    EvidenceGenerationGateway,
    _answer_preserves_source_exceptions,
)


def test_legal_lookup_renderer_keeps_each_claim_attached_to_exact_chunk():
    documents = [
        DocumentRecord(
            content=(
                "Người lao động có trình độ cao đẳng trở lên được thử việc tối đa 60 ngày."
            ),
            document_id="labor-25",
            source="legal",
            metadata={
                "Dieu": "Điều 25. Thời gian thử việc",
                "source_title": "Bộ luật Lao động 2019",
            },
        )
    ]

    answer = EvidenceGenerationGateway._compose_legal_route_answer(documents)

    assert "[1]" in answer
    assert "Nguồn tham khảo" in answer
    assert legal_claim_segments(answer) == [
        (
            "Theo Điều 25. Thời gian thử việc, văn bản quy định: "
            "Người lao động có trình độ cao đẳng trở lên được thử việc tối đa 60 ngày. [1]"
        )
    ]


def test_legal_synthesis_preserves_a_cross_referenced_exception():
    source = DocumentRecord(
        content=(
            "Điều 468. Lãi suất vay. "
            "1. Lãi suất do các bên thỏa thuận, trừ trường hợp luật khác có liên quan quy định khác. "
            "Mức lãi suất theo thỏa thuận không được vượt quá 20% một năm."
        ),
        document_id="civil-468",
        source="legal",
        metadata={
            "Dieu": "Điều 468. Lãi suất trong hợp đồng vay",
            "source_title": "Bộ luật Dân sự 2015",
        },
    )
    incomplete = (
        "Các bên có thể thỏa thuận lãi suất vay nhưng không vượt quá 20% một năm [1]."
    )
    qualified = (
        "Các bên có thể thỏa thuận lãi suất vay nhưng không vượt quá 20% một năm, "
        "trừ trường hợp luật khác có liên quan quy định khác [1]."
    )

    assert _answer_preserves_source_exceptions(incomplete, [source]) is False
    assert _answer_preserves_source_exceptions(qualified, [source]) is True

    extractive = EvidenceGenerationGateway._compose_legal_route_answer([source])
    assert "trừ trường hợp luật khác có liên quan quy định khác" in extractive
