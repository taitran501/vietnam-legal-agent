"""Pipeline V4 legal workflow with one evidence-backed path for all domains."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from vietnam_legal_agent.agent.graph import WorkflowDependencies, create_initial_state, run_workflow
from vietnam_legal_agent.agent.guardrails import AgentGuardrails
from vietnam_legal_agent.agent.runtime import (
    WorkflowRuntime,
    _documents_for_api,
    _metadata,
    _source_snapshots,
    split_verified_answer_for_stream,
)
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
    classify_route,
    detect_legal_domain,
    has_explicit_no_evidence_signal,
    is_context_dependent_query,
    latest_turn_requires_context,
    rewrite_follow_up,
)
from vietnam_legal_agent.domain.v4 import (
    AssessmentStatus,
    FactSource,
    FactValue,
    InteractionSource,
    ResultType,
    TurnOperation,
    WorkflowOutcome,
)
from vietnam_legal_agent.domain.verification import VerificationPolicy, VerificationStatus
from vietnam_legal_agent.tools.evidence import (
    document_matches_anchor,
)
from vietnam_legal_agent.tools.legal_readiness import LegalReadinessProvider, ReadinessStatus

logger = logging.getLogger(__name__)
_PHASES = {
    Action.VALIDATE_INPUT.value: ("understand", "Hiểu yêu cầu"),
    Action.LOAD_CONTEXT.value: ("understand", "Hiểu yêu cầu"),
    Action.UNDERSTAND_TASK.value: ("understand", "Hiểu yêu cầu"),
    Action.ASK_USER.value: ("collect_information", "Thu thập thông tin"),
    Action.RETRIEVE_LEGAL.value: ("check_evidence", "Kiểm tra căn cứ"),
    Action.EVALUATE_EVIDENCE.value: ("check_evidence", "Kiểm tra căn cứ"),
    Action.COMPOSE_ANSWER.value: ("compose", "Soạn kết quả"),
    Action.VERIFY_CITATIONS.value: ("compose", "Soạn kết quả"),
    Action.FINISH.value: ("compose", "Soạn kết quả"),
}


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
        if reason in {"verification_unavailable", "legal_readiness_invalid"}
        or "unavailable" in reason
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


class V4WorkflowRuntime(WorkflowRuntime):
    """Runtime selected by ``AGENT_PIPELINE_VERSION=pipeline-v4``."""

    async def _initial(self, **kwargs: Any) -> AgentState:
        # ``create_initial_state`` intentionally knows only the stable V3
        # request surface.  V4 request controls stay in state after that
        # boundary instead of leaking into the old graph initializer.
        initial_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in {"query", "user_id", "conversation_id", "legacy_session_id", "mode", "trace_id"}
        }
        state = await create_initial_state(deps=self.deps, **initial_kwargs)
        state["pipeline_version"] = "pipeline-v4"
        state["turn_id"] = str(kwargs.get("turn_id") or "")
        state["user_message_id"] = str(kwargs.get("user_message_id") or "")
        state["assistant_message_id"] = str(kwargs.get("assistant_message_id") or "")
        state["target_assistant_message_id"] = kwargs.get("target_assistant_message_id")
        state["turn_status"] = str(kwargs.get("turn_status") or "pending")
        state["outcome"] = WorkflowOutcome.FAILED.value
        state["result_type"] = ResultType.NONE.value
        state["operation"] = str(kwargs.get("operation") or TurnOperation.MESSAGE.value)
        state["intent_hint"] = str(kwargs.get("intent_hint") or "auto")
        state["interaction_source"] = str(kwargs.get("interaction_source") or InteractionSource.COMPOSER.value)
        replay_defaults = {
            "query_mode": state.get("mode", "auto"),
            "intent": state.get("intent_hint", "auto"),
            "operation": state.get("operation", TurnOperation.MESSAGE.value),
            "interaction_source": state.get("interaction_source", InteractionSource.COMPOSER.value),
        }
        legacy_replay_metadata = dict(kwargs.get("replay_metadata") or {})
        legacy_replay_metadata.pop("case_patch", None)
        legacy_replay_metadata.pop("fact_updates", None)
        replay_defaults.update(legacy_replay_metadata)
        if replay_defaults.get("interaction_source") not in {"composer", "quick_action"}:
            replay_defaults["interaction_source"] = InteractionSource.COMPOSER.value
        state["replay_metadata"] = replay_defaults
        from vietnam_legal_agent.config import get_settings

        settings = get_settings()
        state["corpus_as_of_date"] = str(settings.corpus_as_of_date or "")
        state["preview"] = settings.corpus_runtime_mode == "preview"
        state["rule_id"] = ""
        return state

    async def _begin_durable_turn(
        self, request_kwargs: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Create the durable placeholder and restore server-owned replay inputs."""

        begin_turn = getattr(self.deps.history, "begin_turn", None)
        if not callable(begin_turn):
            return None, request_kwargs

        request_operation = str(request_kwargs.get("operation") or TurnOperation.MESSAGE.value)
        turn_id = str(request_kwargs.get("turn_id") or trace_id or uuid4())
        replay_metadata = {
            "query_mode": str(request_kwargs.get("mode") or "auto"),
            "intent": str(request_kwargs.get("intent_hint") or "auto"),
            "operation": request_operation,
            "interaction_source": str(
                request_kwargs.get("interaction_source") or InteractionSource.COMPOSER.value
            ),
        }
        legacy_replay_metadata = dict(request_kwargs.get("replay_metadata") or {})
        legacy_replay_metadata.pop("case_patch", None)
        legacy_replay_metadata.pop("fact_updates", None)
        replay_metadata.update(legacy_replay_metadata)
        if replay_metadata.get("interaction_source") not in {"composer", "quick_action"}:
            replay_metadata["interaction_source"] = InteractionSource.COMPOSER.value
        target_message_id = request_kwargs.get("target_assistant_message_id")
        handle = await begin_turn(
            str(request_kwargs["user_id"]),
            str(request_kwargs["conversation_id"]),
            turn_id,
            str(request_kwargs.get("query") or ""),
            mode=str(request_kwargs.get("mode") or "auto"),
            operation=request_operation,
            replay_metadata=replay_metadata,
            target_assistant_message_id=int(target_message_id) if target_message_id is not None else None,
        )

        effective = dict(request_kwargs)
        descriptor = dict(handle.get("replay_metadata") or replay_metadata)
        if target_message_id is not None:
            # The persisted assistant message owns replay classification.  A
            # client may identify the target, but cannot silently change the
            # prior mode, intent, operation, facts, or interaction source.
            effective.update(
                query=str(handle.get("query") or ""),
                mode=str(descriptor.get("query_mode") or "auto"),
                operation=str(descriptor.get("operation") or TurnOperation.MESSAGE.value),
                intent_hint=str(descriptor.get("intent") or "auto"),
                interaction_source=str(
                    descriptor.get("interaction_source") or InteractionSource.COMPOSER.value
                ),
            )
            descriptor["replay_mode"] = request_operation
            descriptor["target_assistant_message_id"] = int(target_message_id)
        effective.update(
            turn_id=turn_id,
            user_message_id=handle.get("user_message_id"),
            assistant_message_id=handle.get("assistant_message_id"),
            target_assistant_message_id=target_message_id,
            turn_status=str(handle.get("status") or "pending"),
            replay_metadata=descriptor,
        )
        return handle, effective

    async def _turn_cancelled(self, state_or_kwargs: Mapping[str, Any]) -> bool:
        checker = getattr(self.deps.history, "is_turn_cancelled", None)
        turn_id = str(state_or_kwargs.get("turn_id") or "")
        if not turn_id or not callable(checker):
            return False
        return bool(
            await checker(
                str(state_or_kwargs["user_id"]),
                str(state_or_kwargs["conversation_id"]),
                turn_id,
            )
        )

    async def _finish_interrupted_turn(
        self,
        state_or_kwargs: Mapping[str, Any],
        *,
        content: str,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        finish_turn = getattr(self.deps.history, "finish_turn", None)
        turn_id = str(state_or_kwargs.get("turn_id") or "")
        if not turn_id or not callable(finish_turn):
            return None
        metadata = {
            "turn_status": status,
            "trace_id": str(state_or_kwargs.get("trace_id") or ""),
            "pipeline_version": "pipeline-v4",
            "replay_metadata": dict(state_or_kwargs.get("replay_metadata") or {}),
        }
        return await finish_turn(
            str(state_or_kwargs["user_id"]),
            str(state_or_kwargs["conversation_id"]),
            turn_id,
            content=content,
            metadata=metadata,
            status=status,
            error_code=error_code,
        )

    async def _execute_case(self, state: AgentState) -> AgentState:
        """Turn assessment and checklist requests into ordinary legal chat."""
        append_action(state, Action.VALIDATE_INPUT)
        operation = str(state.get("operation") or TurnOperation.MESSAGE.value)
        if operation == TurnOperation.MESSAGE.value and not str(state.get("query") or "").strip():
            cast(dict[str, Any], state).update(
                answer="Bạn hãy nhập câu hỏi hoặc mô tả tình huống cần hỗ trợ.",
                source="error",
                outcome=WorkflowOutcome.FAILED.value,
                termination_reason=TerminationReason.INVALID_INPUT.value,
            )
            return state

        append_action(state, Action.LOAD_CONTEXT)
        snapshot = await self.deps.history.load(
            state["user_id"],
            state["conversation_id"],
            self.deps.max_history_messages,
        )
        _apply_context_metadata(state, snapshot)
        clarification = _clarify_unresolved_follow_up(state, snapshot)
        if clarification is not None:
            return clarification
        active = snapshot.active_case or {}

        append_action(state, Action.UNDERSTAND_TASK)
        hint = str(state.get("intent_hint") or "auto")
        classification_query = str(state.get("standalone_query") or state.get("query") or "")
        if hint in {RouteType.CASE_ASSESSMENT.value, RouteType.COMPLIANCE_CHECKLIST.value}:
            route = RouteType(hint)
        else:
            route = classify_route(classification_query, snapshot.history, active)
        if route not in {RouteType.CASE_ASSESSMENT, RouteType.COMPLIANCE_CHECKLIST}:
            state["route"] = route.value
            return state

        task = TaskType.BUILD_COMPLIANCE_CHECKLIST if route == RouteType.COMPLIANCE_CHECKLIST else TaskType.CASE_ASSESSMENT
        domain = detect_legal_domain(str(state.get("standalone_query") or state.get("query") or ""))
        state["route"] = route.value
        state["task_type"] = task.value
        state["source_scope"] = "legal_corpus"
        return await self._execute_case_general(state, task=task, domain=domain)

    async def _execute_case_general(
        self,
        state: AgentState,
        *,
        task: TaskType,
        domain: str,
    ) -> AgentState:
        """Answer a legal situation through the ordinary evidence workflow.

        Case assessment is a user intent, not a separate hard-coded legal
        rules engine. Carry the facts into the lookup context and let the
        normal retrieval, evidence, generation, and citation checks handle it.
        """
        active = cast(dict[str, Any], state.get("active_case") or {})
        original_query = str(state.get("query") or "").strip()
        request_query = str(state.get("standalone_query") or original_query).strip()
        request_query = request_query or original_query

        known_facts = {
            key: value.value
            for key, value in _fact_values(cast(dict[str, Any] | None, active.get("facts"))).items()
            if value.value.strip()
        }
        if known_facts:
            facts_context = "; ".join(f"{key.replace('_', ' ')}: {value}" for key, value in known_facts.items())
            request_query = f"{request_query}\nThông tin tình huống người dùng đã cung cấp: {facts_context}"
        if task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            request_query = f"{request_query}\nHãy trả lời bằng danh sách các bước cần làm, gắn từng bước với căn cứ truy xuất được."

        from vietnam_legal_agent.domain.tasks import QueryPlan

        plan = QueryPlan(
            task_type=TaskType.LEGAL_LOOKUP,
            route=RouteType.LEGAL_LOOKUP,
            is_follow_up=False,
            standalone_query=request_query,
            retrieval_queries=[request_query],
            legal_topics=[domain] if domain != "general" else [],
            confidence=1.0,
        ).model_dump(mode="json")
        delegated = await run_workflow(
            original_query or request_query,
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
            legacy_session_id=state.get("legacy_session_id", ""),
            mode=state.get("mode", "auto"),
            deps=self.deps,
            trace_id=state["trace_id"],
            compiled_workflow=self._compiled_workflow,
            precomputed_understanding=plan,
        )
        for key, default in (
            ("operation", TurnOperation.MESSAGE.value),
            ("intent_hint", "auto"),
            ("interaction_source", InteractionSource.COMPOSER.value),
            ("replay_metadata", {}),
            ("turn_id", ""),
            ("user_message_id", ""),
            ("assistant_message_id", ""),
            ("target_assistant_message_id", None),
            ("turn_status", "pending"),
            ("corpus_as_of_date", ""),
            ("preview", False),
        ):
            cast(dict[str, Any], delegated)[key] = state.get(key, default)
        delegated["route"] = RouteType.LEGAL_LOOKUP.value
        delegated["task_type"] = TaskType.LEGAL_LOOKUP.value
        delegated["rule_id"] = ""
        delegated["case_state"] = None
        delegated["active_case"] = None
        delegated["missing_facts"] = []
        delegated["clear_legacy_case"] = bool(active)
        delegated["pipeline_version"] = "pipeline-v4"
        termination = str(delegated.get("termination_reason") or "")
        delegated["outcome"] = (
            WorkflowOutcome.COMPLETED.value
            if termination in {
                TerminationReason.ANSWER_COMPLETE.value,
                TerminationReason.CACHE_HIT.value,
                TerminationReason.RESEARCH_COMPLETE.value,
            }
            else WorkflowOutcome.NEEDS_INFORMATION.value
            if termination == TerminationReason.AWAITING_USER_INPUT.value
            else WorkflowOutcome.INSUFFICIENT_EVIDENCE.value
            if termination == TerminationReason.INSUFFICIENT_EVIDENCE.value
            else WorkflowOutcome.OUT_OF_SCOPE.value
            if termination == TerminationReason.OUT_OF_SCOPE.value
            else WorkflowOutcome.FAILED.value
        )
        delegated["result_type"] = (
            ResultType.LEGAL_ANSWER.value
            if delegated["outcome"] == WorkflowOutcome.COMPLETED.value
            else ResultType.NONE.value
        )
        return delegated

    async def _execute(self, **kwargs: Any) -> AgentState:
        state = await self._initial(**kwargs)
        hint = str(state.get("intent_hint") or "auto")
        active_case = None
        if hint in {RouteType.CASE_ASSESSMENT.value, RouteType.COMPLIANCE_CHECKLIST.value}:
            return await self._execute_case(state)
        # Load the active case before automatic routing.  Terse follow-ups
        # such as "doanh thu 20 tỷ" must continue the existing assessment
        # instead of being treated as an out-of-scope standalone query.
        snapshot = await self.deps.history.load(state["user_id"], state["conversation_id"], self.deps.max_history_messages)
        _apply_context_metadata(state, snapshot)
        clarification = _clarify_unresolved_follow_up(state, snapshot)
        if clarification is not None:
            return clarification
        active_case = snapshot.active_case
        understanding_gw = getattr(self.deps, "understanding", None)
        precomputed_understanding: dict[str, Any] | None = None
        if understanding_gw is not None:
            try:
                u = await understanding_gw.understand(state.get("query", ""), snapshot.history, "", active_case)
                route = RouteType(u.route)
                precomputed_understanding = u.model_dump(mode="json")
            except Exception:  # noqa: BLE001 - fallback to deterministic route classification
                route = classify_route(state.get("query", ""), snapshot.history, active_case)
        else:
            route = classify_route(state.get("query", ""), snapshot.history, active_case)
        if route in {RouteType.CASE_ASSESSMENT, RouteType.COMPLIANCE_CHECKLIST}:
            return await self._execute_case(state)
        if route == RouteType.OUT_OF_SCOPE:
            return _terminal_safe_stop(
                state,
                route=route,
                outcome=WorkflowOutcome.OUT_OF_SCOPE,
                termination=TerminationReason.OUT_OF_SCOPE,
                answer="Tôi chỉ hỗ trợ tra cứu và xử lý các vấn đề pháp luật Việt Nam nằm trong kho văn bản đã đăng ký.",
                source_scope="outside_registered_corpus",
                reason_code="outside_registered_corpus",
            )
        if route != RouteType.RESEARCH_WEB and has_explicit_no_evidence_signal(state.get("query", "")):
            return _terminal_safe_stop(
                state,
                route=route,
                outcome=WorkflowOutcome.INSUFFICIENT_EVIDENCE,
                termination=TerminationReason.INSUFFICIENT_EVIDENCE,
                answer="Tôi chưa có tài liệu pháp luật phù hợp để kiểm chứng yêu cầu này. Bạn có thể chọn tìm nguồn công khai.",
                source_scope="legal_corpus",
                available_actions=[RouteType.RESEARCH_WEB.value],
                reason_code="explicit_no_evidence_signal",
            )
        delegated = await run_workflow(
            state["query"], user_id=state["user_id"], conversation_id=state["conversation_id"],
            legacy_session_id=state.get("legacy_session_id", ""), mode=state.get("mode", "auto"), deps=self.deps,
            trace_id=state["trace_id"], compiled_workflow=self._compiled_workflow,
            precomputed_understanding=precomputed_understanding,
        )
        # The bounded V4 router delegates ordinary legal lookups to the
        # already-accepted V3 graph.  Copy the V4 request descriptor back onto
        # that result so replay, retry, regeneration, and persistence retain
        # the user's original operation instead of silently falling back to
        # the legacy defaults.
        delegated["operation"] = state.get("operation", TurnOperation.MESSAGE.value)
        delegated["intent_hint"] = state.get("intent_hint", "auto")
        delegated["interaction_source"] = state.get(
            "interaction_source", InteractionSource.COMPOSER.value
        )
        delegated["replay_metadata"] = dict(state.get("replay_metadata") or {})
        delegated["turn_id"] = state.get("turn_id", "")
        delegated["user_message_id"] = state.get("user_message_id", "")
        delegated["assistant_message_id"] = state.get("assistant_message_id", "")
        delegated["target_assistant_message_id"] = state.get("target_assistant_message_id")
        delegated["turn_status"] = state.get("turn_status", "pending")
        delegated["corpus_as_of_date"] = state.get("corpus_as_of_date", "")
        delegated["preview"] = bool(state.get("preview", False))
        delegated["rule_id"] = ""
        delegated["pipeline_version"] = "pipeline-v4"
        delegated["outcome"] = WorkflowOutcome.COMPLETED.value if delegated.get("termination_reason") in {TerminationReason.ANSWER_COMPLETE.value, TerminationReason.CACHE_HIT.value, TerminationReason.RESEARCH_COMPLETE.value} else (
            WorkflowOutcome.NEEDS_INFORMATION.value if delegated.get("termination_reason") == TerminationReason.AWAITING_USER_INPUT.value else WorkflowOutcome.INSUFFICIENT_EVIDENCE.value if delegated.get("termination_reason") == TerminationReason.INSUFFICIENT_EVIDENCE.value else WorkflowOutcome.OUT_OF_SCOPE.value if delegated.get("termination_reason") == TerminationReason.OUT_OF_SCOPE.value else WorkflowOutcome.FAILED.value
        )
        delegated["result_type"] = (
            ResultType.LEGAL_ANSWER.value
            if delegated["outcome"] == WorkflowOutcome.COMPLETED.value
            and route != RouteType.CHITCHAT
            else ResultType.NONE.value
        )
        return delegated

    async def run(self, **kwargs: Any) -> AgentState:
        started = time.perf_counter()
        trace_id = str(kwargs.get("trace_id") or uuid4())
        _, request_kwargs = await self._begin_durable_turn({**kwargs, "trace_id": trace_id}, trace_id)
        state = await self._execute(**request_kwargs)
        state["run_started_at"] = state.get("run_started_at") or datetime.now(UTC).isoformat()
        state["run_ended_at"] = datetime.now(UTC).isoformat()
        state["run_duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        await self._persist(state, started_at=started)
        return state

    async def _persist(self, state: AgentState, *, started_at: float) -> None:
        """Persist V4 case lifecycle without completing safe-stop cases."""

        user_id = state["user_id"]
        conversation_id = state["conversation_id"]
        try:
            state["sources"] = _source_snapshots(state)
            finish_turn = getattr(self.deps.history, "finish_turn", None)
            durable_turn = bool(state.get("turn_id")) and callable(finish_turn)
            if durable_turn:
                assert callable(finish_turn)
                final = await finish_turn(
                    user_id,
                    conversation_id,
                    state["turn_id"],
                    content=state.get("answer", ""),
                    metadata=_metadata_v4(state),
                    status="complete",
                    error_code=None,
                )
                if final is None:
                    raise PermissionError("durable turn is not owned by current user")
                state["turn_status"] = str(final.get("status") or "failed")
                state["assistant_message_id"] = str(final.get("assistant_message_id") or "")
                if state["turn_status"] != "complete":
                    state["cache_status"] = "not_cacheable"
                    return

            active_case = state.get("active_case")
            outcome = state.get("outcome")
            if state.pop("clear_legacy_case", False):
                await self.deps.history.clear_case(user_id, conversation_id)
            elif active_case and outcome in {
                WorkflowOutcome.NEEDS_INFORMATION.value,
                WorkflowOutcome.INSUFFICIENT_EVIDENCE.value,
            }:
                # Keep a ready case when corpus evidence is incomplete.  The
                # user can return after an index update; it is not a decision.
                saved_case = await self.deps.history.save_case(user_id, conversation_id, active_case)
                state["case_state"] = _hydrate_persisted_case(saved_case) or state.get("case_state")
                if state.get("case_state"):
                    state["active_case"] = state["case_state"]
            elif active_case and outcome == WorkflowOutcome.COMPLETED.value:
                await self.deps.history.save_case(user_id, conversation_id, active_case)
                await self.deps.history.clear_case(user_id, conversation_id)
                state["case_state"] = {**dict(active_case), "status": "completed", "missing_facts": []}

            if not durable_turn:
                assistant_message_id = await self.deps.history.save_exchange(
                    user_id, conversation_id, state.get("query", ""), state.get("answer", ""), _metadata_v4(state)
                )
                if assistant_message_id is not None:
                    state["assistant_message_id"] = str(assistant_message_id)
            state["cache_status"] = "not_cacheable"
        finally:
            await self.deps.history.record_run(state, started_at, time.perf_counter())

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        started = time.perf_counter()
        trace_id = str(kwargs.get("trace_id") or uuid4())
        request_kwargs = {**kwargs, "trace_id": trace_id}
        sequence = 0
        durable_handle: dict[str, Any] | None = None
        durable_finalized = False
        partial_answer = ""
        state: AgentState | None = None

        def emit(payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal sequence
            sequence += 1
            return {
                **payload,
                "trace_id": trace_id,
                "pipeline_version": "pipeline-v4",
                "sequence": sequence,
            }

        async def finish_stopped(payload: Mapping[str, Any], code: str) -> dict[str, Any] | None:
            nonlocal durable_finalized
            final = await self._finish_interrupted_turn(
                payload, content=partial_answer, status="stopped", error_code=code
            )
            durable_finalized = bool(durable_handle)
            return final

        try:
            try:
                durable_handle, request_kwargs = await self._begin_durable_turn(request_kwargs, trace_id)
            except (PermissionError, ValueError) as exc:
                logger.info("Turn request rejected: %s", exc, extra={"trace_id": trace_id})
                yield emit({
                    "type": "error",
                    "code": "invalid_replay_target"
                    if request_kwargs.get("target_assistant_message_id")
                    else "turn_conflict",
                    "message": "Không thể dùng lại lượt trả lời này. Hãy tải lại cuộc trò chuyện rồi thử lại.",
                    "retryable": False,
                    "retry_after_seconds": None,
                })
                return

            yield emit({
                "type": "status",
                "message": "Đã tiếp nhận yêu cầu. Đang hiểu nội dung…",
                "stage": "turn_started",
                "turn_id": request_kwargs.get("turn_id", ""),
                "user_message_id": request_kwargs.get("user_message_id"),
                "assistant_message_id": request_kwargs.get("assistant_message_id"),
                "turn_status": request_kwargs.get("turn_status", "pending"),
            })
            yield emit({
                "type": "workflow_step",
                "step": 1,
                "action": Action.UNDERSTAND_TASK.value,
                "label": "Hiểu yêu cầu",
                "status": "running",
            })

            try:
                state = await self._execute(**request_kwargs)
            except Exception:
                logger.exception("V4 workflow execution failed", extra={"trace_id": trace_id})
                await self._finish_interrupted_turn(
                    request_kwargs,
                    content=partial_answer,
                    status="failed",
                    error_code="v4_execution_failed",
                )
                durable_finalized = bool(durable_handle)
                yield emit({
                    "type": "error",
                    "code": "v4_execution_failed",
                    "message": "Không thể hoàn tất workflow. Bạn có thể thử lại.",
                    "retryable": True,
                    "retry_after_seconds": 2,
                })
                return

            state["run_ended_at"] = datetime.now(UTC).isoformat()
            state["run_duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            trace_id = str(state.get("trace_id") or trace_id)
            seen: set[str] = set()
            step = 0
            for action in state.get("action_sequence", []):
                phase, label = _PHASES.get(action, ("check_evidence", "Kiểm tra căn cứ"))
                if phase in seen:
                    continue
                seen.add(phase)
                step += 1
                if phase == "collect_information" and state.get("missing_facts"):
                    label = f"{label} · còn thiếu {len(state['missing_facts'])} thông tin"
                yield emit({
                    "type": "workflow_step",
                    "step": step,
                    "action": phase,
                    "label": label,
                    "status": "completed",
                })
            if state.get("outcome") == WorkflowOutcome.NEEDS_INFORMATION.value:
                yield emit({
                    "type": "input_required",
                    "question": state.get("answer", ""),
                })

            answer = state.get("answer", "")
            chunks = split_verified_answer_for_stream(answer, max_chunk_chars=self.answer_chunk_size)
            last_flushed_length = 0
            for index, chunk in enumerate(chunks, start=1):
                if await self._turn_cancelled(state):
                    final = await finish_stopped(state, "user_cancelled")
                    yield emit({
                        "type": "response_stopped",
                        "text": partial_answer,
                        "stage": "stopped",
                        "turn_id": state.get("turn_id", ""),
                        "assistant_message_id": (final or {}).get("assistant_message_id")
                        or state.get("assistant_message_id", ""),
                        "turn_status": "stopped",
                    })
                    return
                partial_answer += chunk
                yield emit({
                    "type": "response_chunk",
                    "chunk": chunk,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "stage": "streaming",
                })
                update_turn = getattr(self.deps.history, "update_turn_content", None)
                if callable(update_turn) and state.get("turn_id") and (
                    len(partial_answer) - last_flushed_length >= 480 or index == len(chunks)
                ):
                    await update_turn(
                        state["user_id"], state["conversation_id"], state["turn_id"], partial_answer
                    )
                    last_flushed_length = len(partial_answer)
                if self.answer_chunk_delay_s:
                    await asyncio.sleep(self.answer_chunk_delay_s)

            if await self._turn_cancelled(state):
                final = await finish_stopped(state, "user_cancelled")
                yield emit({
                    "type": "response_stopped",
                    "text": partial_answer,
                    "stage": "stopped",
                    "turn_id": state.get("turn_id", ""),
                    "assistant_message_id": (final or {}).get("assistant_message_id")
                    or state.get("assistant_message_id", ""),
                    "turn_status": "stopped",
                })
                return

            try:
                await self._persist(state, started_at=started)
            except Exception:
                logger.exception("V4 workflow persistence failed", extra={"trace_id": trace_id})
                await self._finish_interrupted_turn(
                    state,
                    content=partial_answer,
                    status="failed",
                    error_code="v4_persistence_failed",
                )
                durable_finalized = bool(durable_handle)
                yield emit({
                    "type": "error",
                    "code": "v4_persistence_failed",
                    "message": "Câu trả lời đã được tạo nhưng chưa lưu được vào lịch sử. Bạn có thể thử lại.",
                    "retryable": True,
                    "retry_after_seconds": 2,
                })
                return
            durable_finalized = bool(durable_handle)
            if state.get("turn_status") == "stopped":
                yield emit({
                    "type": "response_stopped",
                    "text": partial_answer,
                    "stage": "stopped",
                    "turn_id": state.get("turn_id", ""),
                    "assistant_message_id": state.get("assistant_message_id", ""),
                    "turn_status": "stopped",
                })
                return
            yield emit({
                "type": "response_complete",
                "text": answer,
                "documents": _documents_for_api(state),
                "source": state.get("source", "error"),
                "stage": "complete",
                "turn_id": state.get("turn_id", ""),
                "turn_status": "complete",
                "assistant_message_id": state.get("assistant_message_id", ""),
                "user_message_id": state.get("user_message_id", ""),
                **_metadata_v4(state),
            })
        except asyncio.CancelledError:
            if durable_handle and not durable_finalized:
                await finish_stopped(state or request_kwargs, "client_disconnected")
            raise
        except Exception:
            logger.exception("V4 stream failed", extra={"trace_id": trace_id})
            if durable_handle and not durable_finalized:
                await self._finish_interrupted_turn(
                    state or request_kwargs,
                    content=partial_answer,
                    status="failed",
                    error_code="stream_incomplete",
                )
                durable_finalized = True
            yield emit({
                "type": "error",
                "code": "stream_incomplete",
                "message": "Luồng trả lời bị gián đoạn. Phần đã hiển thị được giữ lại trong lịch sử.",
                "retryable": True,
                "retry_after_seconds": 2,
            })
        finally:
            if durable_handle and not durable_finalized:
                try:
                    await finish_stopped(state or request_kwargs, "client_disconnected")
                except Exception:
                    logger.exception("Failed to finalize interrupted turn", extra={"trace_id": trace_id})
