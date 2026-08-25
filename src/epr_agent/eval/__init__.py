"""Evaluation contracts and deterministic verification helpers."""

from epr_agent.eval.contracts import (
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
)
from epr_agent.eval.evidence_verifier import verify_evaluation_case

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
    "verify_evaluation_case",
]
