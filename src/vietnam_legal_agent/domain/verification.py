"""Shared runtime verification contracts.

Applicability is deliberately owned by :mod:`vietnam_legal_agent.domain.routes`.
These values describe only the outcome of checking an answer or its evidence
after a route has been selected, so runtime code does not need to depend on
the evaluation package.
"""

from __future__ import annotations

from enum import StrEnum


class VerificationStatus(StrEnum):
    """Canonical result of a verification step."""

    VERIFIED = "verified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"


class VerificationPolicy(StrEnum):
    """Verification contract selected by a route."""

    NONE = "none"
    LEGAL_CORPUS = "legal_corpus"
    WEB = "web"


def canonical_verification_status(
    status: VerificationStatus | str,
    *,
    supported: bool,
    reason_code: str = "",
) -> VerificationStatus:
    """Normalize verifier output without promoting a legacy fail-open result."""

    try:
        parsed = status if isinstance(status, VerificationStatus) else VerificationStatus(str(status))
    except ValueError:
        return VerificationStatus.VERIFICATION_UNAVAILABLE

    reason = str(reason_code or "").strip().casefold()
    if parsed is not VerificationStatus.VERIFIED:
        return parsed
    if reason in {
        "verifier_fallback",
        "critic_unavailable",
        "critic_disabled_or_empty_answer",
        "claim_support_verifier_unavailable",
    } or "timeout" in reason or "unavailable" in reason or "fallback" in reason:
        return VerificationStatus.VERIFICATION_UNAVAILABLE
    if reason in {
        "no_evidence_for_claims",
        "no_answer_or_evidence",
        "insufficient_evidence",
    }:
        return VerificationStatus.INSUFFICIENT_EVIDENCE
    if supported:
        return VerificationStatus.VERIFIED
    return VerificationStatus.UNSUPPORTED_CLAIM
