"""Pipeline V4 bounded case workflow.

V4 intentionally reuses V3 for the already-accepted lookup, comparison,
research and chitchat routes.  Assessment and checklist are replaced by a
typed, rule-pack driven path; this is the route where a generic top-k answer
was unsafe.  The public runtime interface remains identical to V3.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from epr_agent.agent.graph import create_initial_state, run_workflow
from epr_agent.agent.runtime import (
    WorkflowRuntime,
    _documents_for_api,
    _metadata,
    _source_snapshots,
    split_verified_answer_for_stream,
)
from epr_agent.domain.epr_rules import (
    EPR_EFFECTIVE_DATES,
    EPR_RULE_ID,
    EPR_RULE_PACK_VERSION,
    case_fields,
    evaluate_assessment,
    extract_explicit_epr_facts,
    follow_up_question,
    legal_issues,
    missing_fact_keys,
    validate_fact_value,
)
from epr_agent.domain.models import (
    Action,
    AgentState,
    DocumentRecord,
    TaskType,
    TerminationReason,
    append_action,
    documents_to_dict,
)
from epr_agent.domain.routes import RouteType
from epr_agent.domain.tasks import classify_route, has_explicit_no_evidence_signal
from epr_agent.domain.v4 import (
    AssessmentStatus,
    CaseStateV4,
    FactConfirmationStatus,
    FactSource,
    FactValue,
    InteractionSource,
    IssueState,
    ResultType,
    RetrievalRequest,
    TurnOperation,
    WorkflowOutcome,
)
from epr_agent.tools.evidence import build_citations, is_unresolved_current_law_source

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
                fact = FactValue.model_validate(value)
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

    # V3 stored four free-form fields. Convert only values that have an
    # unambiguous V4 meaning; every migrated value remains explicitly
    # unverified so the V4 rule pack can still ask for material facts.
    migrated: dict[str, FactValue] = {}

    def migrate(target_key: str, value: str) -> None:
        if target_key not in result and value:
            migrated[target_key] = FactValue(
                value=value,
                source=FactSource.USER_TURN,
                source_turn="legacy-v3-migration",
                confidence=0.5,
                verified=False,
            )

    legacy_product = result.get("product_or_packaging")
    if legacy_product:
        product_text = legacy_product.value
        if "bao bì" in product_text.casefold():
            migrate("object_kind", "packaging")
            migrate("product_group", "bao_bi")
        elif "sản phẩm" in product_text.casefold():
            migrate("object_kind", "product")

    legacy_scope = result.get("activity_scope")
    if legacy_scope and any(marker in legacy_scope.value.casefold() for marker in ("việt nam", "nội địa", "trong nước")):
        migrate("market_placement", "vietnam_market")

    result.update(migrated)
    return result


def _case_payload(case: CaseStateV4) -> dict[str, Any]:
    payload = case.model_dump(mode="json")
    payload["fields"] = [field.model_dump() for field in case_fields(case.facts, case.missing_facts)]
    return payload


def _hydrate_persisted_case(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rebuild presentation fields after the generic persistence layer returns a case.

    ``case_states`` deliberately stores facts and workflow state, not UI metadata.
    The stream response still needs the route-owned field definitions; otherwise the
    frontend falls back to raw database keys such as ``business_role``.
    """

    if raw is None or raw.get("schema_version") != "v4":
        return raw
    payload = dict(raw)
    facts = _fact_values(cast(dict[str, Any] | None, raw.get("facts")))
    payload["fields"] = [
        field.model_dump()
        for field in case_fields(facts, list(raw.get("missing_facts") or []))
    ]
    return payload


def _metadata_v4(state: AgentState) -> dict[str, Any]:
    data = _metadata(state)
    data.update(
        {
            "outcome": state.get("outcome", WorkflowOutcome.FAILED.value),
            "result_type": state.get("result_type", ResultType.NONE.value),
            "required_issues": state.get("required_issues", []),
            "covered_issues": state.get("covered_issues", []),
            "rule_pack_version": EPR_RULE_PACK_VERSION,
            "rule_id": state.get("rule_id", EPR_RULE_ID),
            "effective_dates": EPR_EFFECTIVE_DATES,
            "case_fields": state.get("case_fields", []),
        }
    )
    return data


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
        state["case_patch"] = dict(kwargs.get("case_patch") or {})
        state["fact_updates"] = dict(kwargs.get("fact_updates") or {})
        replay_defaults = {
            "query_mode": state.get("mode", "auto"),
            "intent": state.get("intent_hint", "auto"),
            "operation": state.get("operation", TurnOperation.MESSAGE.value),
            "interaction_source": state.get("interaction_source", InteractionSource.COMPOSER.value),
            "case_patch": state.get("case_patch", {}),
            "fact_updates": state.get("fact_updates", {}),
        }
        replay_defaults.update(dict(kwargs.get("replay_metadata") or {}))
        state["replay_metadata"] = replay_defaults
        from backend.config import get_settings

        settings = get_settings()
        state["corpus_as_of_date"] = str(settings.corpus_as_of_date or "")
        state["preview"] = settings.corpus_runtime_mode == "preview"
        state["rule_id"] = EPR_RULE_ID
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
            "case_patch": dict(request_kwargs.get("case_patch") or {}),
            "fact_updates": dict(request_kwargs.get("fact_updates") or {}),
        }
        replay_metadata.update(dict(request_kwargs.get("replay_metadata") or {}))
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
                case_patch=dict(descriptor.get("case_patch") or {}),
                fact_updates=dict(descriptor.get("fact_updates") or {}),
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
        """Run the closed V4 assessment/checklist path with no free planner."""

        append_action(state, Action.VALIDATE_INPUT)
        operation = TurnOperation(str(state.get("operation") or TurnOperation.MESSAGE.value))
        if operation == TurnOperation.MESSAGE and not state.get("query", "").strip():
            cast(dict[str, Any], state).update(
                answer="Bạn hãy nhập nội dung cần tra cứu hoặc mô tả tình huống.",
                source="error",
                outcome=WorkflowOutcome.FAILED.value,
                termination_reason=TerminationReason.INVALID_INPUT.value,
            )
            return state

        append_action(state, Action.LOAD_CONTEXT)
        snapshot = await self.deps.history.load(state["user_id"], state["conversation_id"], self.deps.max_history_messages)
        state["history"] = snapshot.history
        state["history_summary"] = snapshot.summary
        state["active_case"] = snapshot.active_case

        append_action(state, Action.UNDERSTAND_TASK)
        active = snapshot.active_case or {}
        hint = str(state.get("intent_hint") or "auto")
        if hint in {RouteType.CASE_ASSESSMENT.value, RouteType.COMPLIANCE_CHECKLIST.value}:
            route = RouteType(hint)
        elif operation == TurnOperation.CONTINUE_CASE and active.get("task_type"):
            route = RouteType.COMPLIANCE_CHECKLIST if active["task_type"] == TaskType.BUILD_COMPLIANCE_CHECKLIST.value else RouteType.CASE_ASSESSMENT
        else:
            route = classify_route(state.get("query", ""), snapshot.history, active)
        if route not in {RouteType.CASE_ASSESSMENT, RouteType.COMPLIANCE_CHECKLIST}:
            # The caller will use the accepted V3 route implementation.
            state["route"] = route.value
            return state

        task = TaskType.BUILD_COMPLIANCE_CHECKLIST if route == RouteType.COMPLIANCE_CHECKLIST else TaskType.ASSESS_EPR_OBLIGATION
        state["route"] = route.value
        state["task_type"] = task.value
        state["source_scope"] = "legal_corpus"
        state["standalone_query"] = state.get("query", "") or str(active.get("last_query") or "")

        facts = _fact_values(cast(dict[str, Any] | None, active.get("facts")))
        turn_id = state.get("trace_id", "")
        facts.update(extract_explicit_epr_facts(state.get("query", ""), turn_id=turn_id))
        invalid_facts: dict[str, str] = {}
        for key, raw in dict(cast(dict[str, str] | None, state.get("case_patch")) or {}).items():
            try:
                text = validate_fact_value(key, " ".join(str(raw or "").split()))
            except ValueError as exc:
                invalid_facts[key] = str(exc)
                continue
            if text:
                facts[key] = FactValue(
                    value=text,
                    source=FactSource.CASE_PANEL,
                    source_turn=turn_id,
                    confidence=1.0,
                    verified=False,
                    confirmation_status=FactConfirmationStatus.USER_CONFIRMED,
                )
        for key, update_payload in dict(state.get("fact_updates") or {}).items():
            update = update_payload if isinstance(update_payload, dict) else {"value": update_payload}
            raw_value = " ".join(str(update.get("value") or "").split())
            if not raw_value:
                facts.pop(key, None)
                continue
            try:
                text = validate_fact_value(key, raw_value)
                confirmation_status = FactConfirmationStatus(
                    str(update.get("confirmation_status") or FactConfirmationStatus.UNKNOWN.value)
                )
            except (ValueError, TypeError) as exc:
                invalid_facts[key] = str(exc)
                continue
            facts[key] = FactValue(
                value=text,
                source=FactSource.CASE_PANEL,
                source_turn=turn_id,
                confidence=1.0,
                verified=False,
                confirmation_status=confirmation_status,
            )
        if invalid_facts:
            state["route"] = route.value
            state["source_scope"] = "legal_corpus"
            state["answer"] = "Một hoặc nhiều thông tin chưa hợp lệ: " + "; ".join(
                f"{key}: {message}" for key, message in invalid_facts.items()
            )
            state["source"] = "error"
            state["outcome"] = WorkflowOutcome.NEEDS_INFORMATION.value
            state["result_type"] = ResultType.NONE.value
            state["termination_reason"] = TerminationReason.AWAITING_USER_INPUT.value
            state["missing_facts"] = list(invalid_facts)
            state["validation_errors"] = invalid_facts
            return state
        missing = missing_fact_keys(facts)
        case = CaseStateV4(
            task_type=task.value,
            status="collecting" if missing else "ready",
            facts=facts,
            missing_facts=missing,
            as_of_date=datetime.now(UTC).date().isoformat(),
            last_query=state.get("query", "") or str(active.get("last_query") or ""),
        )
        state["active_case"] = _case_payload(case)
        state["case_state"] = _case_payload(case)
        state["facts"] = {key: value.value for key, value in facts.items()}
        state["missing_facts"] = missing
        state["case_fields"] = list((state["case_state"] or {}).get("fields") or [])
        state["understanding_confidence"] = 1.0 if hint != "auto" else 0.7
        state["trace_events"][-1]["reason_code"] = "route_selected"
        state["trace_events"][-1]["payload"] = {
            "route": route.value,
            "confidence": state["understanding_confidence"],
            "missing_facts": missing,
            "fact_provenance": {
                key: {"source": value.source.value, "verified": value.verified}
                for key, value in facts.items()
            },
        }

        if missing:
            append_action(state, Action.ASK_USER)
            cast(dict[str, Any], state).update(
                answer=follow_up_question(missing),
                source="follow_up",
                awaiting_user_input=True,
                outcome=WorkflowOutcome.NEEDS_INFORMATION.value,
                result_type=ResultType.NONE.value,
                termination_reason=TerminationReason.AWAITING_USER_INPUT.value,
                evidence_status="not_evaluated",
                assessment={
                    "status": AssessmentStatus.NEEDS_INFORMATION.value,
                    "missing_facts": missing,
                    "conclusion": "Chưa đủ thông tin để đánh giá nghĩa vụ.",
                },
            )
            return state

        if has_explicit_no_evidence_signal(state.get("query", "")):
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

        issues = legal_issues(facts, checklist=task == TaskType.BUILD_COMPLIANCE_CHECKLIST)
        state["required_issues"] = [issue.issue_id for issue in issues if issue.required]
        append_action(state, Action.RETRIEVE_LEGAL)
        started = time.perf_counter()
        requests = [
            RetrievalRequest(route=route.value, issue_id=issue.issue_id, query=issue.query, required_anchors=issue.required_anchors)
            for issue in issues
        ]
        state["trace_events"][-1]["reason_code"] = "issue_retrieval_requested"
        state["trace_events"][-1]["payload"] = {
            "tool": "issue_legal_retrieval",
            "issue_plan": [
                {"issue_id": request.issue_id, "required_anchors": request.required_anchors}
                for request in requests
            ],
        }
        semaphore = asyncio.Semaphore(4)

        async def retrieve_issue(request: RetrievalRequest):
            async with semaphore:
                return await self.deps.retrieval.legal(request)

        results = await asyncio.gather(*(retrieve_issue(request) for request in requests), return_exceptions=True)
        bundles: dict[str, list[dict[str, Any]]] = {}
        all_documents: dict[str, dict[str, Any]] = {}
        for issue, retrieval_result in zip(issues, results, strict=True):
            retrieved_documents: list[DocumentRecord] = [] if isinstance(retrieval_result, BaseException) else list(retrieval_result)
            selected = [
                document
                for document in retrieved_documents
                if not is_unresolved_current_law_source(document)
            ][:3]
            serialised = documents_to_dict(selected)
            bundles[issue.issue_id] = serialised
            for document in serialised:
                all_documents.setdefault(str(document.get("document_id") or ""), document)
        state["evidence_bundles"] = bundles
        state["evidence"] = list(all_documents.values())[:8]
        state["source"] = "legal" if state["evidence"] else ""
        state["retrieval_actions"] = 1
        state.setdefault("tool_results", []).append({
            "tool": "issue_legal_retrieval",
            "ok": bool(state["evidence"]),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "count": len(state["evidence"]),
            "metadata": {"issues": [request.issue_id for request in requests]},
        })

        append_action(state, Action.EVALUATE_EVIDENCE)
        issue_states: dict[str, dict[str, Any]] = {}
        evidence_ids: dict[str, list[str]] = {}
        covered: list[str] = []
        for issue in issues:
            bundle_docs = bundles[issue.issue_id]
            matches_by_anchor: dict[str, list[dict[str, Any]]] = {}
            for anchor in issue.required_anchors:
                anchor_text = anchor.casefold()
                matches_by_anchor[anchor] = [
                    doc
                    for doc in bundle_docs
                    if anchor_text in (
                        str((doc.get("metadata") or {}).get("legal_anchor") or "")
                        + " " + str((doc.get("metadata") or {}).get("Dieu") or "")
                        + " " + str((doc.get("metadata") or {}).get("source_title") or "")
                        + " " + str(doc.get("content") or "")
                    ).casefold()
                ]
            matching = [doc for values in matches_by_anchor.values() for doc in values]
            ids = list(dict.fromkeys(str(doc.get("document_id") or "") for doc in matching if doc.get("document_id")))
            evidence_ids[issue.issue_id] = ids
            is_covered = bool(ids) and all(bool(values) for values in matches_by_anchor.values())
            issue_states[issue.issue_id] = {
                "issue_id": issue.issue_id,
                "status": "supported" if is_covered else "insufficient_evidence",
                "evidence_ids": ids,
                "reason": "required_anchors_covered" if is_covered else "required_anchor_missing",
            }
            if is_covered:
                covered.append(issue.issue_id)
        state["issue_states"] = issue_states
        state["covered_issues"] = covered
        state["evidence_assessment"] = {
            "sufficient": set(state["required_issues"]).issubset(set(covered)),
            "reason": "all_required_issues_covered" if set(state["required_issues"]).issubset(set(covered)) else "required_issue_evidence_missing",
            "required_issues": state["required_issues"],
            "covered_issues": covered,
        }
        state["trace_events"][-1]["reason_code"] = state["evidence_assessment"]["reason"]
        state["trace_events"][-1]["payload"] = {
            "required_issues": state["required_issues"],
            "covered_issues": covered,
            "coverage_reason": state["evidence_assessment"]["reason"],
            "evidence_status": "sufficient" if state["evidence_assessment"]["sufficient"] else "insufficient",
        }
        if not state["evidence_assessment"]["sufficient"]:
            cast(dict[str, Any], state).update(
                answer="Tôi chưa có đủ căn cứ pháp lý đã kiểm chứng cho toàn bộ điều kiện cần đánh giá. Bạn có thể dùng chức năng tìm nguồn công khai hoặc thử lại khi corpus được cập nhật.",
                source="error",
                outcome=WorkflowOutcome.INSUFFICIENT_EVIDENCE.value,
                result_type=ResultType.NONE.value,
                termination_reason=TerminationReason.INSUFFICIENT_EVIDENCE.value,
                evidence_status="insufficient",
                available_actions=[RouteType.RESEARCH_WEB.value],
                safe_stop_reason="incomplete_issue_coverage",
            )
            return state

        append_action(state, Action.COMPOSE_ANSWER)
        result = evaluate_assessment(facts, evidence_ids=evidence_ids)
        result = result.model_copy(update={
            "rule_id": state.get("rule_id", EPR_RULE_ID),
            "active_evidence_ids": list(dict.fromkeys(item for values in evidence_ids.values() for item in values)),
            "corpus_version": str(state.get("corpus_version", "")),
            "corpus_as_of_date": str(state.get("corpus_as_of_date", "")),
        })
        if result.status == AssessmentStatus.NEEDS_INFORMATION:
            # Defensive invariant: deterministic evaluation cannot finish a
            # case if its own decision tree discovered a missing field.
            cast(dict[str, Any], state).update(
                answer=follow_up_question(result.missing_facts),
                source="follow_up",
                awaiting_user_input=True,
                outcome=WorkflowOutcome.NEEDS_INFORMATION.value,
                result_type=ResultType.NONE.value,
                termination_reason=TerminationReason.AWAITING_USER_INPUT.value,
                missing_facts=result.missing_facts,
            )
            return state
        if result.status == AssessmentStatus.CANNOT_DETERMINE:
            cast(dict[str, Any], state).update(
                answer=result.conclusion,
                source="error",
                assessment=result.model_dump(mode="json"),
                outcome=WorkflowOutcome.INSUFFICIENT_EVIDENCE.value,
                result_type=ResultType.NONE.value,
                termination_reason=TerminationReason.INSUFFICIENT_EVIDENCE.value,
                evidence_status="insufficient",
                available_actions=[RouteType.RESEARCH_WEB.value],
                safe_stop_reason="invalid_or_unresolved_fact",
            )
            return state
        citations = build_citations([type("Doc", (), {"metadata": doc.get("metadata", {}), "document_id": doc.get("document_id", "")})() for doc in state["evidence"]])
        if not citations:
            cast(dict[str, Any], state).update(
                answer="Chưa thể hoàn tất vì các nguồn truy xuất chưa tạo được vị trí trích dẫn kiểm chứng.",
                source="error",
                outcome=WorkflowOutcome.INSUFFICIENT_EVIDENCE.value,
                result_type=ResultType.NONE.value,
                termination_reason=TerminationReason.INSUFFICIENT_EVIDENCE.value,
                evidence_status="insufficient",
                available_actions=[RouteType.RESEARCH_WEB.value],
                citation_valid=False,
                citation_error="citation_verification_failed",
                safe_stop_reason="failed_citation_verification",
            )
            return state
        index_by_id = {citation.document_id: citation.index for citation in citations}
        lines = [result.conclusion]
        for reason in result.reasons:
            indices = sorted({index_by_id[item] for item in reason.evidence_ids if item in index_by_id})
            lines.append(f"- {reason.claim}" + (" " + " ".join(f"[{index}]" for index in indices) if indices else ""))
        if task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            state["checklist"] = [
                {"item": "Xác nhận tỷ lệ và quy cách tái chế áp dụng", "action": "Đối chiếu Điều 78 và Phụ lục XXII", "evidence_indices": [index_by_id[item] for item in evidence_ids.get("recycling_rate", []) if item in index_by_id]},
                {"item": "Chọn hình thức thực hiện", "action": "Đối chiếu Điều 79", "evidence_indices": [index_by_id[item] for item in evidence_ids.get("implementation", []) if item in index_by_id]},
                {"item": "Chuẩn bị đăng ký và báo cáo", "action": "Đối chiếu Điều 80", "evidence_indices": [index_by_id[item] for item in evidence_ids.get("reporting", []) if item in index_by_id]},
                {"item": "Đối chiếu nghĩa vụ đóng góp tài chính nếu chọn phương án này", "action": "Đối chiếu Điều 81", "evidence_indices": [index_by_id[item] for item in evidence_ids.get("financial", []) if item in index_by_id]},
            ]
            state["result_type"] = ResultType.CHECKLIST.value
        else:
            state["result_type"] = ResultType.ASSESSMENT.value
        state["assessment"] = result.model_dump(mode="json")
        state["answer"] = "\n".join(lines)
        state["citations"] = [citation.to_dict() for citation in citations]
        state["citation_valid"] = True
        state["citation_error"] = "ok"
        state["outcome"] = WorkflowOutcome.COMPLETED.value
        state["termination_reason"] = TerminationReason.ANSWER_COMPLETE.value
        state["evidence_status"] = "sufficient"
        case.status = "completed"
        case.decision_status = result.status
        case.issue_states = {key: IssueState.model_validate(value) for key, value in issue_states.items()}
        state["case_state"] = _case_payload(case)
        state["active_case"] = state["case_state"]
        append_action(state, Action.VERIFY_CITATIONS)
        append_action(state, Action.FINISH)
        return state

    async def _execute(self, **kwargs: Any) -> AgentState:
        state = await self._initial(**kwargs)
        hint = str(state.get("intent_hint") or "auto")
        active_case = None
        if hint in {RouteType.CASE_ASSESSMENT.value, RouteType.COMPLIANCE_CHECKLIST.value} or state.get("operation") == TurnOperation.CONTINUE_CASE.value:
            return await self._execute_case(state)
        # Load the active case before automatic routing.  Terse follow-ups
        # such as "doanh thu 20 tỷ" must continue the existing assessment
        # instead of being treated as an out-of-scope standalone query.
        snapshot = await self.deps.history.load(state["user_id"], state["conversation_id"], self.deps.max_history_messages)
        state["history"] = snapshot.history
        state["history_summary"] = snapshot.summary
        active_case = snapshot.active_case
        state["active_case"] = active_case
        route = classify_route(state.get("query", ""), snapshot.history, active_case)
        if route in {RouteType.CASE_ASSESSMENT, RouteType.COMPLIANCE_CHECKLIST}:
            return await self._execute_case(state)
        if route == RouteType.OUT_OF_SCOPE:
            return _terminal_safe_stop(
                state,
                route=route,
                outcome=WorkflowOutcome.OUT_OF_SCOPE,
                termination=TerminationReason.OUT_OF_SCOPE,
                answer="Tôi hiện chỉ hỗ trợ tra cứu và xử lý các vấn đề trong kho pháp luật EPR đã đăng ký.",
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
        delegated["case_patch"] = dict(state.get("case_patch") or {})
        delegated["fact_updates"] = dict(state.get("fact_updates") or {})
        delegated["replay_metadata"] = dict(state.get("replay_metadata") or {})
        delegated["turn_id"] = state.get("turn_id", "")
        delegated["user_message_id"] = state.get("user_message_id", "")
        delegated["assistant_message_id"] = state.get("assistant_message_id", "")
        delegated["target_assistant_message_id"] = state.get("target_assistant_message_id")
        delegated["turn_status"] = state.get("turn_status", "pending")
        delegated["corpus_as_of_date"] = state.get("corpus_as_of_date", "")
        delegated["preview"] = bool(state.get("preview", False))
        delegated["rule_id"] = state.get("rule_id", EPR_RULE_ID)
        delegated["pipeline_version"] = "pipeline-v4"
        delegated["outcome"] = WorkflowOutcome.COMPLETED.value if delegated.get("termination_reason") in {TerminationReason.ANSWER_COMPLETE.value, TerminationReason.CACHE_HIT.value, TerminationReason.RESEARCH_COMPLETE.value} else (
            WorkflowOutcome.NEEDS_INFORMATION.value if delegated.get("termination_reason") == TerminationReason.AWAITING_USER_INPUT.value else WorkflowOutcome.INSUFFICIENT_EVIDENCE.value if delegated.get("termination_reason") == TerminationReason.INSUFFICIENT_EVIDENCE.value else WorkflowOutcome.OUT_OF_SCOPE.value if delegated.get("termination_reason") == TerminationReason.OUT_OF_SCOPE.value else WorkflowOutcome.FAILED.value
        )
        delegated["result_type"] = ResultType.LEGAL_ANSWER.value if delegated["outcome"] == WorkflowOutcome.COMPLETED.value else ResultType.NONE.value
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
            if active_case and outcome in {
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
                    "missing_facts": state.get("missing_facts", []),
                    "case_state": state.get("case_state"),
                })
            if state.get("case_state"):
                yield emit({"type": "case_update", "case_state": state["case_state"]})

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
