"""Outer Guardrails for the Autonomous Agent.

Enforces input validation and post-generation citation/claim support checks,
reusing existing verification gateways.
"""

from __future__ import annotations

import logging
from typing import Any

from epr_agent.domain.models import DocumentRecord, TaskType
from epr_agent.tools.evidence import verify_citations
from epr_agent.tools.verifier import ClaimSupportVerifier, LegalCriticReviewer

logger = logging.getLogger(__name__)


class AgentGuardrails:
    """Outer verification layer executing before and after the agent loop."""

    @staticmethod
    def check_input(query: str) -> tuple[bool, str]:
        """Validate user input length and content constraints.

        Returns:
            (is_valid, reason_code)
        """
        cleaned = query.strip()
        if not cleaned:
            return False, "empty_query"
        if len(cleaned) > 3000:
            return False, "query_too_long"
        return True, "ok"

    @staticmethod
    async def check_output(
        answer: str,
        evidence: list[dict[str, Any] | DocumentRecord],
        *,
        query: str = "",
        claim_verifier: ClaimSupportVerifier | None = None,
        critic_reviewer: LegalCriticReviewer | None = None,
    ) -> tuple[bool, str, str, list[dict[str, Any]]]:
        """Verify that claims in the generated answer are grounded in retrieved evidence.

        Returns:
            (is_valid, reason_code, safe_fallback_or_corrected_answer, citations_list)
        """
        if not answer.strip():
            return False, "empty_answer", "Không thể tạo câu trả lời.", []

        # Convert dict evidence to DocumentRecord if needed
        docs: list[DocumentRecord] = [
            d if isinstance(d, DocumentRecord) else DocumentRecord.from_dict(d)
            for d in evidence
        ]

        import re
        has_citations = bool(re.search(r"\[\d+\]", answer))

        if not docs or not has_citations:
            # If no docs were retrieved but answer fabricated citation tags [1], [2], reject
            if not docs and has_citations:
                return (
                    False,
                    "no_evidence_for_claims",
                    "Tôi chưa tìm đủ căn cứ pháp lý để đưa ra câu trả lời được kiểm chứng.",
                    [],
                )
            # If no citations were made (conversational guidance, overview, clarification), pass through safely!
            return True, "ok", answer, []

        # 1. Structural citation validation
        valid, citations, reason = verify_citations(answer, docs, TaskType.LEGAL_LOOKUP)
        citations_dicts = [c.to_dict() for c in citations]

        if not valid:
            return (
                False,
                reason,
                "Tôi chưa thể xác minh đầy đủ câu trả lời từ tài liệu đã truy xuất.",
                citations_dicts,
            )

        # 2. Semantic claim support verification (if verifier is configured)
        if claim_verifier is not None:
            try:
                support = await claim_verifier.verify(answer, docs)
                if not support.supported:
                    return (
                        False,
                        f"claim_support_{support.reason_code}",
                        "Tôi chưa thể xác minh đầy đủ căn cứ của các nhận định pháp lý trong câu trả lời.",
                        citations_dicts,
                    )
            except Exception as exc:  # noqa: BLE001 - unverified claims must stop safely
                logger.warning("Claim support verifier failed: %s", exc)
                return (
                    False,
                    "claim_support_verifier_unavailable",
                    "Dịch vụ kiểm chứng căn cứ tạm thời chưa phản hồi.",
                    citations_dicts,
                )

        # 3. Legal Critic Reviewer audit (Peer reviewer agent)
        final_answer = answer
        if critic_reviewer is not None and docs:
            try:
                critic_verdict = await critic_reviewer.review(query, answer, docs)
                if critic_verdict.fatal_error or not critic_verdict.approved:
                    logger.warning("Critic reviewer rejected answer: %s", critic_verdict.critique)
                    return (
                        False,
                        "critic_legal_flaw_rejected",
                        "Câu trả lời chưa đạt tiêu chuẩn thẩm định tính chính xác của căn cứ pháp lý.",
                        citations_dicts,
                    )
                if critic_verdict.corrected_answer and critic_verdict.corrected_answer.strip():
                    final_answer = critic_verdict.corrected_answer
            except Exception as exc:  # noqa: BLE001
                logger.warning("Critic reviewer encountered exception: %s", exc)

        return True, "ok", final_answer, citations_dicts
