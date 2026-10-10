from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vietnam_legal_agent.tools.contract_redliner import (
    DEFAULT_BATCH_SIZE,
    ClauseReview,
    ContractReviewReport,
    CoverageMetadata,
    _merge_contract_review_reports,
    review_contract_clauses_heuristic,
    review_contract_with_llm,
)
from vietnam_legal_agent.tools.document_parser import ParsedClause, parse_contract_clauses


def test_contract_redliner_heuristic_violations():
    contract_text = """
Điều 1. Công việc và thử việc
Người lao động đồng ý thử việc trong thời gian 90 ngày với mức lương thỏa thuận.

Điều 2. Phạt vi phạm hợp đồng
Nếu một bên vi phạm hợp đồng thì phải chịu phạt vi phạm 20% giá trị hợp đồng.

Điều 3. Lãi suất chậm trả
Trường hợp chậm thanh toán, bên mua phải chịu lãi suất 30% mỗi năm.

Điều 4. Bồi thường thiệt hại
Bên bán được miễn trừ toàn bộ trách nhiệm bồi thường thiệt hại trong mọi trường hợp.
"""
    clauses = parse_contract_clauses(contract_text)
    report = review_contract_clauses_heuristic(clauses, document_title="Hợp đồng dịch vụ")

    assert report.total_clauses == 4
    assert report.overall_risk == "high"
    assert report.high_risk_count >= 3

    # Check that high risk items have statutory conflicts
    conflicts = [c.statutory_conflict for c in report.clause_reviews if c.statutory_conflict]
    assert any("301" in c for c in conflicts)  # Luật Thương mại 8%
    assert any("468" in c for c in conflicts)  # BLDS 20%
    assert any("25" in c for c in conflicts)   # BLLĐ thử việc

    # Check coverage metadata
    assert isinstance(report.coverage, CoverageMetadata)
    assert report.coverage.total_clauses == 4
    assert report.coverage.reviewed_count == 4
    assert report.coverage.coverage_ratio == 1.0
    assert report.coverage.is_complete is True


def test_contract_redliner_heuristic_empty():
    report = review_contract_clauses_heuristic([], document_title="Hợp đồng rỗng")

    assert report.total_clauses == 0
    assert report.clause_reviews == []
    assert report.overall_risk == "low"
    assert report.coverage.total_clauses == 0
    assert report.coverage.reviewed_count == 0
    assert report.coverage.coverage_ratio == 1.0
    assert report.coverage.is_complete is True


def test_contract_redliner_more_than_15_clauses_heuristic():
    """Verify that contracts with > 15 clauses (e.g. 25 clauses) are fully reviewed."""
    lines = []
    for i in range(1, 26):
        if i == 5:
            lines.append(f"Điều {i}. Phạt vi phạm\nBên vi phạm chịu phạt 25% giá trị hợp đồng.")
        elif i == 18:
            lines.append(f"Điều {i}. Lãi suất quá hạn\nLãi suất 36% mỗi năm.")
        else:
            lines.append(f"Điều {i}. Nội dung chung\nCác bên cam kết tuân thủ quy định tại Điều {i}.")

    contract_text = "\n\n".join(lines)
    clauses = parse_contract_clauses(contract_text)
    assert len(clauses) == 25

    report = review_contract_clauses_heuristic(clauses, document_title="Hợp đồng thương mại 25 điều")

    assert report.total_clauses == 25
    assert len(report.clause_reviews) == 25
    assert report.high_risk_count == 2
    assert report.overall_risk == "high"

    # Verify coverage metadata
    assert report.coverage.total_clauses == 25
    assert report.coverage.reviewed_count == 25
    assert report.coverage.coverage_ratio == 1.0
    assert report.coverage.is_complete is True


def test_coverage_metadata_schema_and_serialization():
    """Verify CoverageMetadata model fields, validation, and JSON dictionary serialization."""
    assert DEFAULT_BATCH_SIZE == 10
    coverage = CoverageMetadata(
        total_clauses=30,
        reviewed_count=30,
        coverage_ratio=1.0,
        is_complete=True,
    )
    dumped = coverage.model_dump()
    assert dumped == {
        "total_clauses": 30,
        "reviewed_count": 30,
        "coverage_ratio": 1.0,
        "is_complete": True,
    }

    partial_coverage = CoverageMetadata(
        total_clauses=20,
        reviewed_count=10,
        coverage_ratio=0.5,
        is_complete=False,
    )
    assert partial_coverage.is_complete is False
    assert partial_coverage.coverage_ratio == 0.5


def _generate_mock_clauses(count: int) -> list[ParsedClause]:
    clauses: list[ParsedClause] = []
    for i in range(1, count + 1):
        if i == 12:
            text = f"Điều {i}. Phạt vi phạm\nPhạt vi phạm 25% giá trị nghĩa vụ."
        elif i == 20:
            text = f"Điều {i}. Lãi suất\nLãi chậm trả là 25% mỗi năm."
        else:
            text = f"Điều {i}. Điều khoản chung số {i}\nQuy định điều {i} an toàn và hợp pháp."

        clauses.append(
            ParsedClause(
                clause_id=f"Dieu_{i}",
                clause_number=str(i),
                clause_title=f"Điều khoản {i}",
                full_text=text,
                page_number=1,
            )
        )
    return clauses


@pytest.mark.asyncio
async def test_review_contract_with_llm_multi_batch_success():
    """Verify contracts with > 15 clauses are split into structured batches and merged."""
    clauses = _generate_mock_clauses(25)  # 25 clauses -> 3 batches with batch_size=10
    assert len(clauses) == 25

    # Mock LLM structured output invocation
    mock_model = MagicMock()

    async def mock_ainvoke(messages):
        # Extract payload from human message
        human_content = messages[1][1]
        json_str = human_content.split("Hãy rà soát hợp đồng sau:\n")[1]
        payload = json.loads(json_str)

        batch_clauses = payload["clauses_to_review"]
        reviews = [
            ClauseReview(
                clause_id=c["clause_id"],
                clause_title=c["clause_title"],
                original_text=c["text"],
                risk_level="safe",
                statutory_conflict=None,
                issue_description="Điều khoản hợp lệ.",
                suggested_redline=c["text"],
            )
            for c in batch_clauses
        ]

        return ContractReviewReport(
            document_title=payload["document_title"],
            contract_type=payload["contract_type"],
            overall_risk="low",
            total_clauses=len(batch_clauses),
            high_risk_count=0,
            medium_risk_count=0,
            safe_clause_count=len(batch_clauses),
            executive_summary=f"Batch {payload.get('batch_index')} an toàn.",
            clause_reviews=reviews,
            negotiation_strategy=["Đàm phán bình thường."],
        )

    mock_model.ainvoke = AsyncMock(side_effect=mock_ainvoke)

    mock_llm_smart = MagicMock()
    mock_llm_smart.with_structured_output.return_value = mock_model

    with patch("vietnam_legal_agent.infra.llm_instances.get_llm_smart", return_value=mock_llm_smart):
        report = await review_contract_with_llm(
            clauses=clauses,
            document_title="Hợp đồng kiểm thử 25 điều",
            contract_type="Thương mại",
            batch_size=10,
        )

    # Must invoke 3 batches (10, 10, 5)
    assert mock_model.ainvoke.call_count == 3

    # Verify that all 25 clauses were reviewed rather than sliced to 15
    assert report.total_clauses == 25
    assert len(report.clause_reviews) == 25
    assert report.clause_reviews[0].clause_id == "Dieu_1"
    assert report.clause_reviews[24].clause_id == "Dieu_25"

    # Verify coverage metadata
    assert report.coverage.total_clauses == 25
    assert report.coverage.reviewed_count == 25
    assert report.coverage.coverage_ratio == 1.0
    assert report.coverage.is_complete is True


@pytest.mark.asyncio
async def test_review_contract_with_llm_per_batch_heuristic_fallback():
    """Verify that if an individual LLM batch fails, heuristic review runs for that batch and merges."""
    clauses = _generate_mock_clauses(25)  # 3 batches: 1-10, 11-20 (contains Dieu 12 with 25% penalty), 21-25

    mock_model = MagicMock()
    call_counter = 0

    async def mock_ainvoke(messages):
        nonlocal call_counter
        call_counter += 1

        human_content = messages[1][1]
        json_str = human_content.split("Hãy rà soát hợp đồng sau:\n")[1]
        payload = json.loads(json_str)
        batch_clauses = payload["clauses_to_review"]

        # Batch 2 fails (e.g. rate limit / timeout / invalid json)
        if payload.get("batch_index") == 2:
            raise RuntimeError("OpenAI API rate limit exceeded / timeout on batch 2")

        reviews = [
            ClauseReview(
                clause_id=c["clause_id"],
                clause_title=c["clause_title"],
                original_text=c["text"],
                risk_level="safe",
                statutory_conflict=None,
                issue_description="Điều khoản hợp lệ.",
                suggested_redline=c["text"],
            )
            for c in batch_clauses
        ]

        return ContractReviewReport(
            document_title=payload["document_title"],
            contract_type=payload["contract_type"],
            overall_risk="low",
            total_clauses=len(batch_clauses),
            high_risk_count=0,
            medium_risk_count=0,
            safe_clause_count=len(batch_clauses),
            executive_summary=f"Batch {payload.get('batch_index')} an toàn.",
            clause_reviews=reviews,
            negotiation_strategy=["Giữ nguyên các điều khoản."],
        )

    mock_model.ainvoke = AsyncMock(side_effect=mock_ainvoke)
    mock_llm_smart = MagicMock()
    mock_llm_smart.with_structured_output.return_value = mock_model

    with patch("vietnam_legal_agent.infra.llm_instances.get_llm_smart", return_value=mock_llm_smart):
        report = await review_contract_with_llm(
            clauses=clauses,
            document_title="Hợp đồng kiểm thử lỗi batch",
            batch_size=10,
        )

    # 3 batches were attempted
    assert call_counter == 3

    # All 25 clauses are preserved in merged output
    assert report.total_clauses == 25
    assert len(report.clause_reviews) == 25

    # Batch 2 fell back to heuristic review: Dieu 12 (penalty 25%) should be caught as high risk!
    dieu_12_review = next(r for r in report.clause_reviews if r.clause_id == "Dieu_12")
    assert dieu_12_review.risk_level == "high"
    assert "301" in (dieu_12_review.statutory_conflict or "")

    # Coverage is still complete because heuristic covered batch 2
    assert report.coverage.total_clauses == 25
    assert report.coverage.reviewed_count == 25
    assert report.coverage.coverage_ratio == 1.0
    assert report.coverage.is_complete is True


@pytest.mark.asyncio
async def test_review_contract_with_llm_all_batches_fail():
    """Verify that when all LLM batch invocations fail, full heuristic review covers the entire contract."""
    clauses = _generate_mock_clauses(22)

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(side_effect=RuntimeError("Provider connection failure"))
    mock_llm_smart = MagicMock()
    mock_llm_smart.with_structured_output.return_value = mock_model

    with patch("vietnam_legal_agent.infra.llm_instances.get_llm_smart", return_value=mock_llm_smart):
        report = await review_contract_with_llm(
            clauses=clauses,
            document_title="Hợp đồng toàn bộ lỗi LLM",
            batch_size=10,
        )

    assert report.total_clauses == 22
    assert len(report.clause_reviews) == 22
    assert report.coverage.total_clauses == 22
    assert report.coverage.reviewed_count == 22
    assert report.coverage.is_complete is True


@pytest.mark.asyncio
async def test_review_contract_with_llm_empty_input():
    """Verify review_contract_with_llm handles empty clause input gracefully."""
    report = await review_contract_with_llm([])
    assert report.total_clauses == 0
    assert report.clause_reviews == []
    assert report.coverage.total_clauses == 0
    assert report.coverage.reviewed_count == 0
    assert report.coverage.is_complete is True


@pytest.mark.asyncio
async def test_review_contract_with_llm_init_failure():
    """Verify review_contract_with_llm falls back to heuristic if LLM initialization fails."""
    clauses = _generate_mock_clauses(18)

    with patch(
        "vietnam_legal_agent.infra.llm_instances.get_llm_smart",
        side_effect=ValueError("LLM credentials missing"),
    ):
        report = await review_contract_with_llm(
            clauses=clauses,
            document_title="Hợp đồng fallback init",
            batch_size=10,
        )

    assert report.total_clauses == 18
    assert len(report.clause_reviews) == 18
    assert report.coverage.total_clauses == 18
    assert report.coverage.reviewed_count == 18
    assert report.coverage.is_complete is True


def test_merge_contract_review_reports_partial_coverage():
    """Verify _merge_contract_review_reports properly computes partial coverage if reviews are missing."""
    cr1 = ClauseReview(
        clause_id="Dieu_1",
        clause_title="Tiêu đề 1",
        original_text="Nội dung 1",
        risk_level="safe",
        statutory_conflict=None,
        issue_description="An toàn",
        suggested_redline="Nội dung 1",
    )
    batch_report = ContractReviewReport(
        document_title="Tài liệu",
        contract_type="Thương mại",
        overall_risk="low",
        total_clauses=1,
        high_risk_count=0,
        medium_risk_count=0,
        safe_clause_count=1,
        executive_summary="Tóm tắt",
        clause_reviews=[cr1],
        negotiation_strategy=["Chiến lược A"],
    )

    # 1 clause reviewed out of 2 expected
    merged = _merge_contract_review_reports(
        batch_reports=[batch_report],
        total_expected_clauses=2,
        document_title="Tài liệu",
        contract_type="Thương mại",
    )

    assert merged.total_clauses == 2
    assert len(merged.clause_reviews) == 1
    assert merged.coverage.total_clauses == 2
    assert merged.coverage.reviewed_count == 1
    assert merged.coverage.coverage_ratio == 0.5
    assert merged.coverage.is_complete is False


def test_merge_contract_review_reports_empty_batch_list():
    """Verify _merge_contract_review_reports handles empty batch reports gracefully."""
    merged = _merge_contract_review_reports(
        batch_reports=[],
        total_expected_clauses=5,
        document_title="Tài liệu",
        contract_type="Thương mại",
    )
    assert merged.total_clauses == 0
    assert merged.coverage.total_clauses == 5
    assert merged.coverage.reviewed_count == 0
    assert merged.coverage.coverage_ratio == 0.0
    assert merged.coverage.is_complete is False
