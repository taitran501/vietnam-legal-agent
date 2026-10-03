"""Pipeline V4 legal workflow with one evidence-backed path for all domains."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from vietnam_legal_agent.agent.runtime.presentation import (
    _documents_for_api,
    _source_snapshots,
    split_verified_answer_for_stream,
)
from vietnam_legal_agent.agent.runtime.workflow import WorkflowRuntime
from vietnam_legal_agent.agent.v4_support import (
    _apply_context_metadata,
    _clarify_unresolved_follow_up,
    _fact_values,
    _hydrate_persisted_case,
    _metadata_v4,
    _terminal_safe_stop,
)
from vietnam_legal_agent.agent.workflow.execution import create_initial_state, run_workflow
from vietnam_legal_agent.domain.models import (
    Action,
    AgentState,
    TaskType,
    TerminationReason,
    append_action,
)
from vietnam_legal_agent.domain.routes import RouteType, route_spec
from vietnam_legal_agent.domain.tasks import (
    TaskUnderstanding,
    classify_route,
    detect_legal_domain,
    deterministic_task_understanding,
    has_explicit_no_evidence_signal,
)
from vietnam_legal_agent.domain.v4 import (
    InteractionSource,
    ResultType,
    TurnOperation,
    WorkflowOutcome,
)

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
            "interaction_source": str(request_kwargs.get("interaction_source") or InteractionSource.COMPOSER.value),
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
                interaction_source=str(descriptor.get("interaction_source") or InteractionSource.COMPOSER.value),
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

    async def _execute_case(
        self,
        state: AgentState,
        *,
        precomputed_understanding: dict[str, Any] | None = None,
    ) -> AgentState:
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

        understanding: TaskUnderstanding | None = None
        if precomputed_understanding is not None:
            understanding = TaskUnderstanding.model_validate(precomputed_understanding)
        elif self.deps.understanding is not None:
            try:
                understanding = await self.deps.understanding.understand(
                    str(state.get("query") or ""),
                    snapshot.history,
                    snapshot.summary,
                    active,
                )
            except Exception as exc:  # noqa: BLE001 - keep the route usable with its original query
                logger.warning("Case-query understanding unavailable: %s", type(exc).__name__)

        if understanding is not None:
            state["standalone_query"] = understanding.standalone_query or str(state.get("query") or "")

        append_action(state, Action.UNDERSTAND_TASK)
        hint = str(state.get("intent_hint") or "auto")
        classification_query = str(
            (understanding.standalone_query if understanding else "")
            or state.get("standalone_query")
            or state.get("query")
            or ""
        )
        if hint in {RouteType.CASE_ASSESSMENT.value, RouteType.COMPLIANCE_CHECKLIST.value}:
            route = RouteType(hint)
        else:
            route = classify_route(classification_query, snapshot.history, active)
        if route not in {RouteType.CASE_ASSESSMENT, RouteType.COMPLIANCE_CHECKLIST}:
            state["route"] = route.value
            understanding = understanding or deterministic_task_understanding(
                classification_query,
                snapshot.history,
                active,
            )
            understanding = understanding.model_copy(update={"task_type": route_spec(route).task_type, "route": route})
            return await self._delegate_ordinary(
                state,
                precomputed_understanding=understanding.model_dump(mode="json"),
            )

        task = (
            TaskType.BUILD_COMPLIANCE_CHECKLIST if route == RouteType.COMPLIANCE_CHECKLIST else TaskType.CASE_ASSESSMENT
        )
        domain = detect_legal_domain(str(state.get("standalone_query") or state.get("query") or ""))
        state["route"] = route.value
        state["task_type"] = task.value
        state["source_scope"] = "legal_corpus"
        return await self._execute_case_general(
            state,
            task=task,
            domain=domain,
            retrieval_queries=understanding.retrieval_queries if understanding else [],
        )

    async def _execute_case_general(
        self,
        state: AgentState,
        *,
        task: TaskType,
        domain: str,
        retrieval_queries: list[str] | None = None,
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
            retrieval_queries=list(retrieval_queries or []),
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
            if termination
            in {
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

    async def _delegate_ordinary(
        self,
        state: AgentState,
        *,
        precomputed_understanding: dict[str, Any] | None,
    ) -> AgentState:
        """Run a non-case turn through the shared legal evidence workflow."""

        delegated = await run_workflow(
            state["query"],
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
            legacy_session_id=state.get("legacy_session_id", ""),
            mode=state.get("mode", "auto"),
            deps=self.deps,
            trace_id=state["trace_id"],
            compiled_workflow=self._compiled_workflow,
            precomputed_understanding=precomputed_understanding,
        )
        delegated["operation"] = state.get("operation", TurnOperation.MESSAGE.value)
        delegated["intent_hint"] = state.get("intent_hint", "auto")
        delegated["interaction_source"] = state.get("interaction_source", InteractionSource.COMPOSER.value)
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
        termination = str(delegated.get("termination_reason") or "")
        delegated["outcome"] = (
            WorkflowOutcome.COMPLETED.value
            if termination
            in {
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
            and delegated.get("route") != RouteType.CHITCHAT.value
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
        snapshot = await self.deps.history.load(
            state["user_id"], state["conversation_id"], self.deps.max_history_messages
        )
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
            return await self._execute_case(
                state,
                precomputed_understanding=precomputed_understanding,
            )
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
        return await self._delegate_ordinary(
            state,
            precomputed_understanding=precomputed_understanding,
        )

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
                yield emit(
                    {
                        "type": "error",
                        "code": "invalid_replay_target"
                        if request_kwargs.get("target_assistant_message_id")
                        else "turn_conflict",
                        "message": "Không thể dùng lại lượt trả lời này. Hãy tải lại cuộc trò chuyện rồi thử lại.",
                        "retryable": False,
                        "retry_after_seconds": None,
                    }
                )
                return

            yield emit(
                {
                    "type": "status",
                    "message": "Đã tiếp nhận yêu cầu. Đang hiểu nội dung…",
                    "stage": "turn_started",
                    "turn_id": request_kwargs.get("turn_id", ""),
                    "user_message_id": request_kwargs.get("user_message_id"),
                    "assistant_message_id": request_kwargs.get("assistant_message_id"),
                    "turn_status": request_kwargs.get("turn_status", "pending"),
                }
            )
            yield emit(
                {
                    "type": "workflow_step",
                    "step": 1,
                    "action": Action.UNDERSTAND_TASK.value,
                    "label": "Hiểu yêu cầu",
                    "status": "running",
                }
            )

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
                yield emit(
                    {
                        "type": "error",
                        "code": "v4_execution_failed",
                        "message": "Không thể hoàn tất workflow. Bạn có thể thử lại.",
                        "retryable": True,
                        "retry_after_seconds": 2,
                    }
                )
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
                yield emit(
                    {
                        "type": "workflow_step",
                        "step": step,
                        "action": phase,
                        "label": label,
                        "status": "completed",
                    }
                )
            if state.get("outcome") == WorkflowOutcome.NEEDS_INFORMATION.value:
                yield emit(
                    {
                        "type": "input_required",
                        "question": state.get("answer", ""),
                    }
                )

            answer = state.get("answer", "")
            chunks = split_verified_answer_for_stream(answer, max_chunk_chars=self.answer_chunk_size)
            last_flushed_length = 0
            for index, chunk in enumerate(chunks, start=1):
                if await self._turn_cancelled(state):
                    final = await finish_stopped(state, "user_cancelled")
                    yield emit(
                        {
                            "type": "response_stopped",
                            "text": partial_answer,
                            "stage": "stopped",
                            "turn_id": state.get("turn_id", ""),
                            "assistant_message_id": (final or {}).get("assistant_message_id")
                            or state.get("assistant_message_id", ""),
                            "turn_status": "stopped",
                        }
                    )
                    return
                partial_answer += chunk
                yield emit(
                    {
                        "type": "response_chunk",
                        "chunk": chunk,
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "stage": "streaming",
                    }
                )
                update_turn = getattr(self.deps.history, "update_turn_content", None)
                if (
                    callable(update_turn)
                    and state.get("turn_id")
                    and (len(partial_answer) - last_flushed_length >= 480 or index == len(chunks))
                ):
                    await update_turn(state["user_id"], state["conversation_id"], state["turn_id"], partial_answer)
                    last_flushed_length = len(partial_answer)
                if self.answer_chunk_delay_s:
                    await asyncio.sleep(self.answer_chunk_delay_s)

            if await self._turn_cancelled(state):
                final = await finish_stopped(state, "user_cancelled")
                yield emit(
                    {
                        "type": "response_stopped",
                        "text": partial_answer,
                        "stage": "stopped",
                        "turn_id": state.get("turn_id", ""),
                        "assistant_message_id": (final or {}).get("assistant_message_id")
                        or state.get("assistant_message_id", ""),
                        "turn_status": "stopped",
                    }
                )
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
                yield emit(
                    {
                        "type": "error",
                        "code": "v4_persistence_failed",
                        "message": "Câu trả lời đã được tạo nhưng chưa lưu được vào lịch sử. Bạn có thể thử lại.",
                        "retryable": True,
                        "retry_after_seconds": 2,
                    }
                )
                return
            durable_finalized = bool(durable_handle)
            if state.get("turn_status") == "stopped":
                yield emit(
                    {
                        "type": "response_stopped",
                        "text": partial_answer,
                        "stage": "stopped",
                        "turn_id": state.get("turn_id", ""),
                        "assistant_message_id": state.get("assistant_message_id", ""),
                        "turn_status": "stopped",
                    }
                )
                return
            yield emit(
                {
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
                }
            )
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
            yield emit(
                {
                    "type": "error",
                    "code": "stream_incomplete",
                    "message": "Luồng trả lời bị gián đoạn. Phần đã hiển thị được giữ lại trong lịch sử.",
                    "retryable": True,
                    "retry_after_seconds": 2,
                }
            )
        finally:
            if durable_handle and not durable_finalized:
                try:
                    await finish_stopped(state or request_kwargs, "client_disconnected")
                except Exception:
                    logger.exception("Failed to finalize interrupted turn", extra={"trace_id": trace_id})
