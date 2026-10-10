"""Evaluation contracts and deterministic verification helpers."""

from vietnam_legal_agent.eval.contracts import (
    AuthoritativeSource,
    ClaimVerification,
    EvalTurn,
    EvaluationCase,
    EvaluationResult,
    EvaluationStatus,
    EvidenceMetadata,
    EvidenceStatus,
    ExpectedCitation,
    ExpectedClaim,
    ExpectedOutcome,
    FailureCode,
    SourceVerification,
    failure_code_for_verification_status,
)
from vietnam_legal_agent.eval.evidence_verifier import verify_evaluation_case

__all__ = [
    "AuthoritativeSource",
    "ClaimVerification",
    "EvalTurn",
    "EvaluationCase",
    "EvaluationResult",
    "EvaluationStatus",
    "EvidenceMetadata",
    "EvidenceStatus",
    "ExpectedCitation",
    "ExpectedClaim",
    "ExpectedOutcome",
    "FailureCode",
    "SourceVerification",
    "failure_code_for_verification_status",
    "verify_evaluation_case",
]
