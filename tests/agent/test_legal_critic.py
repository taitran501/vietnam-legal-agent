"""Unit tests for Legal Critic Reviewer and Peer Review Guardrails."""

from __future__ import annotations

import pytest

from epr_agent.agent.guardrails import AgentGuardrails
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.verifier import (
    LegalCriticVerdict,
    StaticClaimSupportVerifier,
    StaticLegalCriticReviewer,
)


@pytest.mark.asyncio
async def test_critic_verdict_schema() -> None:
    verdict = LegalCriticVerdict(
        approved=True,
        critique="Căn cứ Điều 115 Luật Doanh nghiệp 2020 là chính xác.",
        corrected_answer=None,
        fatal_error=False,
    )
    assert verdict.approved is True
    assert verdict.fatal_error is False
    assert "Điều 115" in verdict.critique


@pytest.mark.asyncio
async def test_guardrails_check_output_with_critic_approval() -> None:
    doc = DocumentRecord(
        content="Điều 115 quy định quyền của cổ đông phổ thông sở hữu từ 5% cổ phần.",
        document_id="doc-1",
        metadata={"legal_anchor": "Điều 115", "source": "Luật Doanh nghiệp 2020"},
    )
    answer = "Cổ đông sở hữu từ 5% có quyền yêu cầu triệu tập họp ĐHĐCĐ theo Điều 115 [1]."

    guard = AgentGuardrails()
    valid, reason, final_ans, citations = await guard.check_output(
        answer,
        [doc],
        query="Cổ đông 5% có quyền gì?",
        claim_verifier=StaticClaimSupportVerifier(supported=True),
        critic_reviewer=StaticLegalCriticReviewer(
            verdict=LegalCriticVerdict(approved=True, critique="Chuẩn xác.")
        ),
    )
    assert valid is True
    assert reason == "ok"
    assert "Điều 115" in final_ans
    assert len(citations) == 1


@pytest.mark.asyncio
async def test_guardrails_check_output_with_critic_fatal_rejection() -> None:
    doc = DocumentRecord(
        content="Điều 478 Bộ luật Dân sự 2015 quy định về điều chỉnh giá thuê tài sản.",
        document_id="doc-1",
        metadata={"legal_anchor": "Điều 478", "source": "Bộ luật Dân sự 2015"},
    )
    # Answer hallucinates or reverses statutory rule
    answer = "Chủ nhà có quyền tùy ý tăng giá bất cứ lúc nào theo Điều 478 [1]."

    guard = AgentGuardrails()
    valid, reason, fallback, _citations = await guard.check_output(
        answer,
        [doc],
        query="Chủ nhà có được tự ý tăng giá thuê?",
        claim_verifier=StaticClaimSupportVerifier(supported=True),
        critic_reviewer=StaticLegalCriticReviewer(
            verdict=LegalCriticVerdict(
                approved=False,
                fatal_error=True,
                critique="Tư vấn sai hoàn toàn: Đ.478 không cho phép tự ý tăng giá giữa chừng.",
            )
        ),
    )
    assert valid is False
    assert reason == "critic_legal_flaw_rejected"
    assert "chưa đạt tiêu chuẩn thẩm định" in fallback


@pytest.mark.asyncio
async def test_guardrails_check_output_with_critic_refinement() -> None:
    doc = DocumentRecord(
        content="Điều 98 Bộ luật Lao động quy định tiền lương làm thêm giờ.",
        document_id="doc-1",
        metadata={"legal_anchor": "Điều 98", "source": "Bộ luật Lao động 2019"},
    )
    answer = "Làm thêm ngày Chủ nhật được 200% theo Điều 98 [1]."
    refined_answer = "Căn cứ Điều 98 Bộ luật Lao động 2019, người lao động làm thêm vào ngày nghỉ hàng tuần (Chủ nhật) được trả ít nhất 200% lương [1]."

    guard = AgentGuardrails()
    valid, _reason, final_ans, _citations = await guard.check_output(
        answer,
        [doc],
        query="Làm thêm Chủ nhật tính lương thế nào?",
        claim_verifier=StaticClaimSupportVerifier(supported=True),
        critic_reviewer=StaticLegalCriticReviewer(
            verdict=LegalCriticVerdict(
                approved=True,
                critique="Hợp lý nhưng đã bổ sung trích dẫn chi tiết hơn.",
                corrected_answer=refined_answer,
            )
        ),
    )
    assert valid is True
    assert final_ans == refined_answer
