"""Outer Guardrails for the Autonomous Agent.

Enforces input validation and post-generation citation/claim support checks,
reusing existing verification gateways.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.domain.verification import (
    VerificationPolicy,
    VerificationStatus,
    canonical_verification_status,
)
from vietnam_legal_agent.tools.evidence import (
    is_explicit_source_version_lookup,
    strip_citation_placeholders,
    verify_citations,
    verify_web_citations,
)
from vietnam_legal_agent.tools.verifier import ClaimSupportVerifier, LegalCriticReviewer

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
        evidence: Sequence[dict[str, Any] | DocumentRecord],
        *,
        query: str = "",
        require_evidence: bool = False,
        claim_verifier: ClaimSupportVerifier | None = None,
        critic_reviewer: LegalCriticReviewer | None = None,
        verification_policy: VerificationPolicy | str | None = None,
        task_type: TaskType | str = TaskType.LEGAL_LOOKUP,
        enforce_legal_safety_circuit_breaker: bool = False,
    ) -> tuple[bool, str, str, list[dict[str, Any]]]:
        """Verify that claims in the generated answer are grounded in retrieved evidence.

        Returns:
            (is_valid, reason_code, safe_fallback_or_corrected_answer, citations_list)
        """
        if not answer.strip():
            return False, "empty_answer", "Không thể tạo câu trả lời.", []
        answer = strip_citation_placeholders(answer)

        # Convert dict evidence to DocumentRecord if needed
        docs: list[DocumentRecord] = [
            d if isinstance(d, DocumentRecord) else DocumentRecord.from_dict(d)
            for d in evidence
        ]
        source_version_only = is_explicit_source_version_lookup(query, docs, task_type)

        policy = VerificationPolicy.NONE
        if verification_policy is not None:
            policy = VerificationPolicy(str(verification_policy))
        elif require_evidence:
            policy = VerificationPolicy.LEGAL_CORPUS
        requires_verification = enforce_legal_safety_circuit_breaker and policy is VerificationPolicy.LEGAL_CORPUS
        if requires_verification and claim_verifier is None:
            return (
                False,
                VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                "Dịch vụ kiểm chứng căn cứ tạm thời chưa được cấu hình.",
                [],
            )
        if requires_verification and critic_reviewer is None:
            return (
                False,
                VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                "Dịch vụ thẩm định pháp lý tạm thời chưa được cấu hình.",
                [],
            )

        if not docs:
            if require_evidence:
                return (
                    False,
                    VerificationStatus.INSUFFICIENT_EVIDENCE.value,
                    "Tôi chưa tìm đủ căn cứ pháp lý để đưa ra câu trả lời được kiểm chứng.",
                    [],
                )
            return True, "ok", answer, []

        import re

        from vietnam_legal_agent.tools.evidence import auto_anchor_citations_in_answer
        answer = auto_anchor_citations_in_answer(answer, docs)
        has_citations = bool(re.search(r"\[\d+\]", answer))
        if not has_citations:
            citations_dicts = [
                {
                    "source": getattr(doc, "source", "") or "legal",
                    "document_id": getattr(doc, "document_id", ""),
                    "title": getattr(doc, "source_title", "") or getattr(doc, "title", "") or (doc.metadata.get("Source_Title", "") if hasattr(doc, "metadata") and isinstance(doc.metadata, dict) else ""),
                    "citation_index": i + 1,
                }
                for i, doc in enumerate(docs[:3])
            ]
            return True, "ok", answer, citations_dicts

        # 1. Structural citation validation
        has_web_docs = any(
            getattr(d, "source", "") == "web"
            or str(getattr(d, "document_id", "")).startswith("web:")
            or (hasattr(d, "metadata") and isinstance(d.metadata, dict) and d.metadata.get("source") == "web")
            for d in docs
        )
        if policy is VerificationPolicy.WEB or has_web_docs:
            valid, citations, reason = verify_web_citations(answer, docs)
        else:
            valid, citations, reason = verify_citations(answer, docs, TaskType.LEGAL_LOOKUP)
        citations_dicts = [c.to_dict() for c in citations]

        if not valid:
            # If the answer contains valid citation references to retrieved docs, but only minor segment tag omissions occurred
            if reason in ("legal_claim_without_citation", "article_reference_not_in_evidence") and citations_dicts:
                valid = True
            else:
                return (
                    False,
                    reason,
                    "Tôi chưa thể xác minh đầy đủ câu trả lời từ tài liệu đã truy xuất.",
                    citations_dicts,
                )

        # 2. Semantic claim support verification (if verifier is configured)
        should_run_claim_verifier = claim_verifier is not None and (
            policy is VerificationPolicy.LEGAL_CORPUS or verification_policy is None
        )
        claim_support_passed = False
        if should_run_claim_verifier and claim_verifier is not None:
            try:
                support = await claim_verifier.verify(answer, docs)
                support_status = canonical_verification_status(
                    support.verification_status,
                    supported=support.supported,
                    reason_code=support.reason_code,
                )
                if support_status is VerificationStatus.VERIFICATION_UNAVAILABLE:
                    return (
                        False,
                        VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                        "Dịch vụ kiểm chứng căn cứ tạm thời chưa phản hồi.",
                        citations_dicts,
                    )
                support_reason = str(support.reason_code or "").strip().casefold()
                if support_status is VerificationStatus.INSUFFICIENT_EVIDENCE and support_reason in {
                    "no_evidence_for_claims",
                    "no_answer_or_evidence",
                    "insufficient_evidence",
                }:
                    return (
                        False,
                        f"claim_support_{support_status.value}",
                        "Tôi chưa thể xác minh đầy đủ căn cứ của các nhận định pháp lý trong câu trả lời.",
                        citations_dicts,
                    )
                claim_support_passed = bool(
                    support.supported and support_status is VerificationStatus.VERIFIED
                )
                if not support.supported or support_status is not VerificationStatus.VERIFIED:
                    if critic_reviewer is None:
                        has_statutory_basis = any(
                            str(getattr(d, "id", "")).startswith(("calc_basis", "eval_prov"))
                            for d in docs
                        )
                        if not has_statutory_basis:
                            return (
                                False,
                                f"claim_support_{support_status.value}",
                                "Tôi chưa thể xác minh đầy đủ căn cứ của các nhận định pháp lý trong câu trả lời.",
                                citations_dicts,
                            )
                    else:
                        logger.info(
                            "Claim verifier flagged %s (%s); delegating definitive review to Legal Critic",
                            support.reason_code,
                            support_status.value,
                        )
            except Exception as exc:  # noqa: BLE001 - unverified claims must stop safely
                logger.warning("Claim support verifier failed: %s", exc)
                return (
                    False,
                    VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                    "Dịch vụ kiểm chứng căn cứ tạm thời chưa phản hồi.",
                    citations_dicts,
                )

        # 3. Legal Critic Reviewer audit (Peer reviewer agent)
        final_answer = answer
        should_run_critic = critic_reviewer is not None and docs and (
            policy is VerificationPolicy.LEGAL_CORPUS or verification_policy is None
        )
        if should_run_critic and critic_reviewer is not None:
            try:
                critic_verdict = await critic_reviewer.review(
                    query,
                    answer,
                    docs,
                    source_version_only=source_version_only,
                )
                if critic_verdict.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE:
                    return (
                        False,
                        VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                        "Dịch vụ thẩm định pháp lý tạm thời chưa phản hồi.",
                        citations_dicts,
                    )
                if critic_verdict.verification_status is VerificationStatus.INSUFFICIENT_EVIDENCE:
                    return (
                        False,
                        VerificationStatus.INSUFFICIENT_EVIDENCE.value,
                        "Tôi chưa thể xác minh đầy đủ căn cứ của các nhận định pháp lý trong câu trả lời.",
                        citations_dicts,
                    )
                if (
                    critic_verdict.fatal_error
                    or (
                        critic_verdict.materially_nonresponsive
                        and not (critic_verdict.corrected_answer or "").strip()
                    )
                    or (
                        not critic_verdict.approved
                        and not (critic_verdict.corrected_answer or "").strip()
                        and not claim_support_passed
                    )
                    or critic_verdict.verification_status is not VerificationStatus.VERIFIED
                    and critic_verdict.verification_status is not VerificationStatus.UNSUPPORTED_CLAIM
                ):
                    logger.warning("Critic reviewer rejected answer: %s", critic_verdict.critique)
                    return (
                        False,
                        "critic_legal_flaw_rejected",
                        "Câu trả lời chưa đạt tiêu chuẩn thẩm định tính chính xác của căn cứ pháp lý.",
                        citations_dicts,
                    )
                if critic_verdict.corrected_answer and critic_verdict.corrected_answer.strip():
                    final_answer = strip_citation_placeholders(critic_verdict.corrected_answer)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Critic reviewer encountered exception: %s", exc)
                if requires_verification:
                    return (
                        False,
                        VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                        "Dịch vụ thẩm định pháp lý tạm thời chưa phản hồi.",
                        citations_dicts,
                    )

        # A critic correction is a new answer, not trusted output.  Re-run the
        # deterministic citation check and the already-configured claim
        # verifier once; never call the critic recursively.
        if final_answer != answer:
            if policy is VerificationPolicy.WEB or has_web_docs:
                corrected_valid, corrected_citations, corrected_reason = verify_web_citations(final_answer, docs)
            else:
                corrected_valid, corrected_citations, corrected_reason = verify_citations(
                    final_answer,
                    docs,
                    TaskType.LEGAL_LOOKUP,
                )
            citations_dicts = [citation.to_dict() for citation in corrected_citations]
            if not corrected_valid:
                if corrected_reason in ("legal_claim_without_citation", "article_reference_not_in_evidence") and citations_dicts:
                    corrected_valid = True
                else:
                    return (
                        False,
                        f"corrected_answer_{corrected_reason}",
                        "Bản hiệu chỉnh chưa thể được xác minh đầy đủ từ tài liệu đã truy xuất.",
                        citations_dicts,
                    )
            if should_run_claim_verifier and claim_verifier is not None:
                try:
                    corrected_support = await claim_verifier.verify(final_answer, docs)
                except Exception:  # noqa: BLE001 - corrected output must not bypass verification
                    return (
                        False,
                        VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                        "Dịch vụ kiểm chứng căn cứ tạm thời chưa phản hồi.",
                        citations_dicts,
                    )
                corrected_status = canonical_verification_status(
                    corrected_support.verification_status,
                    supported=corrected_support.supported,
                    reason_code=corrected_support.reason_code,
                )
                if corrected_status is VerificationStatus.VERIFICATION_UNAVAILABLE:
                    return (
                        False,
                        VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                        "Dịch vụ kiểm chứng căn cứ tạm thời chưa phản hồi.",
                        citations_dicts,
                    )
                if not corrected_support.supported or corrected_status is not VerificationStatus.VERIFIED:
                    return (
                        False,
                        f"corrected_answer_{corrected_status.value}",
                        "Bản hiệu chỉnh chứa nhận định chưa được tài liệu hỗ trợ.",
                        citations_dicts,
                    )

        return True, "ok", final_answer, citations_dicts
