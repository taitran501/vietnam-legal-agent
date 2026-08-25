"""Tests for the source-audited evaluation contract and verifier."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from epr_agent.eval.contracts import (
    AuditedEvalCase,
    AuditStatus,
    AuthoritativeSource,
    EvalTurn,
    EvaluationStatus,
    ExpectedCitation,
    ExpectedClaim,
    ExpectedOutcome,
    load_audited_case,
)
from epr_agent.eval.evidence_verifier import verify_audited_case


def _audited_case() -> AuditedEvalCase:
    return AuditedEvalCase(
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
        audit={
            "status": AuditStatus.AUDITED,
            "audited_by": "reviewer",
            "audited_at": "2026-08-25",
            "corpus_sha": "sha-test",
        },
    )


def test_audited_case_requires_reviewer_and_corpus_metadata() -> None:
    with pytest.raises(ValidationError):
        AuditedEvalCase(
            case_id="invalid",
            turns=[EvalTurn(query="Q")],
            expected_outcome=ExpectedOutcome.ANSWER_COMPLETE,
            audit={"status": AuditStatus.AUDITED},
        )


def test_pending_fixture_is_informational_and_not_gate_eligible() -> None:
    fixture = load_audited_case(Path("data/eval/audited/2026-law-follow-up.json"))
    assert fixture.audit.status == AuditStatus.PENDING
    result = verify_audited_case(
        fixture,
        answer="Một câu trả lời chưa được audit.",
        documents=[],
        observed_outcome=ExpectedOutcome.SAFE_STOP,
    )
    assert result.status == EvaluationStatus.INFORMATIONAL
    assert result.gate_eligible is False
    assert result.metadata["reason"] == "audit_pending"


def test_verifier_maps_claim_to_source_and_citation() -> None:
    case = _audited_case()
    documents = [
        {
            "source_id": "law-1",
            "anchor": "Điều 1",
            "official_url": "https://example.gov.vn/law-1",
            "excerpt": "Điều 1 quy định thời hạn 10 ngày.",
        }
    ]
    result = verify_audited_case(
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


def test_verifier_reports_retrieval_and_unsupported_claim_failures() -> None:
    result = verify_audited_case(
        _audited_case(),
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
