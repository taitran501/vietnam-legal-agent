"""Shared data and verification helpers for the V4 runtime."""

from __future__ import annotations

from typing import Any

from vietnam_legal_agent.agent.guardrails import AgentGuardrails
from vietnam_legal_agent.agent.runtime.presentation import _metadata
from vietnam_legal_agent.agent.workflow.contracts import WorkflowDependencies
from vietnam_legal_agent.domain.legal import parse_required_anchors
from vietnam_legal_agent.domain.models import (
    Action,
    AgentState,
    DocumentRecord,
    TaskType,
    TerminationReason,
    append_action,
)
from vietnam_legal_agent.domain.routes import RouteType
from vietnam_legal_agent.domain.tasks import (
    detect_legal_domain,
    is_context_dependent_query,
    latest_turn_requires_context,
    rewrite_follow_up,
)
from vietnam_legal_agent.domain.v4 import (
    AssessmentStatus,
    FactSource,
    FactValue,
    ResultType,
    WorkflowOutcome,
)
from vietnam_legal_agent.domain.verification import VerificationPolicy, VerificationStatus
from vietnam_legal_agent.tools.evidence import document_matches_anchor
from vietnam_legal_agent.tools.legal_readiness import LegalReadinessProvider, ReadinessStatus


def _fact_values(raw: dict[str, Any] | None) -> dict[str, FactValue]:
    result: dict[str, FactValue] = {}
    for key, value in (raw or {}).items():
        target_key = str(key)
        if isinstance(value, dict) and "value" in value:
            try:
                stored_value = dict(value)
                # Facts entered through the retired panel were still user
                # supplied. Preserve them as ordinary conversation facts.
                if stored_value.get("source") == "case_panel":
                    stored_value["source"] = FactSource.USER_TURN.value
                fact = FactValue.model_validate(stored_value)
                result[target_key] = fact
                continue
            except (TypeError, ValueError):
                # Legacy V3 facts have no typed provenance and are converted
                # below to explicitly unverified values.
                continue
        text = " ".join(str(value or "").split())
        if text:
            result[target_key] = FactValue(
                value=text,
                source=FactSource.USER_TURN,
                source_turn="legacy-v3-migration",
                confidence=0.5,
                verified=False,
            )

    # Preserve every legacy fact under its original key. Reinterpreting old
    # user facts into domain-specific slots could silently change their meaning.
    return result


def _hydrate_persisted_case(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Preserve conversational facts while dropping retired form metadata."""

    if raw is None:
        return None
    payload = dict(raw)
    if payload.get("task_type") not in {
        TaskType.CASE_ASSESSMENT.value,
        TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
    }:
        # Old persisted task labels from previous app versions are normalized
        # at the storage boundary; the runtime uses only generic legal tasks.
        payload["task_type"] = TaskType.CASE_ASSESSMENT.value
    payload.pop("fields", None)
    payload.pop("form_version", None)
    payload.pop("validation_errors", None)
    payload.pop("submission_blocked_reason", None)
    payload.pop("completed_count", None)
    payload.pop("required_count", None)
    return payload


def _metadata_v4(state: AgentState) -> dict[str, Any]:
    data = _metadata(state)
    query = str(state.get("standalone_query") or state.get("query") or "")
    data.update(
        {
            "outcome": state.get("outcome", WorkflowOutcome.FAILED.value),
            "result_type": state.get("result_type", ResultType.NONE.value),
            "required_issues": state.get("required_issues", []),
            "covered_issues": state.get("covered_issues", []),
            "rule_id": "",
            "effective_dates": {},
            "legal_domain": detect_legal_domain(query),
        }
    )
    return data


def _apply_context_metadata(state: AgentState, snapshot: Any) -> None:
    """Apply one context contract to both case and delegated lookup paths."""

    history = list(snapshot.history or [])
    query = str(state.get("query") or "").strip()
    state["history"] = history
    state["history_summary"] = snapshot.summary
    state["active_case"] = snapshot.active_case
    state["context_loaded"] = True
    state["history_messages"] = len(history)

    rewritten = rewrite_follow_up(query, history, snapshot.active_case)
    state["is_follow_up"] = bool(rewritten and rewritten.casefold() != query.casefold())
    state["standalone_query"] = rewritten or query


def _clarify_unresolved_follow_up(state: AgentState, snapshot: Any) -> AgentState | None:
    """Ask for a subject when an elliptical query has no usable prior context."""

    query = str(state.get("query") or "")
    history = list(snapshot.history or [])
    if not is_context_dependent_query(query) or snapshot.active_case:
        return None
    unresolved_previous_turn = latest_turn_requires_context(history)
    if history and not unresolved_previous_turn:
        return None

    answer = (
        "Lượt trước chưa có đủ căn cứ phù hợp để kết luận, nên câu hỏi tiếp theo chưa xác định rõ nội dung cần tra cứu. "
        "Bạn hãy nêu tên văn bản, lĩnh vực hoặc vấn đề cụ thể để tôi tra cứu lại."
        if unresolved_previous_turn
        else "Câu hỏi tiếp theo chưa cho biết rõ nội dung cần tra cứu. "
        "Bạn hãy nêu tên văn bản, lĩnh vực hoặc vấn đề cụ thể để tôi kiểm tra căn cứ pháp lý phù hợp."
    )
    state.update(
        {
            "route": RouteType.LEGAL_LOOKUP.value,
            "task_type": TaskType.LEGAL_LOOKUP.value,
            "answer": answer,
            "source": "follow_up",
            "source_scope": "legal_corpus",
            "outcome": WorkflowOutcome.NEEDS_INFORMATION.value,
            "result_type": ResultType.NONE.value,
            "termination_reason": TerminationReason.AWAITING_USER_INPUT.value,
            "clarification_required": True,
            "awaiting_user_input": True,
            "is_follow_up": True,
            "available_actions": [],
            "evidence": [],
            "citations": [],
            "sources": [],
            "citation_valid": False,
            "citation_error": "awaiting_user_input",
            "safe_stop_reason": "",
            "missing_facts": [],
        }
    )
    append_action(state, Action.UNDERSTAND_TASK)
    append_action(state, Action.ASK_USER)
    append_action(state, Action.FINISH)
    return state


def _terminal_safe_stop(
    state: AgentState,
    *,
    route: RouteType,
    outcome: WorkflowOutcome,
    termination: TerminationReason,
    answer: str,
    source_scope: str,
    available_actions: list[str] | None = None,
    reason_code: str,
) -> AgentState:
    """Finish a bounded route before retrieval when its contract requires it."""

    state["route"] = route.value
    state["source_scope"] = source_scope
    state["answer"] = answer
    state["source"] = "error"
    state["outcome"] = outcome.value
    state["result_type"] = ResultType.NONE.value
    state["termination_reason"] = termination.value
    state["evidence_status"] = "not_evaluated" if outcome == WorkflowOutcome.OUT_OF_SCOPE else "insufficient"
    state["available_actions"] = list(available_actions or [])
    state["citation_valid"] = False
    state["citation_error"] = reason_code
    if outcome is not WorkflowOutcome.OUT_OF_SCOPE:
        state["verification_status"] = (
            VerificationStatus.VERIFICATION_UNAVAILABLE.value
            if reason_code in {"required_anchor_parse_failed", "legal_readiness_invalid", "verification_unavailable"}
            or "unavailable" in reason_code
            else VerificationStatus.UNSUPPORTED_CLAIM.value
            if "unsupported_claim" in reason_code
            else VerificationStatus.INSUFFICIENT_EVIDENCE.value
        )
    state["safe_stop_reason"] = {
        "outside_registered_corpus": "out_of_scope",
        "explicit_no_evidence_signal": "missing_provision",
    }.get(reason_code, reason_code)
    if state.get("trace_events"):
        state["trace_events"][-1]["reason_code"] = reason_code
        state["trace_events"][-1]["payload"] = {
            "route": route.value,
            "outcome": outcome.value,
            "source_scope": source_scope,
        }
    append_action(state, Action.FINISH)
    return state


def _current_law_support_stop(state: AgentState, *, route: RouteType) -> AgentState:
    return _terminal_safe_stop(
        state,
        route=route,
        outcome=WorkflowOutcome.INSUFFICIENT_EVIDENCE,
        termination=TerminationReason.INSUFFICIENT_EVIDENCE,
        answer=(
            "Tôi đã tìm thấy văn bản liên quan, nhưng dữ liệu chưa xác nhận nội dung sau sửa đổi "
            "hoặc hiệu lực hiện hành. Vì vậy tôi chưa thể kết luận nghĩa vụ đang áp dụng. "
            "Bạn có thể chọn “Tìm nguồn công khai” để đối chiếu nguồn chính thức."
        ),
        source_scope="legal_corpus",
        available_actions=[RouteType.RESEARCH_WEB.value],
        reason_code="current_law_support_unverified",
    )


def _matches_required_anchor(document: DocumentRecord, raw_anchor: str) -> bool:
    """Match an issue anchor against the source address, never body mentions."""

    anchors, invalid = parse_required_anchors([raw_anchor])
    return not invalid and any(document_matches_anchor(document, anchor) for anchor in anchors)


def _documents_readiness_stop(
    state: AgentState,
    provider: LegalReadinessProvider | None,
    *,
    route: RouteType,
    documents: list[DocumentRecord],
) -> AgentState | None:
    """Require every document used by a case result to be signed and current."""

    if provider is None:
        return None
    try:
        audit = provider.audit()
        allowed, reason = provider.allows_documents(documents)
    except Exception:  # noqa: BLE001 - gate failures are fail closed
        audit = None
        allowed, reason = False, "legal_readiness_invalid"
    if audit is not None:
        state["legal_readiness_status"] = audit.status.value
        state["legal_readiness_sha"] = audit.manifest_sha256
    else:
        state["legal_readiness_status"] = ReadinessStatus.INVALID.value
        state["legal_readiness_sha"] = provider.manifest_sha256
    if allowed:
        return None
    return _terminal_safe_stop(
        state,
        route=route,
        outcome=WorkflowOutcome.INSUFFICIENT_EVIDENCE,
        termination=TerminationReason.INSUFFICIENT_EVIDENCE,
        answer="Tôi chưa thể sử dụng các nguồn này vì chưa xác minh được trạng thái pháp lý của chúng.",
        source_scope="legal_corpus",
        available_actions=[],
        reason_code=reason or "legal_readiness_invalid",
    )


async def _verify_case_delivery(
    state: AgentState,
    *,
    deps: WorkflowDependencies,
    route: RouteType,
) -> AgentState | None:
    """Apply the same final verification contract to deterministic case cards."""

    documents = [DocumentRecord.from_dict(document) for document in state.get("evidence") or []]
    readiness_block = _documents_readiness_stop(
        state,
        deps.legal_readiness,
        route=route,
        documents=documents,
    )
    if readiness_block is not None:
        return readiness_block
    answer = str(state.get("answer") or "").strip()
    if documents and "[" not in answer:
        # Case cards keep their detailed result in structured state, but the
        # assistant message still needs one structural citation for the final
        # delivery verifier to audit.
        answer = f"{answer} [1]"
        state["answer"] = answer
    passed, reason, verified_answer, citations = await AgentGuardrails.check_output(
        answer,
        documents,
        query=str(state.get("standalone_query") or state.get("query") or ""),
        require_evidence=True,
        claim_verifier=deps.claim_verifier,
        critic_reviewer=deps.critic_reviewer,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        enforce_legal_safety_circuit_breaker=deps.enforce_legal_safety_circuit_breaker,
    )
    if passed:
        state["answer"] = verified_answer
        state["citations"] = citations
        state["citation_valid"] = True
        state["citation_error"] = "ok"
        state["verification_status"] = "verified"
        return None
    blocked = _terminal_safe_stop(
        state,
        route=route,
        outcome=WorkflowOutcome.INSUFFICIENT_EVIDENCE,
        termination=TerminationReason.INSUFFICIENT_EVIDENCE,
        answer="Tôi chưa thể phát hành kết quả vì chưa xác minh đầy đủ căn cứ pháp lý.",
        source_scope="legal_corpus",
        available_actions=[],
        reason_code=reason or "verification_unavailable",
    )
    blocked["evidence"] = []
    blocked["citations"] = []
    blocked["assessment"] = None
    blocked["checklist"] = []
    blocked["verification_status"] = (
        "verification_unavailable"
        if reason in {"verification_unavailable", "legal_readiness_invalid"} or "unavailable" in reason
        else "insufficient_evidence"
        if reason in {"insufficient_evidence", "legal_review_pending"}
        else "unsupported_claim"
    )
    return blocked


def _general_decision_status(status: str) -> AssessmentStatus:
    """Map a multi-domain rule-engine status onto the closed-loop vocabulary."""

    if status == "needs_information":
        return AssessmentStatus.NEEDS_INFORMATION
    if "not_met" in status or "out_of_scope" in status:
        return AssessmentStatus.LIKELY_OUT_OF_SCOPE
    if status in {"", "evaluated_general"}:
        return AssessmentStatus.CANNOT_DETERMINE
    return AssessmentStatus.LIKELY_IN_SCOPE
