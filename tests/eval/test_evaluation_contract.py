"""Tests for the replayable evaluation contract and verifier."""

from __future__ import annotations

from pathlib import Path

import pytest

from epr_agent.eval.contracts import (
    AuthoritativeSource,
    EvalTurn,
    EvaluationCase,
    EvaluationStatus,
    EvidenceStatus,
    ExpectedCitation,
    ExpectedClaim,
    ExpectedOutcome,
    load_evaluation_case,
)
from epr_agent.eval.evidence_verifier import verify_evaluation_case


def _evaluation_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="SYNTHETIC-001",
        turns=[EvalTurn(query="Quy định gì?", expected_outcome=ExpectedOutcome.ANSWER_COMPLETE)],
        expected_outcome=ExpectedOutcome.ANSWER_COMPLETE,
        claims=[
            ExpectedClaim(
                claim_id="claim-1",
                text="Thời hạn là 10 ngày.",
                source_ids=["law-1"],
                anchors=["Điều 1"],
                match_terms=["10 ngày"],
            )
        ],
        sources=[
            AuthoritativeSource(
                source_id="law-1",
                title="Luật thử nghiệm",
                official_url="https://example.gov.vn/law-1",
                anchors=["Điều 1"],
                corpus_sha="sha-test",
            )
        ],
        citations=[ExpectedCitation(claim_id="claim-1", source_id="law-1", anchor="Điều 1", citation_index=1)],
        evidence={
            "status": EvidenceStatus.READY,
            "corpus_sha": "sha-test",
        },
    )


def test_evaluation_case_uses_informational_evidence_by_default() -> None:
    case = EvaluationCase(
        case_id="informational-default",
        turns=[EvalTurn(query="Q")],
        evidence={"status": EvidenceStatus.INFORMATIONAL},
    )
    assert case.evidence.status == EvidenceStatus.INFORMATIONAL


def test_example_fixture_is_evaluated_as_engineering_evidence() -> None:
    fixture = load_evaluation_case(Path("data/eval/examples/legal-follow-up.json"))
    result = verify_evaluation_case(
        fixture,
        answer="Chưa có đủ dữ liệu trong bản replay.",
        documents=[],
        observed_outcome=ExpectedOutcome.CLARIFICATION,
    )
    assert result.status == EvaluationStatus.PASS
    assert result.gate_eligible is True


def test_verifier_maps_claim_to_source_and_citation() -> None:
    case = _evaluation_case()
    documents = [
        {
            "source_id": "law-1",
            "anchor": "Điều 1",
            "official_url": "https://example.gov.vn/law-1",
            "excerpt": "Điều 1 quy định thời hạn 10 ngày.",
        }
    ]
    result = verify_evaluation_case(
        case,
        answer="Theo Điều 1, thời hạn là 10 ngày [1].",
        documents=documents,
        source_drawer_documents=documents,
        observed_outcome=ExpectedOutcome.ANSWER_COMPLETE,
    )
    assert result.status == EvaluationStatus.PASS
    assert result.gate_eligible is True
    assert result.failure_codes == []
    assert result.claim_results[0].supported is True
    assert result.source_results[0].official_url_matches is True
    assert result.source_results[0].present_in_drawer is True


def test_verifier_reports_missing_source_drawer_payload() -> None:
    case = _evaluation_case()
    documents = [
        {
            "source_id": "law-1",
            "anchor": "Điều 1",
            "official_url": "https://example.gov.vn/law-1",
            "excerpt": "Điều 1 quy định thời hạn 10 ngày.",
        }
    ]

    result = verify_evaluation_case(
        case,
        answer="Theo Điều 1, thời hạn là 10 ngày [1].",
        documents=documents,
        source_drawer_documents=[],
        observed_outcome=ExpectedOutcome.ANSWER_COMPLETE,
    )

    assert result.status == EvaluationStatus.FAIL
    assert "source_drawer_payload_mismatch" in {code.value for code in result.failure_codes}
    assert result.source_results[0].present is True
    assert result.source_results[0].present_in_drawer is False


def test_verifier_reports_retrieval_and_unsupported_claim_failures() -> None:
    result = verify_evaluation_case(
        _evaluation_case(),
        answer="Theo Điều 1, thời hạn là 30 ngày [1].",
        documents=[],
        source_drawer_documents=[],
        observed_outcome=ExpectedOutcome.ANSWER_COMPLETE,
    )
    assert result.status == EvaluationStatus.FAIL
    assert "retrieval_miss" in {code.value for code in result.failure_codes}
    assert "unsupported_claim" in {code.value for code in result.failure_codes}


@pytest.mark.asyncio
async def test_ragas_judge_failure_is_not_scored_as_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    from epr_agent.eval.ragas_evaluator import evaluate_ragas_sample

    def unavailable():
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr("epr_agent.infra.llm_instances.get_llm_smart", unavailable)
    result = await evaluate_ragas_sample(
        query="Quy định gì?",
        answer="Theo Điều 1 [1].",
        retrieved_docs=[{"page_content": "Điều 1", "metadata": {}}],
        expected_anchors=["Điều 1"],
        sample_id="judge-unavailable",
    )
    assert result.evaluator_status == "evaluation_unavailable"
    assert result.passed_gate is False
    assert result.overall_ragas_score == 0.0
    assert "faithfulness_error" in result.details
