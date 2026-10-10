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
from vietnam_legal_agent.domain.routes import RouteType, route_for_task, route_spec
from vietnam_legal_agent.domain.tasks import (
    TaskUnderstanding,
    build_follow_up_question,
    deterministic_task_understanding,
    extract_facts,
    is_context_dependent_query,
    merge_facts,
)
from vietnam_legal_agent.domain.verification import (
    VerificationPolicy,
)
from vietnam_legal_agent.tools.evidence import (
    verify_citations,
)
from vietnam_legal_agent.tools.legal_readiness import (
    ReadinessStatus,
)

logger = logging.getLogger(__name__)

from vietnam_legal_agent.agent.workflow.contracts import (
    _tool_result,
    _trace,
)
from vietnam_legal_agent.agent.workflow.nodes.context import WorkflowNodeContext


class IntakeNodeHandlers(WorkflowNodeContext):
    async def validate_input(self, state: AgentState) -> AgentState:
        append_action(state, Action.VALIDATE_INPUT)
        query = state.get("query", "").strip()
        if not query:
            state["error"] = "empty_query"
            state["termination_reason"] = TerminationReason.INVALID_INPUT.value
        elif len(query) > 3000:
            state["error"] = "query_too_long"
            state["termination_reason"] = TerminationReason.INVALID_INPUT.value
        _trace(state, reason_code=state.get("error") or "input_valid", payload={"query_length": len(query)})
        return state

    async def load_context(self, state: AgentState) -> AgentState:
        append_action(state, Action.LOAD_CONTEXT)
        snapshot = await self.deps.history.load(
            state["user_id"],
            state["conversation_id"],
            self.deps.max_history_messages,
        )
        state["history"] = snapshot.history
        state["history_summary"] = snapshot.summary
        state["active_case"] = snapshot.active_case
        state["context_loaded"] = True
        state["history_messages"] = len(snapshot.history)
        _trace(
            state,
            reason_code="context_loaded",
            payload={"history_messages": len(snapshot.history), "has_active_case": bool(snapshot.active_case)},
        )
        return state

    async def understand_task(self, state: AgentState) -> AgentState:
        append_action(state, Action.UNDERSTAND_TASK)
        history = state.get("history", [])
        active_case = state.get("active_case")
        precomputed = state.get("precomputed_understanding")
        state["precomputed_understanding"] = None
        if precomputed is not None:
            understanding = TaskUnderstanding.model_validate(precomputed)
        elif self.deps.understanding is None:
            understanding = deterministic_task_understanding(state["query"], history, active_case)
        else:
            understanding = await self.deps.understanding.understand(
                state["query"],
                history,
                state.get("history_summary", ""),
                active_case,
            )
        # Elliptical prompts such as "còn gìk" are not answerable in a new
        # conversation.  Ask for the missing topic instead of allowing either
        # a model shortcut or a generic retriever miss to produce an invented
        # legal answer.  Existing turns continue through the normal rewrite.
        if (
            understanding.is_follow_up
            and not history
            and not active_case
            and is_context_dependent_query(state["query"])
        ):
            state["clarification_required"] = True
            state["follow_up_question"] = (
                "Bạn đang hỏi tiếp về nội dung nào? Hãy nhắc lại tên văn bản, lĩnh vực "
                "hoặc câu hỏi trước để tôi kiểm tra căn cứ pháp lý chính xác."
            )
        route = RouteType(understanding.route)
        # The route contract owns product behavior; task_type is a legacy
        # compatibility field and may disagree in model output. Derive it
        # from the route so a general lookup cannot accidentally ask for
        # case-assessment facts.
        task = route_spec(route).task_type
        # If an active case is ongoing and the model detects topic continuity,
        # continue collecting information for the active case.
        if (
            active_case
            and active_case.get("status", "collecting") != "completed"
            and active_case.get("task_type")
            in {
                TaskType.CASE_ASSESSMENT.value,
                TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
            }
            and understanding.is_follow_up
        ):
            task = TaskType(active_case["task_type"])
            route = route_for_task(task)
        elif state.get("mode") == RouteType.RESEARCH_WEB.value:
            route = RouteType.RESEARCH_WEB
            task = route_spec(route).task_type
        # A low-confidence structured decision is not allowed to trigger a
        # retrieval.  The deterministic fallback is intentionally confident
        # enough to keep local/offline development usable.
        if 0.0 < understanding.confidence < 0.45:
            state["clarification_required"] = True
            state["follow_up_question"] = (
                "Bạn có thể nói rõ bạn muốn tra cứu quy định, giải thích/so sánh, hay đánh giá một trường hợp cụ thể không?"
            )
        explicit_facts = extract_facts(state["query"])
        active_facts = dict((active_case or {}).get("facts") or {})
        # A structured model may normalize an explicit fact, but it cannot add
        # a fact that is neither in the current user message nor the case.
        query_lower = " ".join(state["query"].lower().split())
        for key, value in understanding.facts.compact().items():
            if value.lower() in query_lower or active_facts.get(key) == value:
                explicit_facts.setdefault(key, value)
        facts = merge_facts(active_case, explicit_facts)
        state["task_type"] = task.value
        state["route"] = route.value
        state["source_scope"] = route_spec(route).source_scope
        # Preserve legacy readiness metadata for observability when the
        # narrow-corpus gate is explicitly enabled. The multi-domain corpus
        # uses its own general promotion gate.
        if (
            route_spec(route).verification_policy is VerificationPolicy.LEGAL_CORPUS
            and self.deps.legal_readiness is not None
        ):
            try:
                readiness = self.deps.legal_readiness.audit()
                state["legal_readiness_status"] = readiness.status.value
                state["legal_readiness_sha"] = readiness.manifest_sha256
            except Exception:  # noqa: BLE001 - an unreadable gate is invalid
                state["legal_readiness_status"] = ReadinessStatus.INVALID.value
                try:
                    state["legal_readiness_sha"] = self.deps.legal_readiness.manifest_sha256
                except Exception:  # noqa: BLE001 - keep the failure visible without blocking unrelated sources
                    state["legal_readiness_sha"] = ""
        state["is_follow_up"] = understanding.is_follow_up
        state["standalone_query"] = understanding.standalone_query or state["query"].strip()
        state["retrieval_queries"] = list(understanding.retrieval_queries)
        state["retrieval_query_count"] = 0
        state["facts"] = facts
        # The ordinary chat flow uses facts as context, never as a required
        # domain-specific intake form. Ask only when the request itself is
        # ambiguous enough that one clarification is genuinely necessary.
        state["missing_facts"] = []
        if not state.get("clarification_required"):
            state["follow_up_question"] = build_follow_up_question(task, state["missing_facts"])
        state["is_legal_scope"] = route != RouteType.OUT_OF_SCOPE
        state["explicit_articles"] = [anchor.article for anchor in understanding.explicit_anchors if anchor.article]
        state["explicit_anchor_details"] = [anchor.model_dump() for anchor in understanding.explicit_anchors]
        _trace(
            state,
            reason_code="task_understood",
            payload={
                "task_type": task.value,
                "route": route.value,
                "is_follow_up": bool(understanding.is_follow_up),
                "explicit_anchors": list(state["explicit_articles"]),
                "confidence": understanding.confidence,
                "missing_facts": list(state["missing_facts"]),
            },
        )
        state["active_case"] = None
        state["case_state"] = None
        return state

    async def check_cache(self, state: AgentState) -> AgentState:
        append_action(state, Action.CHECK_CACHE)
        task = TaskType(state["task_type"])
        started = time.perf_counter()
        try:
            policy = route_spec(state.get("route", RouteType.LEGAL_LOOKUP.value)).verification_policy
            if policy is VerificationPolicy.LEGAL_CORPUS and self.deps.legal_readiness is not None:
                # The manifest can be replaced without restarting the API.
                # Refresh the key namespace before lookup so an entry written
                # under the previous manifest snapshot is a cache miss.
                try:
                    readiness = self.deps.legal_readiness.audit()
                    state["legal_readiness_status"] = readiness.status.value
                    state["legal_readiness_sha"] = readiness.manifest_sha256
                    self.deps.cache.update_legal_readiness_sha(readiness.manifest_sha256)
                except Exception:  # noqa: BLE001 - document-scoped verification will fail closed later
                    state["legal_readiness_status"] = ReadinessStatus.INVALID.value
                    try:
                        state["legal_readiness_sha"] = self.deps.legal_readiness.manifest_sha256
                    except Exception:  # noqa: BLE001 - preserve cache-as-miss behavior
                        state["legal_readiness_sha"] = ""
            value, key = await self.deps.cache.lookup(
                task, state["standalone_query"], route=state.get("route", "legal_lookup")
            )
            if value is not None:
                cached_documents = documents_from_dict(value.evidence)
                cache_valid, _, _ = verify_citations(value.answer, cached_documents, task)
                if not cache_valid:
                    value = None
                    state["citation_error"] = ""
                elif policy is VerificationPolicy.LEGAL_CORPUS and self.deps.legal_readiness is not None:
                    try:
                        readiness = self.deps.legal_readiness.audit()
                        state["legal_readiness_status"] = readiness.status.value
                        state["legal_readiness_sha"] = readiness.manifest_sha256
                        self.deps.cache.update_legal_readiness_sha(readiness.manifest_sha256)
                        allowed, _ = self.deps.legal_readiness.allows_documents(cached_documents)
                    except Exception:  # noqa: BLE001 - unreadable legacy review metadata invalidates this cache entry
                        allowed = False
                    if not allowed:
                        value = None
                        state["citation_error"] = ""
            state["cached_answer"] = value.answer if value else None
            state["cached_evidence"] = list(value.evidence) if value else []
            state["cached_citations"] = list(value.citations) if value else []
            state["cached_source"] = value.source if value else ""
            state["cache_key"] = key
            state["cache_status"] = "hit" if value else "miss"
            _tool_result(
                state,
                "answer_cache",
                started,
                ok=True,
                count=1 if value else 0,
                metadata={"cache_status": "hit" if value else "miss"},
            )
        except Exception as exc:  # noqa: BLE001 - cache failures must degrade to a miss
            state["cached_answer"] = None
            state["cache_status"] = "error"
            _tool_result(state, "answer_cache", started, ok=False, error=type(exc).__name__)
        return state

    async def ask_user(self, state: AgentState) -> AgentState:
        append_action(state, Action.ASK_USER)
        state["answer"] = (
            state.get("follow_up_question") or "Bạn có thể cung cấp thêm thông tin về trường hợp cần đánh giá không?"
        )
        state["source"] = "follow_up"
        state["awaiting_user_input"] = True
        state["termination_reason"] = TerminationReason.AWAITING_USER_INPUT.value
        _trace(
            state,
            reason_code=(
                "route_confidence_below_calibrated_threshold"
                if state.get("clarification_required")
                else "required_case_facts_missing"
            ),
            payload={"missing_facts": list(state.get("missing_facts") or [])},
        )
        return state

    async def answer_cache(self, state: AgentState) -> AgentState:
        append_action(state, Action.ANSWER_CACHE)
        state["answer"] = state.get("cached_answer") or ""
        state["evidence"] = list(state.get("cached_evidence") or [])
        state["citations"] = list(state.get("cached_citations") or [])
        state["source"] = "cache"
        state["termination_reason"] = TerminationReason.CACHE_HIT.value
        documents = documents_from_dict(state.get("evidence"))
        valid, _, reason = verify_citations(state["answer"], documents, TaskType.LEGAL_LOOKUP)
        state["citation_valid"] = valid
        state["citation_error"] = reason
        _trace(
            state,
            reason_code="cache_answer_verified" if valid else "cache_answer_rejected",
            payload={"citation_reason": reason},
        )
        return state

    def route_after_understanding(self, state: AgentState) -> str:
        if state.get("citation_error") in {"legal_review_pending", "legal_readiness_invalid"}:
            return "safe_stop"
        decision = self.planner.after_understanding(state)
        if decision.action == Action.COMPOSE_ANSWER:
            return "compose"
        if decision.action == Action.ASK_USER:
            return "ask_user"
        if decision.action == Action.RETRIEVE_WEB:
            return "retrieve_web"
        if decision.action == Action.SAFE_STOP:
            return "safe_stop"
        return "cache"

    def route_after_cache(self, state: AgentState) -> str:
        if state.get("citation_error") in {"legal_review_pending", "legal_readiness_invalid"}:
            return "safe_stop"
        decision = self.planner.after_cache(state)
        return "answer_cache" if decision.action == Action.ANSWER_CACHE else "retrieve_legal"
