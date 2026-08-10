"""LangGraph implementation of the bounded EPR workflow."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from langgraph.graph import END, StateGraph

from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.understanding import StructuredTaskUnderstandingGateway, TaskUnderstandingGateway
from epr_agent.domain.models import (
    Action,
    AgentState,
    EvidenceAssessment,
    TaskType,
    TerminationReason,
    append_action,
    documents_from_dict,
    documents_to_dict,
)
from epr_agent.domain.tasks import (
    build_active_case,
    build_follow_up_question,
    deterministic_task_understanding,
    extract_facts,
    is_epr_scope,
    merge_facts,
    missing_facts,
)
from epr_agent.tools.cache import LegacySemanticAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator, verify_citations
from epr_agent.tools.generation import GenerationGateway, LegacyGenerationGateway
from epr_agent.tools.history import HistoryGateway, UnifiedHistoryGateway
from epr_agent.tools.retrieval import LegacyRetrievalGateway, RetrievalGateway


@dataclass(slots=True)
class WorkflowDependencies:
    history: HistoryGateway
    cache: ScopedAnswerCache
    retrieval: RetrievalGateway
    evidence: EvidenceEvaluator
    generation: GenerationGateway
    planner: BoundedPlanner
    max_history_messages: int = 6
    understanding: TaskUnderstandingGateway | None = None


def default_dependencies() -> WorkflowDependencies:
    """Build production adapters lazily; importing the package needs no secrets."""

    from backend.config import get_settings

    settings = get_settings()
    return WorkflowDependencies(
        history=UnifiedHistoryGateway(),
        cache=ScopedAnswerCache(
            LegacySemanticAnswerCache(),
            corpus_version=str(getattr(settings, "corpus_version", "epr-corpus-v1")),
        ),
        retrieval=LegacyRetrievalGateway(),
        evidence=EvidenceEvaluator(
            min_docs=getattr(settings, "min_legal_evidence_docs", 1),
            min_chars=getattr(settings, "min_legal_evidence_chars", 160),
        ),
        generation=LegacyGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
        max_history_messages=max(2, int(getattr(settings, "history_context_messages", 6))),
        understanding=StructuredTaskUnderstandingGateway(),
    )


def _tool_result(state: AgentState, tool: str, started_at: float, *, ok: bool, count: int = 0, error: str = "") -> None:
    state.setdefault("tool_results", []).append(
        {
            "tool": tool,
            "ok": ok,
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "count": count,
            "error": error,
        }
    )


def build_workflow(deps: WorkflowDependencies):
    """Compile a graph with a closed transition surface."""

    planner = deps.planner
    graph = StateGraph(AgentState)

    async def load_context(state: AgentState) -> AgentState:
        append_action(state, Action.LOAD_CONTEXT)
        snapshot = await deps.history.load(
            state["user_id"],
            state["conversation_id"],
            deps.max_history_messages,
        )
        state["history"] = snapshot.history
        state["history_summary"] = snapshot.summary
        state["active_case"] = snapshot.active_case
        return state

    async def understand_task(state: AgentState) -> AgentState:
        append_action(state, Action.UNDERSTAND_TASK)
        history = state.get("history", [])
        active_case = state.get("active_case")
        if deps.understanding is None:
            understanding = deterministic_task_understanding(state["query"], history, active_case)
        else:
            understanding = await deps.understanding.understand(
                state["query"],
                history,
                state.get("history_summary", ""),
                active_case,
            )
        task = understanding.task_type
        # An in-progress case owns terse fact-only replies.  This guards
        # against a model accidentally reclassifying "Vật liệu là nhựa" as a
        # standalone legal lookup instead of resuming the collection flow.
        if (
            active_case
            and active_case.get("status", "collecting") != "completed"
            and active_case.get("task_type") in {
                TaskType.ASSESS_EPR_OBLIGATION.value,
                TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
            }
            and (understanding.is_follow_up or len(state["query"].strip()) < 160)
        ):
            task = TaskType(active_case["task_type"])
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
        state["is_follow_up"] = understanding.is_follow_up
        state["standalone_query"] = understanding.standalone_query or state["query"].strip()
        state["facts"] = facts
        state["missing_facts"] = missing_facts(task, facts)
        state["follow_up_question"] = build_follow_up_question(task, state["missing_facts"])
        state["is_epr_scope"] = is_epr_scope(state["standalone_query"], history, active_case)
        if task in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST}:
            case = build_active_case(task, facts, state["query"])
            state["active_case"] = case
            state["case_state"] = {
                **case,
                "status": "ready" if not state["missing_facts"] else "collecting",
            }
        return state

    async def check_cache(state: AgentState) -> AgentState:
        append_action(state, Action.CHECK_CACHE)
        task = TaskType(state["task_type"])
        started = time.perf_counter()
        try:
            value, key = await deps.cache.lookup(task, state["standalone_query"])
            if value is not None:
                cached_documents = documents_from_dict(value.evidence)
                cache_valid, _, cache_reason = verify_citations(value.answer, cached_documents, task)
                if not cache_valid:
                    value = None
                    state["citation_error"] = f"cached_{cache_reason}"
            state["cached_answer"] = value.answer if value else None
            state["cached_evidence"] = list(value.evidence) if value else []
            state["cached_citations"] = list(value.citations) if value else []
            state["cached_source"] = value.source if value else ""
            state["cache_key"] = key
            _tool_result(state, "answer_cache", started, ok=True, count=1 if value else 0)
        except Exception as exc:  # noqa: BLE001 - cache failures must degrade to a miss
            state["cached_answer"] = None
            _tool_result(state, "answer_cache", started, ok=False, error=str(exc))
        return state

    async def ask_user(state: AgentState) -> AgentState:
        append_action(state, Action.ASK_USER)
        state["answer"] = state.get("follow_up_question") or "Bạn có thể cung cấp thêm thông tin về trường hợp cần đánh giá không?"
        state["source"] = "follow_up"
        state["awaiting_user_input"] = True
        state["termination_reason"] = TerminationReason.AWAITING_USER_INPUT.value
        state["case_state"] = {
            **dict(state.get("active_case") or {}),
            "status": "collecting",
            "missing_facts": list(state.get("missing_facts") or []),
        }
        return state

    async def answer_cache(state: AgentState) -> AgentState:
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
        return state

    async def retrieve_faq(state: AgentState) -> AgentState:
        append_action(state, Action.RETRIEVE_FAQ)
        if not planner.can_retrieve(state):
            state["evidence"] = []
            return state
        state["retrieval_actions"] = int(state.get("retrieval_actions", 0)) + 1
        started = time.perf_counter()
        try:
            docs = await deps.retrieval.faq(state["standalone_query"], float(state.get("faq_threshold", 0.75)))
            state["evidence"] = documents_to_dict(docs)
            state["faq_hit"] = bool(docs)
            state["source"] = "faq" if docs else ""
            if docs and TaskType(state["task_type"]) != TaskType.LEGAL_LOOKUP:
                assessment = deps.evidence.evaluate(state["standalone_query"], docs, state["task_type"])
                state["evidence_assessment"] = assessment.to_dict()
            _tool_result(state, "faq_retrieval", started, ok=True, count=len(docs))
        except Exception as exc:  # noqa: BLE001 - retrieval failures must reach safe fallback
            state["evidence"] = []
            state["faq_hit"] = False
            _tool_result(state, "faq_retrieval", started, ok=False, error=str(exc))
        return state

    async def retrieve_legal(state: AgentState) -> AgentState:
        append_action(state, Action.RETRIEVE_LEGAL)
        if not planner.can_retrieve(state):
            state["evidence"] = []
            return state
        state["retrieval_actions"] = int(state.get("retrieval_actions", 0)) + 1
        started = time.perf_counter()
        try:
            docs = await deps.retrieval.legal(state["standalone_query"])
            state["evidence"] = documents_to_dict(docs)
            state["source"] = "legal" if docs else ""
            _tool_result(state, "legal_retrieval", started, ok=True, count=len(docs))
        except Exception as exc:  # noqa: BLE001 - retrieval failures must reach safe fallback
            state["evidence"] = []
            _tool_result(state, "legal_retrieval", started, ok=False, error=str(exc))
        return state

    async def evaluate_evidence(state: AgentState) -> AgentState:
        append_action(state, Action.EVALUATE_EVIDENCE)
        docs = documents_from_dict(state.get("evidence"))
        assessment = deps.evidence.evaluate(state["standalone_query"], docs, state["task_type"])
        state["evidence_assessment"] = assessment.to_dict()
        return state

    async def retrieve_web(state: AgentState) -> AgentState:
        append_action(state, Action.RETRIEVE_WEB)
        if not state.get("is_epr_scope") or not planner.can_retrieve(state):
            state["web_answer"] = ""
            state["evidence"] = []
            return state
        state["retrieval_actions"] = int(state.get("retrieval_actions", 0)) + 1
        started = time.perf_counter()
        try:
            answer, document = await deps.generation.web(state["standalone_query"])
            docs = [document] if document is not None else []
            state["web_answer"] = answer
            state["evidence"] = documents_to_dict(docs)
            state["source"] = "web_search" if docs else ""
            # A web response is accepted only as the explicitly-labelled
            # fallback source; citation verification still applies below.
            state["evidence_assessment"] = EvidenceAssessment(
                bool(docs and answer),
                "web_result" if docs and answer else "web_empty",
                len(docs),
                sum(len(doc.content) for doc in docs),
                bool(docs),
                False,
            ).to_dict()
            _tool_result(state, "web_search", started, ok=bool(docs and answer), count=len(docs))
        except Exception as exc:  # noqa: BLE001 - web failure is an observable safe stop
            state["web_answer"] = ""
            state["evidence"] = []
            _tool_result(state, "web_search", started, ok=False, error=str(exc))
        return state

    async def compose_answer(state: AgentState) -> AgentState:
        append_action(state, Action.COMPOSE_ANSWER)
        task = TaskType(state["task_type"])
        docs = documents_from_dict(state.get("evidence"))
        if task == TaskType.CHITCHAT:
            answer = await deps.generation.chitchat(state["query"], state.get("history", []))
            state["source"] = "chitchat"
        elif state.get("source") == "web_search":
            answer = state.get("web_answer", "")
        else:
            answer = await deps.generation.answer(task.value, state["standalone_query"], docs, state.get("facts", {}))
        state["answer"] = answer or ""
        if task == TaskType.ASSESS_EPR_OBLIGATION:
            state["assessment"] = {
                "status": "preliminary",
                "facts": dict(state.get("facts", {})),
                "evidence_count": len(docs),
            }
        elif task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            state["checklist"] = [
                {
                    "item": "Xác nhận vai trò và phạm vi hoạt động",
                    "action": state.get("facts", {}).get("business_role", "cần bổ sung"),
                    "evidence_indices": [1],
                    "assumption": "Dựa trên thông tin người dùng đã cung cấp",
                },
                {
                    "item": "Lập danh mục sản phẩm hoặc bao bì và vật liệu",
                    "action": f"{state.get('facts', {}).get('product_or_packaging', 'cần bổ sung')} / {state.get('facts', {}).get('material', 'cần bổ sung')}",
                    "evidence_indices": [1],
                    "assumption": "Cần kiểm tra lại với hồ sơ doanh nghiệp",
                },
                {
                    "item": "Đối chiếu thời điểm, ngưỡng và hình thức thực hiện",
                    "action": "Kiểm tra điều khoản nguồn",
                    "evidence_indices": [1],
                    "assumption": "Không suy ra ngưỡng khi chưa có số liệu",
                },
            ]
        if task in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST}:
            state["case_state"] = {
                **dict(state.get("active_case") or {}),
                "status": "completed",
                "missing_facts": [],
            }
        return state

    async def verify(state: AgentState) -> AgentState:
        append_action(state, Action.VERIFY_CITATIONS)
        task = TaskType(state["task_type"])
        if task == TaskType.CHITCHAT:
            state["citation_valid"] = True
            return state
        docs = documents_from_dict(state.get("evidence"))
        valid, citations, reason = verify_citations(state.get("answer", ""), docs, task)
        state["citation_valid"] = valid
        state["citation_error"] = reason
        state["citations"] = [citation.to_dict() for citation in citations]
        return state

    async def repair_answer(state: AgentState) -> AgentState:
        append_action(state, Action.REPAIR_ANSWER)
        state["repair_count"] = int(state.get("repair_count", 0)) + 1
        docs = documents_from_dict(state.get("evidence"))
        state["answer"] = await deps.generation.repair(state.get("answer", ""), docs, state["task_type"])
        return state

    async def finish(state: AgentState) -> AgentState:
        append_action(state, Action.FINISH)
        if not state.get("termination_reason"):
            state["termination_reason"] = (
                TerminationReason.WEB_FALLBACK.value
                if state.get("source") == "web_search"
                else TerminationReason.ANSWER_COMPLETE.value
            )
        return state

    async def safe_stop(state: AgentState) -> AgentState:
        append_action(state, Action.SAFE_STOP)
        reason = state.get("citation_error")
        if reason:
            state["answer"] = "Tôi chưa thể xác minh đầy đủ câu trả lời từ tài liệu đã truy xuất."
            state["termination_reason"] = TerminationReason.CITATION_VERIFICATION_FAILED.value
        elif not state.get("is_epr_scope"):
            state["answer"] = "Câu hỏi hiện nằm ngoài phạm vi tra cứu EPR của hệ thống."
            state["termination_reason"] = TerminationReason.OUT_OF_SCOPE.value
        else:
            state["answer"] = "Tôi chưa tìm thấy đủ tài liệu liên quan để đưa ra kết luận an toàn."
            state["termination_reason"] = TerminationReason.INSUFFICIENT_EVIDENCE.value
        state["source"] = "error"
        return state

    def route_after_understanding(state: AgentState) -> str:
        decision = planner.after_understanding(state)
        if decision.action == Action.COMPOSE_ANSWER:
            return "compose"
        if decision.action == Action.ASK_USER:
            return "ask_user"
        return "cache"

    def route_after_cache(state: AgentState) -> str:
        decision = planner.after_cache(state)
        return "answer_cache" if decision.action == Action.ANSWER_CACHE else "retrieve_faq"

    def route_after_faq(state: AgentState) -> str:
        task = TaskType(state["task_type"])
        if state.get("faq_hit") and (
            task == TaskType.LEGAL_LOOKUP
            or (state.get("evidence_assessment") or {}).get("sufficient")
        ):
            return "compose"
        if planner.can_retrieve(state):
            return "retrieve_legal"
        return "safe_stop"

    def route_after_legal(state: AgentState) -> str:
        return "evaluate_evidence"

    def route_after_evidence(state: AgentState) -> str:
        decision = planner.after_evidence(state)
        if decision.action == Action.COMPOSE_ANSWER:
            return "compose"
        if decision.action == Action.RETRIEVE_WEB:
            return "retrieve_web"
        return "safe_stop"

    def route_after_web(state: AgentState) -> str:
        return "compose" if state.get("evidence") and state.get("web_answer") else "safe_stop"

    def route_after_verify(state: AgentState) -> str:
        if not planner.within_iteration_budget(state):
            return "safe_stop"
        decision = planner.after_verification(state)
        if decision.action == Action.FINISH:
            return "finish"
        if decision.action == Action.REPAIR_ANSWER:
            return "repair"
        return "safe_stop"

    graph.add_node("load_context", load_context)
    graph.add_node("understand_task", understand_task)
    graph.add_node("check_cache", check_cache)
    graph.add_node("ask_user", ask_user)
    graph.add_node("answer_cache", answer_cache)
    graph.add_node("retrieve_faq", retrieve_faq)
    graph.add_node("retrieve_legal", retrieve_legal)
    graph.add_node("evaluate_evidence", evaluate_evidence)
    graph.add_node("retrieve_web", retrieve_web)
    graph.add_node("compose", compose_answer)
    graph.add_node("verify", verify)
    graph.add_node("repair", repair_answer)
    graph.add_node("finish", finish)
    graph.add_node("safe_stop", safe_stop)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "understand_task")
    graph.add_conditional_edges(
        "understand_task",
        route_after_understanding,
        {"compose": "compose", "ask_user": "ask_user", "cache": "check_cache"},
    )
    graph.add_conditional_edges(
        "check_cache",
        route_after_cache,
        {"answer_cache": "answer_cache", "retrieve_faq": "retrieve_faq"},
    )
    graph.add_edge("ask_user", END)
    graph.add_edge("answer_cache", END)
    graph.add_conditional_edges(
        "retrieve_faq",
        route_after_faq,
        {"compose": "compose", "retrieve_legal": "retrieve_legal", "safe_stop": "safe_stop"},
    )
    graph.add_edge("retrieve_legal", "evaluate_evidence")
    graph.add_conditional_edges(
        "evaluate_evidence",
        route_after_evidence,
        {"compose": "compose", "retrieve_web": "retrieve_web", "safe_stop": "safe_stop"},
    )
    graph.add_conditional_edges(
        "retrieve_web",
        route_after_web,
        {"compose": "compose", "safe_stop": "safe_stop"},
    )
    graph.add_conditional_edges(
        "compose",
        lambda state: "finish" if state.get("task_type") == TaskType.CHITCHAT.value else "verify",
        {"finish": "finish", "verify": "verify"},
    )
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"finish": "finish", "repair": "repair", "safe_stop": "safe_stop"},
    )
    graph.add_edge("repair", "verify")
    graph.add_edge("finish", END)
    graph.add_edge("safe_stop", END)
    return graph.compile()


async def create_initial_state(
    query: str,
    *,
    user_id: str,
    conversation_id: str,
    legacy_session_id: str = "",
    faq_threshold: float = 0.75,
    deps: WorkflowDependencies,
    trace_id: str | None = None,
) -> AgentState:
    """Initialize one serializable run state for invoke or streaming."""

    await deps.history.initialize()
    return {
        "trace_id": trace_id or str(uuid.uuid4()),
        "query": query.strip(),
        "standalone_query": query.strip(),
        "user_id": user_id,
        "conversation_id": conversation_id,
        "legacy_session_id": legacy_session_id,
        "faq_threshold": faq_threshold,
        "corpus_version": deps.cache.corpus_version,
        "history": [],
        "active_case": None,
        "case_state": None,
        "is_follow_up": False,
        "facts": {},
        "missing_facts": [],
        "tool_results": [],
        "evidence": [],
        "checklist": [],
        "action_sequence": [],
        "retrieval_actions": 0,
        "repair_count": 0,
        "iteration": 0,
        "citation_valid": False,
        "awaiting_user_input": False,
        "cached_answer": None,
        "cached_evidence": [],
        "cached_citations": [],
        "cached_source": "",
        "web_answer": "",
        "faq_hit": False,
        "source": "",
    }


async def run_workflow(
    query: str,
    *,
    user_id: str,
    conversation_id: str,
    legacy_session_id: str = "",
    faq_threshold: float = 0.75,
    deps: WorkflowDependencies,
    trace_id: str | None = None,
) -> AgentState:
    """Execute one bounded run and return its complete traceable state."""

    initial = await create_initial_state(
        query,
        user_id=user_id,
        conversation_id=conversation_id,
        legacy_session_id=legacy_session_id,
        faq_threshold=faq_threshold,
        deps=deps,
        trace_id=trace_id,
    )
    compiled = build_workflow(deps)
    return await compiled.ainvoke(initial)
