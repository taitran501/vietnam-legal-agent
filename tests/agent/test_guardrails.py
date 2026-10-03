"""Unit tests for AgentGuardrails."""

import pytest

from vietnam_legal_agent.agent.guardrails import AgentGuardrails
from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.domain.verification import VerificationPolicy
from vietnam_legal_agent.tools.verifier import (
    ClaimSupportResult,
    ClaimSupportVerifier,
    LegalCriticVerdict,
)


class FakeClaimVerifier(ClaimSupportVerifier):
    def __init__(self, supported: bool = True, reason_code: str = "ok") -> None:
        self.supported = supported
        self.reason_code = reason_code

    async def verify(
        self,
        answer: str,
        documents: list[DocumentRecord],
        *,
        query: str = "",
    ) -> ClaimSupportResult:
        _ = query
        return ClaimSupportResult(
            supported=self.supported,
            unsupported_claim_count=0 if self.supported else 1,
            unsupported_claim_indices=[] if self.supported else [1],
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


@pytest.mark.asyncio
async def test_guardrails_accept_mixed_corpus_and_official_web_evidence_for_legal_route():
    legal_document = DocumentRecord(
        content="Điều 36 quy định về việc đơn phương chấm dứt hợp đồng lao động.",
        document_id="labor-36",
        metadata={"legal_anchor": "Điều 36", "source": "Bộ luật Lao động 2019"},
        source="legal",
    )
    web_document = DocumentRecord(
        content="Nguồn chính thức hướng dẫn nghĩa vụ báo trước khi chấm dứt hợp đồng.",
        document_id="web:1:official-labor-source",
        metadata={
            "title": "Cổng văn bản chính thức",
            "official_url": "https://vbpl.vn/example",
            "authority": "official",
            "source_kind": "official_web",
        },
        source="web",
    )

    valid, reason, _, citations = await AgentGuardrails().check_output(
        "Theo Điều 36 [1], cần đối chiếu nghĩa vụ báo trước tại nguồn chính thức [2].",
        [legal_document, web_document],
        claim_verifier=FakeClaimVerifier(supported=True),
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        task_type=TaskType.LEGAL_LOOKUP,
        enforce_legal_safety_circuit_breaker=False,
    )

    assert valid is True
    assert reason == "ok"
    assert len(citations) == 2


@pytest.mark.asyncio
async def test_guardrails_reanchors_supported_critic_correction_without_citations():
    class Critic:
        async def review(
            self,
            query,
            answer,
            documents,
            *,
            source_version_only=False,
            verification_feedback=None,
        ):
            _ = query, answer, documents, source_version_only, verification_feedback
            return LegalCriticVerdict(
                approved=False,
                corrected_answer="Theo Điều 36, người sử dụng lao động phải tuân thủ nghĩa vụ báo trước.",
                reason_code="clarified_wording",
            )

    document = DocumentRecord(
        content="Điều 36 quy định quyền đơn phương chấm dứt hợp đồng và nghĩa vụ báo trước.",
        document_id="labor-36",
        metadata={"legal_anchor": "Điều 36", "Dieu": "Điều 36", "source": "Bộ luật Lao động 2019"},
        source="legal",
    )

    valid, reason, corrected, citations = await AgentGuardrails().check_output(
        "Theo Điều 36 [1], cần đối chiếu nghĩa vụ báo trước.",
        [document],
        claim_verifier=FakeClaimVerifier(supported=True),
        critic_reviewer=Critic(),
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        task_type=TaskType.LEGAL_LOOKUP,
    )

    assert valid is True
    assert reason == "ok"
    assert "[1]" in corrected
    assert len(citations) == 1


@pytest.mark.asyncio
async def test_guardrails_keeps_verified_draft_when_nonfatal_critic_correction_fails():
    class Critic:
        async def review(
            self,
            query,
            answer,
            documents,
            *,
            source_version_only=False,
            verification_feedback=None,
        ):
            _ = query, answer, documents, source_version_only, verification_feedback
            return LegalCriticVerdict(
                approved=False,
                fatal_error=False,
                materially_nonresponsive=False,
                verification_status="unsupported_claim",
                corrected_answer="Điều 25 quy định tối đa 180 ngày cho mọi công việc [1].",
                reason_code="critic_optional_correction",
            )

    class CorrectionFailsVerifier:
        calls = 0

        async def verify(self, answer, documents, *, query=""):
            _ = documents, query
            self.calls += 1
            supported = self.calls == 1
            return ClaimSupportResult(
                supported=supported,
                unsupported_claim_count=0 if supported else 1,
                unsupported_claim_indices=[] if supported else [1],
                reason_code="ok" if supported else "unsupported_correction",
            )

    document = DocumentRecord(
        content="Điều 25 quy định thời gian thử việc tối đa theo từng nhóm công việc.",
        document_id="labor-25",
        metadata={"legal_anchor": "Điều 25", "Dieu": "Điều 25", "source": "Bộ luật Lao động 2019"},
    )
    answer = "Thời gian thử việc tối đa phụ thuộc vào nhóm công việc theo Điều 25 [1]."
    verifier = CorrectionFailsVerifier()

    valid, reason, final_answer, citations = await AgentGuardrails().check_output(
        answer,
        [document],
        query="Thời gian thử việc tối đa là bao lâu?",
        claim_verifier=verifier,
        critic_reviewer=Critic(),
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        task_type=TaskType.LEGAL_LOOKUP,
        enforce_legal_safety_circuit_breaker=True,
    )

    assert valid is True
    assert reason == "ok"
    assert final_answer == answer
    assert citations[0]["document_id"] == "labor-25"
    assert verifier.calls == 2


@pytest.mark.asyncio
async def test_guardrails_passes_unsupported_claim_to_critic_for_targeted_repair():
    class Critic:
        received_feedback = None

        async def review(
            self,
            query,
            answer,
            documents,
            *,
            source_version_only=False,
            verification_feedback=None,
        ):
            _ = query, answer, documents, source_version_only
            self.received_feedback = verification_feedback
            return LegalCriticVerdict(
                approved=False,
                verification_status="unsupported_claim",
                corrected_answer="Theo Điều 26, lương thử việc ít nhất bằng 85% mức lương của công việc đó [1].",
                reason_code="targeted_repair",
            )

    document = DocumentRecord(
        content="Tiền lương của người lao động trong thời gian thử việc do hai bên thỏa thuận nhưng ít nhất phải bằng 85% mức lương của công việc đó.",
        document_id="labor-26",
        metadata={"legal_anchor": "Điều 26", "Dieu": "Điều 26", "source": "Bộ luật Lao động 2019"},
        source="legal",
    )
    critic = Critic()

    class FirstFailThenPassVerifier:
        calls = 0

        async def verify(self, answer, documents, *, query=""):
            _ = answer, documents, query
            self.calls += 1
            return ClaimSupportResult(
                supported=self.calls > 1,
                unsupported_claim_count=0 if self.calls > 1 else 1,
                unsupported_claim_indices=[] if self.calls > 1 else [1],
                reason_code="ok" if self.calls > 1 else "claim_1_not_supported_by_evidence",
            )

    verifier = FirstFailThenPassVerifier()

    valid, reason, corrected, _citations = await AgentGuardrails().check_output(
        "Công ty có thể trả dưới 85% nếu hai bên thỏa thuận [1].",
        [document],
        query="Tôi đang thử việc, công ty chỉ trả 80% mức lương thỏa thuận, có được không?",
        claim_verifier=verifier,
        critic_reviewer=critic,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        task_type=TaskType.LEGAL_LOOKUP,
        enforce_legal_safety_circuit_breaker=True,
    )

    assert valid is True
    assert reason == "ok"
    assert "85%" in corrected
    assert verifier.calls == 2
    assert critic.received_feedback == {
        "status": "unsupported_claim",
        "reason": "claim_1_not_supported_by_evidence",
        "unsupported_claims": [
            {
                "claim_index": 1,
                "text": "Công ty có thể trả dưới 85% nếu hai bên thỏa thuận [1].",
            }
        ],
        "unsupported_claim_count": 1,
    }


@pytest.mark.asyncio
async def test_guardrails_allows_one_verified_retry_when_first_critic_repair_still_fails():
    class SequenceVerifier:
        calls = 0

        async def verify(self, answer, documents, *, query=""):
            _ = answer, documents, query
            self.calls += 1
            supported = self.calls == 3
            return ClaimSupportResult(
                supported=supported,
                unsupported_claim_count=0 if supported else 1,
                unsupported_claim_indices=[] if supported else [1],
                reason_code="ok" if supported else "claim_1_not_supported_by_evidence",
            )

    class SequenceCritic:
        calls = 0

        async def review(
            self,
            query,
            answer,
            documents,
            *,
            source_version_only=False,
            verification_feedback=None,
        ):
            _ = query, answer, documents, source_version_only
            self.calls += 1
            if self.calls == 1:
                assert verification_feedback["unsupported_claim_count"] == 1
                corrected_answer = "Công ty có thể trả dưới 85% nếu hai bên đồng ý [1]."
            else:
                assert verification_feedback["unsupported_claims"][0]["claim_index"] == 1
                corrected_answer = (
                    "Theo Điều 26, lương thử việc do hai bên thỏa thuận nhưng không thấp hơn "
                    "85% mức lương của công việc đó [1]."
                )
            return LegalCriticVerdict(
                approved=False,
                verification_status="unsupported_claim",
                corrected_answer=corrected_answer,
                reason_code="targeted_repair",
            )

    document = DocumentRecord(
        content="Tiền lương của người lao động trong thời gian thử việc do hai bên thỏa thuận nhưng ít nhất phải bằng 85% mức lương của công việc đó.",
        document_id="labor-26",
        metadata={"legal_anchor": "Điều 26", "Dieu": "Điều 26", "source": "Bộ luật Lao động 2019"},
        source="legal",
    )
    verifier = SequenceVerifier()
    critic = SequenceCritic()

    valid, reason, corrected, _citations = await AgentGuardrails().check_output(
        "Công ty có thể trả dưới 85% nếu hai bên đồng ý theo Điều 26 [1].",
        [document],
        query="Tôi đang thử việc, công ty chỉ trả 80% mức lương thỏa thuận, có được không?",
        claim_verifier=verifier,
        critic_reviewer=critic,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        task_type=TaskType.LEGAL_LOOKUP,
        enforce_legal_safety_circuit_breaker=True,
    )

    assert valid is True
    assert reason == "ok"
    assert "không thấp hơn 85%" in corrected
    assert verifier.calls == 3
    assert critic.calls == 2
