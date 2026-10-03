"""LangGraph implementation of the bounded legal workflow."""

from __future__ import annotations

import logging
import time

from vietnam_legal_agent.domain.models import (
    Action,
    AgentState,
    TaskType,
    TerminationReason,
    append_action,
    documents_from_dict,
)
from vietnam_legal_agent.domain.routes import RouteType, route_spec
from vietnam_legal_agent.domain.verification import (
    VerificationPolicy,
    VerificationStatus,
    canonical_verification_status,
)
from vietnam_legal_agent.tools.evidence import (
    auto_anchor_citations_in_answer,
    propagate_list_item_citations,
    strip_citation_placeholders,
    verify_citations,
    verify_web_citations,
)

logger = logging.getLogger(__name__)

from vietnam_legal_agent.agent.workflow.contracts import (
    _append_source_version_caveat,
    _claim_verifier_feedback,
    _tool_result,
    _trace,
    _verification_status_for_reason,
)
from vietnam_legal_agent.agent.workflow.nodes.context import WorkflowNodeContext


class VerificationNodeHandlers(WorkflowNodeContext):
    async def verify(self, state: AgentState) -> AgentState:
        append_action(state, Action.VERIFY_CITATIONS)
        task = TaskType(state["task_type"])
        state["answer"] = strip_citation_placeholders(state.get("answer", ""))
        if task == TaskType.CHITCHAT:
            state["citation_valid"] = True
            return state
        docs = documents_from_dict(state.get("evidence"))
        route = route_spec(state.get("route", RouteType.LEGAL_LOOKUP.value))
        policy = route.verification_policy
        if policy is VerificationPolicy.LEGAL_CORPUS and self.deps.legal_readiness is not None:
            try:
                readiness = self.deps.legal_readiness.audit()
                state["legal_readiness_status"] = readiness.status.value
                state["legal_readiness_sha"] = readiness.manifest_sha256
                allowed, readiness_reason = self.deps.legal_readiness.allows_documents(docs)
            except Exception:  # noqa: BLE001 - final gate failures stop delivery
                allowed, readiness_reason = False, "legal_readiness_invalid"
            if not allowed:
                state["citation_valid"] = False
                state["citation_error"] = readiness_reason or "legal_readiness_invalid"
                state["verification_status"] = _verification_status_for_reason(
                    state["citation_error"], valid=False
                ).value
                state["citations"] = []
                _trace(
                    state,
                    reason_code=state["citation_error"],
                    payload={"reason": "final_legal_readiness_gate"},
                )
                return state
        if (
            policy is VerificationPolicy.LEGAL_CORPUS
            and self.deps.enforce_legal_safety_circuit_breaker
            and (self.deps.claim_verifier is None or self.deps.critic_reviewer is None)
        ):
            state["citation_valid"] = False
            state["citation_error"] = VerificationStatus.VERIFICATION_UNAVAILABLE.value
            state["verification_status"] = VerificationStatus.VERIFICATION_UNAVAILABLE.value
            state["citations"] = []
            _trace(
                state,
                reason_code=VerificationStatus.VERIFICATION_UNAVAILABLE.value,
                payload={"reason": "mandatory_verifier_dependency_missing"},
            )
            return state
        if policy is VerificationPolicy.WEB:
            valid, citations, reason = verify_web_citations(state.get("answer", ""), docs)
        else:
            valid, citations, reason = verify_citations(state.get("answer", ""), docs, task)

        # Every legal claim gets an independent support check.  If it rejects
        # a draft, one critic-authored correction may be tried, but that new
        # answer must pass the same structural and semantic checks.
        claim_support_passed = False
        critic_correction_passed = False
        if valid and policy is VerificationPolicy.LEGAL_CORPUS and self.deps.claim_verifier is not None:
            started = time.perf_counter()
            try:
                support = await self.deps.claim_verifier.verify(
                    state.get("answer", ""),
                    docs,
                    query=str(state.get("standalone_query") or state.get("query") or ""),
                )
                support_status = canonical_verification_status(
                    support.verification_status,
                    supported=support.supported,
                    reason_code=support.reason_code,
                )
                valid = bool(support.supported) and support_status is VerificationStatus.VERIFIED
                claim_support_passed = valid
                reason = (
                    "ok"
                    if valid
                    else (
                        VerificationStatus.VERIFICATION_UNAVAILABLE.value
                        if support_status is VerificationStatus.VERIFICATION_UNAVAILABLE
                        else f"claim_support_{support_status.value}"
                    )
                )
                state["verification_status"] = (
                    support_status.value
                    if valid
                    else (
                        VerificationStatus.VERIFICATION_UNAVAILABLE.value
                        if support_status is VerificationStatus.VERIFICATION_UNAVAILABLE
                        else support_status.value
                    )
                )
                _tool_result(
                    state,
                    "claim_support_verifier",
                    started,
                    ok=valid,
                    count=len(docs),
                    error="" if valid else reason,
                    metadata={
                        "model": support.model,
                        "token_usage": support.token_usage,
                        "reason": support.reason_code,
                    },
                )
                if (
                    not valid
                    and support_status is VerificationStatus.UNSUPPORTED_CLAIM
                    and support.corrected_answer.strip()
                ):
                    corrected_answer = strip_citation_placeholders(support.corrected_answer)
                    corrected_answer = auto_anchor_citations_in_answer(corrected_answer, docs)
                    corrected_answer = propagate_list_item_citations(corrected_answer)
                    corrected_valid, corrected_citations, corrected_reason = verify_citations(
                        corrected_answer,
                        docs,
                        task,
                    )
                    correction_started = time.perf_counter()
                    correction_supported = False
                    if corrected_valid:
                        try:
                            corrected_support = await self.deps.claim_verifier.verify(
                                corrected_answer,
                                docs,
                                query=str(state.get("standalone_query") or state.get("query") or ""),
                            )
                            corrected_status = canonical_verification_status(
                                corrected_support.verification_status,
                                supported=corrected_support.supported,
                                reason_code=corrected_support.reason_code,
                            )
                            correction_supported = (
                                corrected_support.supported and corrected_status is VerificationStatus.VERIFIED
                            )
                            corrected_reason = "ok" if correction_supported else corrected_status.value
                        except Exception:  # noqa: BLE001 - corrected text must pass the same independent gate
                            corrected_reason = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                    _tool_result(
                        state,
                        "claim_support_correction",
                        correction_started,
                        ok=correction_supported,
                        count=len(docs),
                        error="" if correction_supported else corrected_reason,
                        metadata={
                            "structural_citations_valid": corrected_valid,
                            "reason": support.reason_code,
                        },
                    )
                    if correction_supported:
                        state["answer"] = corrected_answer
                        citations = corrected_citations
                        valid = True
                        claim_support_passed = True
                        reason = "ok"
                        state["verification_status"] = VerificationStatus.VERIFIED.value
                if (
                    not valid
                    and support_status is VerificationStatus.UNSUPPORTED_CLAIM
                    and self.deps.critic_reviewer is not None
                ):
                    correction_started = time.perf_counter()
                    correction_supported = False
                    correction_reason = "critic_no_corrected_answer"
                    candidate_structural_valid = False
                    try:
                        critic_verdict = await self.deps.critic_reviewer.review(
                            str(state.get("standalone_query") or state.get("query") or ""),
                            state.get("answer", ""),
                            docs,
                            source_version_only=bool(
                                (state.get("evidence_assessment") or {}).get("source_version_only")
                            ),
                            verification_feedback=_claim_verifier_feedback(
                                state.get("answer", ""),
                                support,
                                support_status,
                            ),
                        )
                        candidate = str(critic_verdict.corrected_answer or "").strip()
                        if (
                            candidate
                            and not critic_verdict.fatal_error
                            and critic_verdict.verification_status
                            not in {
                                VerificationStatus.VERIFICATION_UNAVAILABLE,
                                VerificationStatus.INSUFFICIENT_EVIDENCE,
                            }
                        ):
                            candidate = strip_citation_placeholders(candidate)
                            candidate = auto_anchor_citations_in_answer(candidate, docs)
                            candidate = propagate_list_item_citations(candidate)
                            candidate_valid, candidate_citations, candidate_reason = verify_citations(
                                candidate,
                                docs,
                                task,
                            )
                            candidate_structural_valid = candidate_valid
                            correction_reason = candidate_reason
                            if candidate_valid:
                                corrected_support = await self.deps.claim_verifier.verify(
                                    candidate,
                                    docs,
                                    query=str(state.get("standalone_query") or state.get("query") or ""),
                                )
                                corrected_status = canonical_verification_status(
                                    corrected_support.verification_status,
                                    supported=corrected_support.supported,
                                    reason_code=corrected_support.reason_code,
                                )
                                correction_supported = (
                                    corrected_support.supported and corrected_status is VerificationStatus.VERIFIED
                                )
                                correction_reason = "ok" if correction_supported else corrected_status.value
                            if correction_supported:
                                state["answer"] = candidate
                                citations = candidate_citations
                                valid = True
                                claim_support_passed = True
                                critic_correction_passed = True
                                reason = "ok"
                                state["verification_status"] = VerificationStatus.VERIFIED.value
                    except Exception as exc:  # noqa: BLE001 - rejected claims remain blocked if repair fails
                        correction_reason = f"critic_correction_{type(exc).__name__}"
                        logger.info("Claim support critic correction unavailable: %s", type(exc).__name__)
                    _tool_result(
                        state,
                        "claim_support_critic_correction",
                        correction_started,
                        ok=correction_supported,
                        count=len(docs),
                        error="" if correction_supported else correction_reason,
                        metadata={
                            "structural_citations_valid": candidate_structural_valid,
                            "reason": support.reason_code,
                        },
                    )
                if not valid and support_status is VerificationStatus.UNSUPPORTED_CLAIM:
                    repair_started = time.perf_counter()
                    repair_supported = False
                    repair_structural_valid = False
                    repair_reason = "generation_repair_unavailable"
                    try:
                        repaired_answer = await self.deps.generation.repair(
                            state.get("answer", ""),
                            docs[:3],
                            task,
                            query=str(state.get("standalone_query") or state.get("query") or ""),
                        )
                        repaired_answer = strip_citation_placeholders(repaired_answer)
                        repaired_answer = auto_anchor_citations_in_answer(repaired_answer, docs[:3])
                        repaired_answer = propagate_list_item_citations(repaired_answer)
                        repair_structural_valid, repaired_citations, repair_reason = verify_citations(
                            repaired_answer,
                            docs[:3],
                            task,
                        )
                        if repair_structural_valid:
                            repaired_support = await self.deps.claim_verifier.verify(
                                repaired_answer,
                                docs[:3],
                                query=str(state.get("standalone_query") or state.get("query") or ""),
                            )
                            repaired_status = canonical_verification_status(
                                repaired_support.verification_status,
                                supported=repaired_support.supported,
                                reason_code=repaired_support.reason_code,
                            )
                            repair_supported = (
                                repaired_support.supported and repaired_status is VerificationStatus.VERIFIED
                            )
                            repair_reason = "ok" if repair_supported else repaired_status.value
                        if repair_supported:
                            state["answer"] = repaired_answer
                            citations = repaired_citations
                            valid = True
                            claim_support_passed = True
                            reason = "ok"
                            state["verification_status"] = VerificationStatus.VERIFIED.value
                    except Exception as exc:  # noqa: BLE001 - fallback stays behind both verification gates
                        repair_reason = f"generation_repair_{type(exc).__name__}"
                        logger.info("Claim support generation repair unavailable: %s", type(exc).__name__)
                    _tool_result(
                        state,
                        "claim_support_generation_repair",
                        repair_started,
                        ok=repair_supported,
                        count=min(3, len(docs)),
                        error="" if repair_supported else repair_reason,
                        metadata={
                            "structural_citations_valid": repair_structural_valid,
                            "reason": support.reason_code,
                        },
                    )
            except Exception as exc:  # noqa: BLE001 - unverified claims must stop safely
                valid = False
                reason = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                state["verification_status"] = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                _tool_result(
                    state,
                    "claim_support_verifier",
                    started,
                    ok=False,
                    count=len(docs),
                    error=reason,
                    metadata={"reason": "verifier_exception", "error_type": type(exc).__name__},
                )

        # Preserve the independently checked draft before asking the critic
        # for optional refinements. A bad optional rewrite must not erase an
        # answer that already passed both structural and claim-level checks.
        verified_answer = state.get("answer", "")
        verified_citations = list(citations)
        corrected = False
        if (
            valid
            and not critic_correction_passed
            and policy is VerificationPolicy.LEGAL_CORPUS
            and self.deps.critic_reviewer is not None
        ):
            critic_started = time.perf_counter()
            try:
                verdict = await self.deps.critic_reviewer.review(
                    state.get("standalone_query", state.get("query", "")),
                    state.get("answer", ""),
                    docs,
                    source_version_only=bool((state.get("evidence_assessment") or {}).get("source_version_only")),
                )
                critic_blocks_answer = (
                    verdict.fatal_error
                    or (verdict.materially_nonresponsive and not (verdict.corrected_answer or "").strip())
                    or verdict.verification_status
                    in {
                        VerificationStatus.VERIFICATION_UNAVAILABLE,
                        VerificationStatus.INSUFFICIENT_EVIDENCE,
                        VerificationStatus.UNSUPPORTED_CLAIM,
                    }
                    or (
                        not verdict.approved
                        and not (verdict.corrected_answer or "").strip()
                        and not claim_support_passed
                    )
                )
                _tool_result(
                    state,
                    "legal_critic",
                    critic_started,
                    ok=not critic_blocks_answer,
                    count=len(docs),
                    error=verdict.reason_code if critic_blocks_answer else "",
                    metadata={
                        "reason_code": verdict.reason_code,
                        "verification_status": verdict.verification_status.value,
                        "fatal_error": bool(verdict.fatal_error),
                        "materially_nonresponsive": bool(verdict.materially_nonresponsive),
                        "nonfatal_concern_retained": bool(not verdict.approved and not critic_blocks_answer),
                        "corrected_answer_present": bool((verdict.corrected_answer or "").strip()),
                    },
                )
                if verdict.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE:
                    valid = False
                    reason = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                    state["verification_status"] = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                elif verdict.verification_status is VerificationStatus.INSUFFICIENT_EVIDENCE:
                    valid = False
                    reason = VerificationStatus.INSUFFICIENT_EVIDENCE.value
                    state["verification_status"] = VerificationStatus.INSUFFICIENT_EVIDENCE.value
                elif verdict.fatal_error:
                    valid = False
                    reason = "critic_legal_flaw_rejected"
                    state["verification_status"] = VerificationStatus.UNSUPPORTED_CLAIM.value
                elif verdict.materially_nonresponsive and not (verdict.corrected_answer or "").strip():
                    valid = False
                    reason = "critic_answer_does_not_address_question"
                    state["verification_status"] = VerificationStatus.UNSUPPORTED_CLAIM.value
                elif verdict.corrected_answer and verdict.corrected_answer.strip():
                    corrected_answer = strip_citation_placeholders(verdict.corrected_answer)
                    corrected_answer = auto_anchor_citations_in_answer(corrected_answer, docs)
                    if (state.get("evidence_assessment") or {}).get("source_version_only"):
                        corrected_answer = _append_source_version_caveat(corrected_answer)
                    state["answer"] = corrected_answer
                    corrected = True
                elif not verdict.approved:
                    if claim_support_passed and verdict.verification_status is VerificationStatus.VERIFIED:
                        # Keep a claim-verified answer when the critic raises
                        # a nonfatal concern but supplies no correction. Do
                        # not turn a completeness preference into a safe stop.
                        logger.info(
                            "Keeping claim-verified answer after nonfatal critic concern: %s",
                            verdict.reason_code,
                        )
                    else:
                        valid = False
                        reason = "critic_legal_flaw_rejected"
                        state["verification_status"] = VerificationStatus.UNSUPPORTED_CLAIM.value
            except Exception as exc:  # noqa: BLE001 - critic outage must stop legal delivery
                valid = False
                reason = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                state["verification_status"] = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                _tool_result(
                    state,
                    "legal_critic",
                    critic_started,
                    ok=False,
                    count=len(docs),
                    error=reason,
                    metadata={"reason": "critic_exception", "error_type": type(exc).__name__},
                )

        # A corrected answer is a fresh output.  Re-check structure and claim
        # support once, without recursively invoking the critic.
        if valid and corrected:
            corrected_answer = state.get("answer", "")
            corrected_valid, corrected_citations, corrected_reason = verify_citations(
                corrected_answer,
                docs,
                task,
            )
            if not corrected_valid:
                valid = False
                reason = f"corrected_answer_{corrected_reason}"
            else:
                citations = corrected_citations
                if self.deps.claim_verifier is not None:
                    try:
                        corrected_support = await self.deps.claim_verifier.verify(
                            corrected_answer,
                            docs,
                            query=str(state.get("standalone_query") or state.get("query") or ""),
                        )
                        corrected_status = canonical_verification_status(
                            corrected_support.verification_status,
                            supported=corrected_support.supported,
                            reason_code=corrected_support.reason_code,
                        )
                        if corrected_status is not VerificationStatus.VERIFIED:
                            valid = False
                            reason = f"corrected_answer_{corrected_status.value}"
                    except Exception:  # noqa: BLE001 - corrected output must not bypass verification
                        valid = False
                        reason = VerificationStatus.VERIFICATION_UNAVAILABLE.value
                state["verification_status"] = (
                    VerificationStatus.VERIFIED.value if valid else VerificationStatus.UNSUPPORTED_CLAIM.value
                )
            if (
                not valid
                and not verdict.fatal_error
                and claim_support_passed
                and (
                    # A malformed/unusable critic rewrite cannot erase a draft
                    # that already passed both evidence gates. A structurally
                    # valid correction that is rejected by the independent
                    # support verifier remains fail-closed.
                    not corrected_valid
                    or (
                        not verdict.materially_nonresponsive
                        and verdict.verification_status
                        not in {
                            VerificationStatus.VERIFICATION_UNAVAILABLE,
                            VerificationStatus.INSUFFICIENT_EVIDENCE,
                            VerificationStatus.UNSUPPORTED_CLAIM,
                        }
                    )
                )
            ):
                # A critic rewrite that fails its own final citation/support
                # checks must not erase the original answer, which already
                # passed both independent gates. The original may be partial,
                # but a nonfatal failed rewrite is not grounds to discard it.
                logger.info(
                    "Discarding unverified nonfatal critic correction; retaining verified draft (%s)",
                    reason,
                )
                state["answer"] = verified_answer
                citations = verified_citations
                valid = True
                reason = "ok"
                corrected = False
                state["verification_status"] = VerificationStatus.VERIFIED.value
        state["citation_valid"] = valid
        state["citation_error"] = reason
        state["citations"] = [citation.to_dict() for citation in citations]
        state["verification_status"] = _verification_status_for_reason(reason, valid=valid).value
        _trace(
            state,
            reason_code="citations_verified" if valid else reason,
            payload={"citation_reason": reason, "citation_count": len(citations)},
        )
        return state

    async def safe_stop(self, state: AgentState) -> AgentState:
        append_action(state, Action.SAFE_STOP)
        citation_reason = str(state.get("citation_error") or "")
        evidence_reason = str((state.get("evidence_assessment") or {}).get("reason") or "")
        reason = citation_reason if citation_reason and citation_reason != "ok" else evidence_reason
        if state.get("route") == RouteType.RESEARCH_WEB.value and not state.get("evidence"):
            reason = "official_web_source_not_found"
        if state.get("termination_reason") == TerminationReason.INVALID_INPUT.value:
            state["answer"] = (
                "Câu hỏi cần có nội dung và không vượt quá 3.000 ký tự. Bạn hãy gửi lại câu hỏi ngắn gọn hơn."
            )
        elif citation_reason in {"legal_review_pending", "legal_readiness_invalid"}:
            state["answer"] = "Tính năng tư vấn pháp lý đang tạm dừng vì bộ căn cứ chưa hoàn tất thẩm định độc lập."
            state["termination_reason"] = TerminationReason.INSUFFICIENT_EVIDENCE.value
        elif reason == "official_web_source_not_found":
            state["answer"] = "Tôi chưa tìm thấy nguồn chính thức ngoài corpus khớp với điều hoặc văn bản bạn yêu cầu."
            state["termination_reason"] = TerminationReason.INSUFFICIENT_EVIDENCE.value
        elif reason == "superseded_or_unresolved_source":
            state["answer"] = (
                "Tôi đã tìm thấy văn bản liên quan, nhưng dữ liệu chưa xác nhận nội dung sau sửa đổi "
                "hoặc hiệu lực hiện hành. Vì vậy tôi chưa thể khẳng định đây là quy định đang áp dụng. "
                "Bạn có thể chọn “Tìm nguồn công khai” để đối chiếu nguồn chính thức."
            )
            state["termination_reason"] = TerminationReason.INSUFFICIENT_EVIDENCE.value
        elif reason == "current_law_status_unverified":
            state["answer"] = (
                "Tôi đã tìm thấy điều khoản được hỏi, nhưng kho dữ liệu không có thông tin xác nhận "
                "hiệu lực hiện hành hoặc các sửa đổi về sau. Bạn có thể chọn “Tìm nguồn công khai” "
                "để đối chiếu văn bản chính thức."
            )
            state["termination_reason"] = TerminationReason.INSUFFICIENT_EVIDENCE.value
        elif citation_reason and citation_reason != "ok":
            state["answer"] = "Tôi chưa thể xác minh đầy đủ câu trả lời từ tài liệu đã truy xuất."
            state["termination_reason"] = TerminationReason.CITATION_VERIFICATION_FAILED.value
        elif not state.get("is_legal_scope"):
            state["answer"] = "Câu hỏi hiện nằm ngoài phạm vi tra cứu pháp luật của hệ thống."
            state["termination_reason"] = TerminationReason.OUT_OF_SCOPE.value
        else:
            state["answer"] = "Tôi chưa tìm thấy đủ tài liệu liên quan để đưa ra kết luận an toàn."
            state["termination_reason"] = TerminationReason.INSUFFICIENT_EVIDENCE.value
        state["source"] = "error"
        state["evidence_status"] = "insufficient"
        if state.get("is_legal_scope") and not citation_reason and state.get("route") != RouteType.RESEARCH_WEB.value:
            state["available_actions"] = [RouteType.RESEARCH_WEB.value]
        state["safe_stop_reason"] = {
            "no_evidence": "missing_provision",
            "not_enough_docs": "missing_provision",
            "insufficient_evidence": "missing_provision",
            "content_too_short": "missing_provision",
            "missing_source_metadata": "missing_provision",
            "superseded_or_unresolved_source": "current_law_support_unverified",
            "explicit_article_not_found": "missing_provision",
            "explicit_anchor_not_found": "missing_provision",
            "source_relevance_mismatch": "source_relevance_mismatch",
            "relevance_check_failed": "insufficient_evidence",
            "current_law_status_unverified": "current_law_status_unverified",
            "required_anchor_parse_failed": "required_anchor_parse_failed",
            "legal_review_pending": "legal_review_pending",
            "legal_readiness_invalid": "legal_readiness_invalid",
            "current_law_support_unverified": "current_law_support_unverified",
            "verification_unavailable": "unavailable_dependencies",
            "official_web_source_not_found": "missing_provision",
            "claim_support_verifier_unavailable": "unavailable_dependencies",
            "claim_support_verification_unavailable": "unavailable_dependencies",
            "claim_support_insufficient_evidence": "missing_provision",
            "claim_support_unsupported_claim": "unsupported_claim",
            "answer_has_no_citation": "failed_citation_verification",
            "citation_out_of_range": "failed_citation_verification",
            "legal_claim_without_citation": "failed_citation_verification",
            "article_reference_not_in_evidence": "failed_citation_verification",
        }.get(str(reason or ""), state.get("termination_reason", ""))
        # Retrieval candidates remain in trace_events for audit, but rejected
        # candidates are not user-facing sources and cannot support a safe stop.
        state["evidence"] = []
        state["citations"] = []
        state["sources"] = []
        _trace(state, reason_code=state["termination_reason"], payload={"citation_error": reason or ""})
        return state

    def route_after_verify(self, state: AgentState) -> str:
        if not self.planner.within_iteration_budget(state):
            return "safe_stop"
        decision = self.planner.after_verification(state)
        if decision.action == Action.FINISH:
            return "finish"
        if decision.action == Action.REPAIR_ANSWER:
            return "repair"
        return "safe_stop"
