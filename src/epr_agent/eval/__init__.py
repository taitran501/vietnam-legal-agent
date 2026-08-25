"""Evaluation contracts and deterministic verification helpers."""

from epr_agent.eval.contracts import (
    AuditedEvalCase,
    AuditMetadata,
    AuditStatus,
    AuthoritativeSource,
    ClaimVerification,
    EvalTurn,
    EvaluationResult,
    EvaluationStatus,
    ExpectedCitation,
    ExpectedClaim,
    ExpectedOutcome,
    FailureCode,
    SourceVerification,
)
from epr_agent.eval.evidence_verifier import verify_audited_case

__all__ = [
    "AuditMetadata",
    "AuditStatus",
    "AuditedEvalCase",
    "AuthoritativeSource",
    "ClaimVerification",
    "EvalTurn",
    "EvaluationResult",
    "EvaluationStatus",
    "ExpectedCitation",
    "ExpectedClaim",
    "ExpectedOutcome",
    "FailureCode",
    "SourceVerification",
    "verify_audited_case",
]
