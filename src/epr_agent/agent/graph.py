"""LangGraph implementation of the bounded EPR workflow."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from langgraph.graph import END, StateGraph

from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.understanding import StructuredTaskUnderstandingGateway, TaskUnderstandingGateway
from epr_agent.domain.corpus import CorpusDescriptor, epr_corpus
from epr_agent.domain.legal import EMBEDDING_PROFILE, LegalAnchor, explicit_anchors
from epr_agent.domain.models import (
    Action,
    AgentState,
    TaskType,
    TerminationReason,
    append_action,
    documents_from_dict,
    documents_to_dict,
)
from epr_agent.domain.routes import RouteType, route_for_task, route_spec
from epr_agent.domain.tasks import (
    build_active_case,
    build_follow_up_question,
    deterministic_task_understanding,
    extract_facts,
    is_epr_scope,
    merge_facts,
    missing_facts,
)
from epr_agent.tools.cache import RedisExactAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import (
    EvidenceEvaluator,
    legal_relevance_checker,
    verify_citations,
    verify_web_citations,
)
from epr_agent.tools.generation import EvidenceGenerationGateway, GenerationGateway
from epr_agent.tools.history import HistoryGateway, UnifiedHistoryGateway
from epr_agent.tools.retrieval import QdrantLegalRetrievalGateway, RetrievalGateway
from epr_agent.tools.verifier import ClaimSupportVerifier, StructuredClaimSupportVerifier

logger = logging.getLogger(__name__)


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
    corpus: CorpusDescriptor | None = None
    claim_verifier: ClaimSupportVerifier | None = None


def default_dependencies() -> WorkflowDependencies:
    """Build production adapters lazily; importing the package needs no secrets."""

    from backend.config import get_settings
    from scripts.canonical_corpus import corpus_sha256

    settings = get_settings()
    corpus_sha = corpus_sha256(
        law_path=settings.law_data_path,
        manifest_path=settings.corpus_manifest_path,
    )
    return WorkflowDependencies(
        history=UnifiedHistoryGateway(),
        cache=ScopedAnswerCache(
            RedisExactAnswerCache(),
            corpus_version=str(getattr(settings, "corpus_version", "epr-corpus-v1")),
            corpus_id=str(getattr(settings, "corpus_id", "epr")),
            corpus_sha=corpus_sha,
            embedding_profile=str(getattr(settings, "embedding_profile", EMBEDDING_PROFILE)),
        ),
        retrieval=QdrantLegalRetrievalGateway(),
        evidence=EvidenceEvaluator(
            min_docs=getattr(settings, "min_legal_evidence_docs", 1),
            min_chars=getattr(settings, "min_legal_evidence_chars", 160),
            relevance_checker=(
                legal_relevance_checker(min_rerank_score=getattr(settings, "min_legal_rerank_score", 0.40))
                if getattr(settings, "enable_relevance_gate", True)
                else None
            ),
        ),
        generation=EvidenceGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=2, max_repairs=1, max_iterations=12),
        max_history_messages=max(2, int(getattr(settings, "history_context_messages", 6))),
        understanding=StructuredTaskUnderstandingGateway(),
        claim_verifier=StructuredClaimSupportVerifier(),
        corpus=epr_corpus(
            collection_alias=str(getattr(settings, "law_collection", "law_collection")),
            corpus_version=str(getattr(settings, "corpus_version", "epr-corpus-v1")),
            corpus_sha=corpus_sha,
            embedding_profile=str(getattr(settings, "embedding_profile", EMBEDDING_PROFILE)),
        ),
    )


def _trace(state: AgentState, *, reason_code: str = "", payload: dict | None = None) -> None:
    """Attach operational facts to the latest node without logging raw prompts."""

    events = state.setdefault("trace_events", [])
    if not events:
        return
    event = events[-1]
    event["reason_code"] = reason_code
    if payload:
        event["payload"] = payload


def _tool_result(
    state: AgentState,
    tool: str,
    started_at: float,
    *,
    ok: bool,
    count: int = 0,
    error: str = "",
    metadata: dict | None = None,
) -> None:
    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    state.setdefault("tool_results", []).append(
        {
            "tool": tool,
            "ok": ok,
            "latency_ms": latency_ms,
            "count": count,
            "error": error,
            "metadata": metadata or {},
        }
    )
    _trace(
        state,
        reason_code="tool_ok" if ok else "tool_failed",
        payload={"tool": tool, "latency_ms": latency_ms, "count": count, "error_code": error, **(metadata or {})},
    )
    logger.info(
        "%s",
        json.dumps(
            {
                "event": "agent_tool",
                "trace_id": state.get("trace_id"),
                "tool": tool,
                "ok": ok,
                "duration_ms": latency_ms,
                "count": count,
                "error_code": error or None,
            },
            ensure_ascii=False,
        ),
    )


def build_workflow(deps: WorkflowDependencies):
    """Compile a graph with a closed transition surface."""

    planner = deps.planner
    graph = StateGraph(AgentState)

    async def validate_input(state: AgentState) -> AgentState:
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
        _trace(state, reason_code="context_loaded", payload={"history_messages": len(snapshot.history), "has_active_case": bool(snapshot.active_case)})
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
        route = RouteType(understanding.route)
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
            route = route_for_task(task)
        # The selected product mode is a user choice, not a model tool call.
        # It is allowed to choose the bounded web-research route but never to
        # silently escape the legal-corpus route on insufficient evidence.
        if state.get("mode") == RouteType.RESEARCH_WEB.value:
            route = RouteType.RESEARCH_WEB
            task = TaskType.LEGAL_LOOKUP
        elif route == RouteType.OUT_OF_SCOPE:
            task = TaskType.LEGAL_LOOKUP
        elif task in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST, TaskType.CHITCHAT}:
            route = route_for_task(task)
        elif route in {RouteType.CASE_ASSESSMENT, RouteType.COMPLIANCE_CHECKLIST, RouteType.CHITCHAT}:
            task = route_spec(route).task_type
        elif route not in {RouteType.LEGAL_LOOKUP, RouteType.LEGAL_EXPLAIN_COMPARE, RouteType.RESEARCH_WEB, RouteType.OUT_OF_SCOPE}:
            route = RouteType.LEGAL_LOOKUP
        # A low-confidence structured decision is not allowed to trigger a
        # retrieval.  The deterministic fallback is intentionally confident
        # enough to keep local/offline development usable.
        if 0.0 < understanding.confidence < 0.45:
            state["clarification_required"] = True
            state["follow_up_question"] = "Bạn có thể nói rõ bạn muốn tra cứu quy định, giải thích/so sánh, hay đánh giá một trường hợp cụ thể không?"
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
        state["is_follow_up"] = understanding.is_follow_up
        state["standalone_query"] = understanding.standalone_query or state["query"].strip()
        state["facts"] = facts
        state["missing_facts"] = missing_facts(task, facts)
        if not state.get("clarification_required"):
            state["follow_up_question"] = build_follow_up_question(task, state["missing_facts"])
        state["is_epr_scope"] = is_epr_scope(state["standalone_query"], history, active_case)
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
            value, key = await deps.cache.lookup(task, state["standalone_query"], route=state.get("route", "legal_lookup"))
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

    async def ask_user(state: AgentState) -> AgentState:
        append_action(state, Action.ASK_USER)
        state["answer"] = state.get("follow_up_question") or "Bạn có thể cung cấp thêm thông tin về trường hợp cần đánh giá không?"
        state["source"] = "follow_up"
        state["awaiting_user_input"] = True
        state["termination_reason"] = TerminationReason.AWAITING_USER_INPUT.value
        if state.get("missing_facts"):
            state["case_state"] = {
                **dict(state.get("active_case") or {}),
                "status": "collecting",
                "missing_facts": list(state.get("missing_facts") or []),
            }
        _trace(
            state,
            reason_code=("route_confidence_below_calibrated_threshold" if state.get("clarification_required") else "required_case_facts_missing"),
            payload={"missing_facts": list(state.get("missing_facts") or [])},
        )
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
        _trace(state, reason_code="cache_answer_verified" if valid else "cache_answer_rejected", payload={"citation_reason": reason})
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
            query_anchors = explicit_anchors(state["standalone_query"])
            expected_articles = {anchor.article.lower() for anchor in query_anchors if anchor.article}
            state["explicit_articles"] = sorted(expected_articles)
            state["explicit_anchor_details"] = [anchor.model_dump() for anchor in query_anchors]
            if expected_articles:
                def exact_rank(document):
                    metadata = document.metadata or {}
                    anchors = {
                        anchor.article.lower()
                        for anchor in explicit_anchors(
                        "\n".join(
                            [
                                str(metadata.get("Dieu") or ""),
                                str(metadata.get("Điều") or ""),
                                str(metadata.get("Parent_Dieu") or ""),
                                document.content[:500],
                            ]
                        )
                        )
                        if anchor.article
                    }
                    return 0 if anchors & expected_articles else 1

                docs.sort(key=exact_rank)
            # The retriever returns ten ranked candidates. Route contracts
            # decide how much evidence reaches generation; traces retain the
            # candidate set and its dense/BM25/RRF/rerank scores.
            spec = route_spec(state.get("route", RouteType.LEGAL_LOOKUP.value))
            selected_docs = docs[: spec.max_evidence]
            state["evidence"] = documents_to_dict(selected_docs)
            state["source"] = "legal" if selected_docs else ""
            state["source_scope"] = spec.source_scope
            _tool_result(
                state,
                "legal_retrieval",
                started,
                ok=True,
                count=len(docs),
                metadata={
                    "explicit_articles": sorted(expected_articles),
                    "candidates": [
                        {
                            "document_id": doc.document_id,
                            "legal_anchor": doc.metadata.get("Parent_Dieu") or doc.metadata.get("Dieu") or doc.metadata.get("Điều"),
                            "dense_score": doc.metadata.get("semantic_score"),
                            "bm25_score": doc.metadata.get("lexical_score"),
                            "rrf_score": doc.metadata.get("rrf_score"),
                            "combined_score": doc.metadata.get("combined_score", doc.score),
                            "rerank_score": doc.metadata.get("rerank_score"),
                            "selected": index < len(selected_docs),
                            "rejection_reason": "selected" if index < len(selected_docs) else "route_evidence_limit",
                        }
                        for index, doc in enumerate(docs[:10])
                    ],
                },
            )
        except Exception as exc:  # noqa: BLE001 - retrieval failures must reach safe fallback
            state["evidence"] = []
            _tool_result(state, "legal_retrieval", started, ok=False, error=type(exc).__name__)
        return state

    async def evaluate_evidence(state: AgentState) -> AgentState:
        append_action(state, Action.EVALUATE_EVIDENCE)
        docs = documents_from_dict(state.get("evidence"))
        assessment = deps.evidence.evaluate(
            state["standalone_query"],
            docs,
            state["task_type"],
            expected_anchors=[LegalAnchor.model_validate(value) for value in state.get("explicit_anchor_details") or []],
        )
        state["evidence_assessment"] = assessment.to_dict()
        state["evidence_status"] = "sufficient" if assessment.sufficient else "insufficient"
        _trace(state, reason_code=assessment.reason, payload=assessment.to_dict())
        return state

    async def retrieve_web(state: AgentState) -> AgentState:
        append_action(state, Action.RETRIEVE_WEB)
        if state.get("route") != RouteType.RESEARCH_WEB.value or not planner.can_retrieve(state):
            state["web_answer"] = ""
            state["evidence"] = []
            return state
        state["retrieval_actions"] = int(state.get("retrieval_actions", 0)) + 1
        started = time.perf_counter()
        try:
            answer, docs = await deps.generation.web(state["standalone_query"])
            state["web_answer"] = answer
            state["evidence"] = documents_to_dict(docs)
            state["source"] = "web_search" if docs else ""
            state["source_scope"] = "web_research"
            # Web evidence is explicitly labelled and structurally checked,
            # but it is never accepted as legal-corpus evidence.
            web_assessment = deps.evidence.evaluate(state["standalone_query"], docs, state["task_type"])
            state["evidence_assessment"] = web_assessment.to_dict()
            state["evidence_status"] = "sufficient" if web_assessment.sufficient else "insufficient"
            _tool_result(state, "web_search", started, ok=bool(docs and answer), count=len(docs), metadata={"explicit_user_request": True})
        except Exception as exc:  # noqa: BLE001 - web failure is an observable safe stop
            state["web_answer"] = ""
            state["evidence"] = []
            _tool_result(state, "web_search", started, ok=False, error=type(exc).__name__)
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
        if state.get("source_scope") == "web_research":
            valid, citations, reason = verify_web_citations(state.get("answer", ""), docs)
        else:
            valid, citations, reason = verify_citations(state.get("answer", ""), docs, task)
        # Layer two is deliberately one bounded batch call.  It runs only
        # after citation structure is valid, and only for corpus legal claims.
        # Tests may omit this dependency and exercise the deterministic
        # structural contract in isolation.
        if valid and state.get("source_scope") == "legal_corpus" and deps.claim_verifier is not None:
            started = time.perf_counter()
            try:
                support = await deps.claim_verifier.verify(state.get("answer", ""), docs)
                valid = bool(support.supported)
                reason = support.reason_code if valid else f"claim_support_{support.reason_code}"
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
            except Exception as exc:  # noqa: BLE001 - unverified claims must stop safely
                valid = False
                reason = "claim_support_verifier_unavailable"
                _tool_result(
                    state,
                    "claim_support_verifier",
                    started,
                    ok=False,
                    count=len(docs),
                    error=reason,
                    metadata={"reason": "verifier_exception", "error_type": type(exc).__name__},
                )
        state["citation_valid"] = valid
        state["citation_error"] = reason
        state["citations"] = [citation.to_dict() for citation in citations]
        _trace(state, reason_code="citations_verified" if valid else reason, payload={"citation_reason": reason, "citation_count": len(citations)})
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
                TerminationReason.RESEARCH_COMPLETE.value
                if state.get("source") == "web_search"
                else TerminationReason.ANSWER_COMPLETE.value
            )
        state["evidence_status"] = state.get("evidence_status") or "sufficient"
        _trace(state, reason_code=state["termination_reason"])
        return state

    async def safe_stop(state: AgentState) -> AgentState:
        append_action(state, Action.SAFE_STOP)
        reason = state.get("citation_error")
        if state.get("termination_reason") == TerminationReason.INVALID_INPUT.value:
            state["answer"] = "Câu hỏi cần có nội dung và không vượt quá 3.000 ký tự. Bạn hãy gửi lại câu hỏi ngắn gọn hơn."
        elif reason:
            state["answer"] = "Tôi chưa thể xác minh đầy đủ câu trả lời từ tài liệu đã truy xuất."
            state["termination_reason"] = TerminationReason.CITATION_VERIFICATION_FAILED.value
        elif not state.get("is_epr_scope"):
            state["answer"] = "Câu hỏi hiện nằm ngoài phạm vi tra cứu EPR của hệ thống."
            state["termination_reason"] = TerminationReason.OUT_OF_SCOPE.value
        else:
            state["answer"] = "Tôi chưa tìm thấy đủ tài liệu liên quan để đưa ra kết luận an toàn."
            state["termination_reason"] = TerminationReason.INSUFFICIENT_EVIDENCE.value
        state["source"] = "error"
        state["evidence_status"] = "insufficient"
        if state.get("is_epr_scope") and not reason:
            state["available_actions"] = [RouteType.RESEARCH_WEB.value]
        _trace(state, reason_code=state["termination_reason"], payload={"citation_error": reason or ""})
        return state

    def route_after_understanding(state: AgentState) -> str:
        decision = planner.after_understanding(state)
        if decision.action == Action.COMPOSE_ANSWER:
            return "compose"
        if decision.action == Action.ASK_USER:
            return "ask_user"
        if decision.action == Action.RETRIEVE_WEB:
            return "retrieve_web"
        if decision.action == Action.SAFE_STOP:
            return "safe_stop"
        return "cache"

    def route_after_cache(state: AgentState) -> str:
        decision = planner.after_cache(state)
        return "answer_cache" if decision.action == Action.ANSWER_CACHE else "retrieve_legal"

    def route_after_legal(state: AgentState) -> str:
        return "evaluate_evidence"

    def route_after_evidence(state: AgentState) -> str:
        decision = planner.after_evidence(state)
        if decision.action == Action.COMPOSE_ANSWER:
            return "compose"
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

    graph.add_node("validate_input", validate_input)
    graph.add_node("load_context", load_context)
    graph.add_node("understand_task", understand_task)
    graph.add_node("check_cache", check_cache)
    graph.add_node("ask_user", ask_user)
    graph.add_node("answer_cache", answer_cache)
    graph.add_node("retrieve_legal", retrieve_legal)
    graph.add_node("evaluate_evidence", evaluate_evidence)
    graph.add_node("retrieve_web", retrieve_web)
    graph.add_node("compose", compose_answer)
    graph.add_node("verify", verify)
    graph.add_node("repair", repair_answer)
    graph.add_node("finish", finish)
    graph.add_node("safe_stop", safe_stop)

    graph.set_entry_point("validate_input")
    graph.add_conditional_edges(
        "validate_input",
        lambda state: "safe_stop" if state.get("error") else "load_context",
        {"safe_stop": "safe_stop", "load_context": "load_context"},
    )
    graph.add_edge("load_context", "understand_task")
    graph.add_conditional_edges(
        "understand_task",
        route_after_understanding,
        {"compose": "compose", "ask_user": "ask_user", "retrieve_web": "retrieve_web", "safe_stop": "safe_stop", "cache": "check_cache"},
    )
    graph.add_conditional_edges(
        "check_cache",
        route_after_cache,
        {"answer_cache": "answer_cache", "retrieve_legal": "retrieve_legal"},
    )
    graph.add_edge("ask_user", END)
    graph.add_edge("answer_cache", END)
    graph.add_edge("retrieve_legal", "evaluate_evidence")
    graph.add_conditional_edges(
        "evaluate_evidence",
        route_after_evidence,
        {"compose": "compose", "safe_stop": "safe_stop"},
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
    mode: str = "auto",
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
        "corpus_id": (deps.corpus or epr_corpus(collection_alias="law_collection", corpus_version=deps.cache.corpus_version)).corpus_id,
        "pipeline_version": "pipeline-v3",
        "corpus_version": deps.cache.corpus_version,
        "corpus_sha": (deps.corpus.corpus_sha if deps.corpus else deps.cache.corpus_sha),
        "embedding_profile": (deps.corpus.embedding_profile if deps.corpus else deps.cache.embedding_profile),
        "mode": mode,
        "route": RouteType.LEGAL_LOOKUP.value,
        "source_scope": "legal_corpus",
        "available_actions": [],
        "evidence_status": "not_evaluated",
        "run_started_at": datetime.now(UTC).isoformat(),
        "history": [],
        "active_case": None,
        "case_state": None,
        "is_follow_up": False,
        "clarification_required": False,
        "facts": {},
        "missing_facts": [],
        "tool_results": [],
        "trace_events": [],
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
        "explicit_articles": [],
        "source": "",
    }


async def run_workflow(
    query: str,
    *,
    user_id: str,
    conversation_id: str,
    legacy_session_id: str = "",
    mode: str = "auto",
    deps: WorkflowDependencies,
    trace_id: str | None = None,
) -> AgentState:
    """Execute one bounded run and return its complete traceable state."""

    initial = await create_initial_state(
        query,
        user_id=user_id,
        conversation_id=conversation_id,
        legacy_session_id=legacy_session_id,
        mode=mode,
        deps=deps,
        trace_id=trace_id,
    )
    compiled = build_workflow(deps)
    return await compiled.ainvoke(initial)
