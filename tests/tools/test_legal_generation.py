from __future__ import annotations

import pytest

from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.tools.evidence import legal_claim_segments, propagate_list_item_citations
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway


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
    claims = legal_claim_segments(answer)
    assert len(claims) == 1
    assert claims[0].endswith("tối đa 60 ngày. [1]")


@pytest.mark.asyncio
async def test_repair_preserves_direct_list_answer_when_citation_completion_makes_it_valid():
    source = DocumentRecord(
        content="Điều 25 quy định bốn mức thời gian thử việc theo tính chất công việc.",
        document_id="labor-25",
        source="legal",
        metadata={"Dieu": "Điều 25", "source_title": "Bộ luật Lao động"},
    )
    answer = (
        "Thời gian thử việc tối đa gồm:\n"
        "1. Không quá 180 ngày với người quản lý doanh nghiệp.\n"
        "2. Không quá 60 ngày với công việc cần trình độ cao đẳng trở lên. [1]"
    )

    repaired = await EvidenceGenerationGateway().repair(answer, [source], TaskType.LEGAL_LOOKUP)

    assert repaired == propagate_list_item_citations(answer)
    assert "Theo Điều 25, văn bản quy định" not in repaired


@pytest.mark.asyncio
async def test_legal_synthesis_is_not_replaced_by_raw_source_on_phrase_mismatch(
    monkeypatch: pytest.MonkeyPatch,
):
    source = DocumentRecord(
        content=(
            "Điều 468. Lãi suất vay. "
            "Lãi suất do các bên thỏa thuận, trừ trường hợp luật khác có liên quan quy định khác. "
            "Mức lãi suất theo thỏa thuận không được vượt quá 20% một năm."
        ),
        document_id="civil-468",
        source="legal",
        metadata={
            "Dieu": "Điều 468. Lãi suất trong hợp đồng vay",
            "source_title": "Bộ luật Dân sự 2015",
        },
    )
    synthesized = (
        "Các bên có thể thỏa thuận lãi suất vay, nhưng giới hạn 20% một năm không áp dụng "
        "khi luật liên quan quy định khác [1]."
    )

    async def _synthesize(_cls, _query, _documents):
        return synthesized

    monkeypatch.setattr(
        EvidenceGenerationGateway,
        "_synthesize_legal_route_answer",
        classmethod(_synthesize),
    )

    answer = await EvidenceGenerationGateway().answer(
        "legal_lookup",
        "Lãi suất vay tối đa bao nhiêu?",
        [source],
        {},
    )

    assert answer == synthesized
    assert "Theo Điều 468, văn bản quy định" not in answer
