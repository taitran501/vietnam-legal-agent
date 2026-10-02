from __future__ import annotations

import pytest

from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.tools.evidence import (
    legal_claim_segments,
    propagate_list_item_citations,
    verify_citations,
)
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
async def test_repair_regenerates_structurally_valid_answer_with_original_question(
    monkeypatch: pytest.MonkeyPatch,
):
    source = DocumentRecord(
        content="Điều 81 quy định việc giao con trực tiếp nuôi sau khi ly hôn.",
        document_id="family-81",
        source="legal",
        metadata={"Dieu": "Điều 81", "source_title": "Luật Hôn nhân và gia đình"},
    )
    captured = {}
    expected = "Tòa xem xét quyền lợi mọi mặt của con [1]."

    async def _repair(_cls, query, answer, documents):
        captured["query"] = query
        captured["answer"] = answer
        captured["documents"] = documents
        return expected

    monkeypatch.setattr(EvidenceGenerationGateway, "_repair_legal_route_answer", classmethod(_repair))
    draft = "Tòa xem xét việc thay đổi người trực tiếp nuôi con [1]."

    repaired = await EvidenceGenerationGateway().repair(
        draft,
        [source],
        TaskType.LEGAL_LOOKUP,
        query="Ly hôn, tòa quyết định ban đầu ai trực tiếp nuôi con?",
    )

    assert repaired == expected
    assert captured["query"] == "Ly hôn, tòa quyết định ban đầu ai trực tiếp nuôi con?"
    assert captured["answer"] == draft
    assert captured["documents"] == [source]


@pytest.mark.asyncio
async def test_repair_adds_citations_to_each_uncited_legal_claim(monkeypatch: pytest.MonkeyPatch):
    source = DocumentRecord(
        content="Điều 468 quy định nghĩa vụ trả lãi khi chậm trả và lãi suất do các bên thỏa thuận.",
        document_id="civil-468",
        source="legal",
        metadata={"Dieu": "Điều 468", "source_title": "Bộ luật Dân sự"},
    )

    async def _repair(_cls, query, answer, documents):
        return "Bên vay phải trả lãi chậm trả. Mức lãi phải căn cứ vào thỏa thuận."

    monkeypatch.setattr(EvidenceGenerationGateway, "_repair_legal_route_answer", classmethod(_repair))

    repaired = await EvidenceGenerationGateway().repair(
        "Bên vay phải trả lãi [1].",
        [source],
        TaskType.LEGAL_LOOKUP,
        query="Quá hạn trả khoản vay thì có phải trả lãi chậm trả không?",
    )

    assert repaired == "Bên vay phải trả lãi chậm trả. [1] Mức lãi phải căn cứ vào thỏa thuận. [1]"
    assert verify_citations(repaired, [source], TaskType.LEGAL_LOOKUP)[0]


@pytest.mark.asyncio
async def test_case_assessment_uses_query_grounded_legal_synthesis(monkeypatch: pytest.MonkeyPatch):
    source = DocumentRecord(
        content="Nếu bên có nghĩa vụ chậm trả tiền thì phải trả lãi đối với số tiền chậm trả.",
        document_id="civil-late-payment",
        source="legal",
        metadata={"Dieu": "Điều 357", "source_title": "Bộ luật Dân sự"},
    )
    captured = {}

    async def _synthesize(_cls, query, documents):
        captured["query"] = query
        captured["documents"] = documents
        return "Bên vay phải trả lãi đối với số tiền chậm trả [1]."

    monkeypatch.setattr(
        EvidenceGenerationGateway,
        "_synthesize_legal_route_answer",
        classmethod(_synthesize),
    )

    answer = await EvidenceGenerationGateway().answer(
        TaskType.CASE_ASSESSMENT.value,
        "Quá hạn trả khoản vay thì có phải trả lãi chậm trả không?",
        [source],
        {},
    )

    assert answer == "Bên vay phải trả lãi đối với số tiền chậm trả [1]."
    assert captured["query"] == "Quá hạn trả khoản vay thì có phải trả lãi chậm trả không?"
    assert captured["documents"] == [source]


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
