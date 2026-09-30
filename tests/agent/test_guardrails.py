"""Unit tests for AgentGuardrails."""

import pytest

from vietnam_legal_agent.agent.guardrails import AgentGuardrails
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.verifier import ClaimSupportResult, ClaimSupportVerifier


class FakeClaimVerifier(ClaimSupportVerifier):
    def __init__(self, supported: bool = True, reason_code: str = "ok") -> None:
        self.supported = supported
        self.reason_code = reason_code

    async def verify(self, answer: str, documents: list[DocumentRecord]) -> ClaimSupportResult:
        return ClaimSupportResult(
            supported=self.supported,
            reason_code=self.reason_code,
        )


def test_guardrails_check_input():
    guard = AgentGuardrails()
    valid, reason = guard.check_input("  ")
    assert valid is False
    assert reason == "empty_query"

    valid, reason = guard.check_input("x" * 3001)
    assert valid is False
    assert reason == "query_too_long"

    valid, reason = guard.check_input("Điều 25 Bộ luật Lao động quy định gì?")
    assert valid is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_guardrails_check_output_valid():
    guard = AgentGuardrails()
    doc = DocumentRecord(
        content="Điều 25 quy định thời gian thử việc của người lao động.",
        document_id="doc-1",
        metadata={"legal_anchor": "Điều 25", "source": "Bộ luật Lao động 2019"},
    )
    answer = "Thời gian thử việc được quy định tại Điều 25 [1]."

    valid, reason, _, citations = await guard.check_output(
        answer,
        [doc],
        claim_verifier=FakeClaimVerifier(supported=True),
    )
    assert valid is True
    assert reason == "ok"
    assert len(citations) == 1


@pytest.mark.asyncio
async def test_guardrails_check_output_unsupported_claim():
    guard = AgentGuardrails()
    doc = DocumentRecord(
        content="Điều 25 quy định thời gian thử việc của người lao động.",
        document_id="doc-1",
        metadata={"legal_anchor": "Điều 25", "source": "Bộ luật Lao động 2019"},
    )
    answer = "Thời gian thử việc được quy định tại Điều 25 [1]."

    valid, reason, safe_msg, _ = await guard.check_output(
        answer,
        [doc],
        claim_verifier=FakeClaimVerifier(supported=False, reason_code="fabricated_claim"),
    )
    assert valid is False
    assert "claim_support" in reason
    assert len(safe_msg) > 0
