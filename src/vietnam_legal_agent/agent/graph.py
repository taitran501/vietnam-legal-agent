"""LangGraph implementation of the bounded legal workflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, StateGraph

from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.understanding import StructuredTaskUnderstandingGateway, TaskUnderstandingGateway
from vietnam_legal_agent.domain.corpus import CorpusDescriptor, vietnamese_law_corpus
from vietnam_legal_agent.domain.legal import EMBEDDING_PROFILE, LegalAnchor, explicit_anchors
from vietnam_legal_agent.domain.models import (
    Action,
    AgentState,
    EvidenceAssessment,
    TaskType,
    TerminationReason,
    append_action,
    documents_from_dict,
    documents_to_dict,
)
from vietnam_legal_agent.domain.routes import RouteType, route_for_task, route_spec
from vietnam_legal_agent.domain.tasks import (
    TaskUnderstanding,
    build_follow_up_question,
    deterministic_task_understanding,
    extract_facts,
    is_context_dependent_query,
    merge_facts,
    preserve_explicit_anchors,
)
from vietnam_legal_agent.domain.verification import (
    VerificationPolicy,
    VerificationStatus,
    canonical_verification_status,
)
from vietnam_legal_agent.tools.cache import RedisExactAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import (
    EvidenceEvaluator,
    auto_anchor_citations_in_answer,
    legal_relevance_checker,
    propagate_list_item_citations,
    strip_citation_placeholders,
    verify_citations,
    verify_web_citations,
)
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway, GenerationGateway
from vietnam_legal_agent.tools.history import HistoryGateway, UnifiedHistoryGateway
from vietnam_legal_agent.tools.legal_readiness import (
    LegalReadinessProvider,
    ReadinessStatus,
)
from vietnam_legal_agent.tools.retrieval import (
    RequiredAnchorParseError,
    RetrievalGateway,
    UniversalLegalRetrievalGateway,
)
from vietnam_legal_agent.tools.verifier import (
    ClaimSupportVerifier,
    LegalCriticReviewer,
    StructuredClaimSupportVerifier,
)

logger = logging.getLogger(__name__)

_SOURCE_VERSION_CAVEAT = (
    "Lưu ý: Câu trả lời tóm tắt nội dung trong nguồn được trích dẫn; dữ liệu hiện "
    "chưa xác nhận các cập nhật hoặc hiệu lực hiện hành."
)


def _append_source_version_caveat(answer: str) -> str:
    cleaned = answer.rstrip()
    if not cleaned or _has_source_version_caveat(cleaned):
        return cleaned
    return f"{cleaned}\n\n{_SOURCE_VERSION_CAVEAT}"


def _has_source_version_caveat(answer: str) -> bool:
    text = " ".join((answer or "").casefold().split())
    if _SOURCE_VERSION_CAVEAT.casefold() in text:
        return True
    return bool(
        re.search(
            r"(?:chưa|không)\s+(?:thể\s+)?(?:xác nhận|kiểm chứng|đối chiếu|xác minh).{0,100}"
            r"(?:hiệu lực|quy định|nội dung).{0,45}(?:hiện hành|mới nhất|sửa đổi|cập nhật)"
            r"|(?:hiệu lực|quy định).{0,35}(?:hiện hành|mới nhất).{0,60}"
            r"(?:chưa|không)\s+(?:được\s+)?(?:xác nhận|kiểm chứng|đối chiếu|xác minh)",
            text,
        )
    )


def _retrieval_document_key(document) -> str:
    metadata = document.metadata or {}
    for key in ("_id", "point_id", "chunk_id", "chunkId"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return f"{document.source}:{key}:{value}"
    digest = hashlib.sha256((document.content or "").encode("utf-8")).hexdigest()[:20]
    return f"{document.source}:{document.document_id}:{digest}"


def _merge_multi_query_results(
    results: list[list[Any]],
    *,
    query_indices: list[int] | None = None,
) -> list[Any]:
    """Fuse ranked candidate lists while retaining chunk-level identity."""

    reciprocal_rank_constant = 60
    ranked: dict[str, dict[str, Any]] = {}
    for result_index, documents in enumerate(results):
        query_index = query_indices[result_index] if query_indices is not None else result_index
        # Preserve some recall from the user's wording, but prioritize the
        # first focused reformulation. Later reformulations add coverage and
        # must not let a noisy secondary query crowd the direct provision out.
        query_weight = 2.5 if query_index == 1 else 0.5
        for rank, document in enumerate(documents):
            key = _retrieval_document_key(document)
            entry = ranked.get(key)
            if entry is None:
                copied = type(document).from_dict(document.to_dict())
                entry = {"document": copied, "score": 0.0, "ranks": []}
                ranked[key] = entry
            else:
                copied = entry["document"]
                for score_key in (
                    "semantic_score",
                    "lexical_score",
                    "combined_score",
                    "rrf_score",
                    "rerank_score",
                ):
                    incoming_value = (document.metadata or {}).get(score_key)
                    if incoming_value is None:
                        continue
                    try:
                        incoming = float(incoming_value)
                    except (TypeError, ValueError):
                        continue
                    existing_value = (copied.metadata or {}).get(score_key)
                    if existing_value is None:
                        existing = None
                    else:
                        try:
                            existing = float(existing_value)
                        except (TypeError, ValueError):
                            existing = None
                    if existing is None or incoming > existing:
                        copied.metadata[score_key] = incoming
                if document.score is not None and (
                    copied.score is None or document.score > copied.score
                ):
                    copied.score = document.score
            entry["score"] += query_weight / (reciprocal_rank_constant + rank + 1)
            entry["ranks"].append({"query_index": query_index, "rank": rank + 1})

    ordered = sorted(ranked.values(), key=lambda item: item["score"], reverse=True)
    documents = []
    for entry in ordered:
        document = entry["document"]
        document.metadata["multi_query_rrf_score"] = entry["score"]
        document.metadata["multi_query_ranks"] = entry["ranks"]
        documents.append(document)
    return documents


def _build_retrieval_queries(
    original_query: str,
    standalone_query: str,
    proposed_queries: list[str] | None,
) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    allowed_anchors = {
        (field, value.casefold())
        for anchor in [*explicit_anchors(original_query), *explicit_anchors(standalone_query)]
        for field, value in (
            ("document_number", anchor.document_number),
            ("document_title", anchor.document_title),
            ("article", anchor.article),
            ("clause", anchor.clause),
            ("point", anchor.point),
            ("appendix", anchor.appendix),
        )
        if value
    }
    # Keep the user's wording as the retrieval baseline. One model-proposed
    # formal query can add recall without letting several overlapping
    # reformulations overwhelm the original request in rank fusion.
    for candidate in [original_query, standalone_query, *(proposed_queries or [])]:
        normalized = " ".join(str(candidate or "").split())
        if not normalized:
            continue
        normalized = preserve_explicit_anchors(original_query, normalized)
        candidate_anchors = {
            (field, value.casefold())
            for anchor in explicit_anchors(normalized)
            for field, value in (
                ("document_number", anchor.document_number),
                ("document_title", anchor.document_title),
                ("article", anchor.article),
                ("clause", anchor.clause),
                ("point", anchor.point),
                ("appendix", anchor.appendix),
            )
            if value
        }
        if candidate_anchors - allowed_anchors:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(normalized[:3000])
        if len(queries) == 3:
            break
    return queries


def _verification_status_for_reason(reason: str, *, valid: bool) -> VerificationStatus:
    if valid:
        return VerificationStatus.VERIFIED
    if reason in {
        "required_anchor_parse_failed",
        "legal_readiness_invalid",
        "verification_unavailable",
        "claim_support_verification_unavailable",
        "claim_support_verifier_unavailable",
    }:
        return VerificationStatus.VERIFICATION_UNAVAILABLE
    if reason in {"no_evidence_for_claims", "insufficient_evidence"}:
        return VerificationStatus.INSUFFICIENT_EVIDENCE
    if reason.startswith("claim_support_") and "insufficient_evidence" in reason:
        return VerificationStatus.INSUFFICIENT_EVIDENCE
    if reason.startswith("claim_support_") or reason in {
        "article_reference_not_in_evidence",
        "citation_out_of_range",
        "legal_claim_without_citation",
    } or "unsupported_claim" in reason or reason == "critic_legal_flaw_rejected":
        return VerificationStatus.UNSUPPORTED_CLAIM
    if reason.startswith("corrected_answer_") and "unavailable" in reason:
        return VerificationStatus.VERIFICATION_UNAVAILABLE
    return VerificationStatus.INSUFFICIENT_EVIDENCE


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
    critic_reviewer: LegalCriticReviewer | None = None
    legal_readiness: LegalReadinessProvider | None = None
    enforce_legal_safety_circuit_breaker: bool = False


def default_dependencies() -> WorkflowDependencies:
    """Build production adapters lazily; importing the package needs no secrets."""

    from vietnam_legal_agent.config import get_settings

    settings = get_settings()
    manifest_path = settings.universal_corpus_manifest_path
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        corpus_sha = hashlib.sha256(manifest_bytes).hexdigest()
    except (OSError, json.JSONDecodeError):
        manifest = {}
        corpus_sha = ""
    cache_corpus_id = str(manifest.get("corpus_id") or "vietnamese_law")
    cache_corpus_version = str(getattr(settings, "corpus_version", "vietnamese-law-v1"))
    cache_corpus_version = str(manifest.get("corpus_version") or cache_corpus_version)
    legal_readiness = None
    return WorkflowDependencies(
        history=UnifiedHistoryGateway(),
        cache=ScopedAnswerCache(
            RedisExactAnswerCache(),
            corpus_version=cache_corpus_version,
            corpus_id=cache_corpus_id,
            corpus_sha=corpus_sha,
            embedding_profile=str(getattr(settings, "embedding_profile", EMBEDDING_PROFILE)),
            legal_readiness_sha=legal_readiness.manifest_sha256 if legal_readiness else "",
        ),
        retrieval=UniversalLegalRetrievalGateway(),
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
        critic_reviewer=LegalCriticReviewer(),
        legal_readiness=legal_readiness,
        enforce_legal_safety_circuit_breaker=settings.enforce_legal_safety_circuit_breaker,
        corpus=vietnamese_law_corpus(
            collection_alias=str(getattr(settings, "law_collection", "law_collection")),
            corpus_version=cache_corpus_version,
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
        state["context_loaded"] = True
        state["history_messages"] = len(snapshot.history)
        _trace(state, reason_code="context_loaded", payload={"history_messages": len(snapshot.history), "has_active_case": bool(snapshot.active_case)})
        return state

    async def understand_task(state: AgentState) -> AgentState:
        append_action(state, Action.UNDERSTAND_TASK)
        history = state.get("history", [])
        active_case = state.get("active_case")
        precomputed = state.get("precomputed_understanding")
        state["precomputed_understanding"] = None
        if precomputed is not None:
            understanding = TaskUnderstanding.model_validate(precomputed)
        elif deps.understanding is None:
            understanding = deterministic_task_understanding(state["query"], history, active_case)
        else:
            understanding = await deps.understanding.understand(
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
            and active_case.get("task_type") in {
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
        # Preserve legacy readiness metadata for observability when the
        # narrow-corpus gate is explicitly enabled. The multi-domain corpus
        # uses its own general promotion gate.
        if route_spec(route).verification_policy is VerificationPolicy.LEGAL_CORPUS and deps.legal_readiness is not None:
            try:
                readiness = deps.legal_readiness.audit()
                state["legal_readiness_status"] = readiness.status.value
                state["legal_readiness_sha"] = readiness.manifest_sha256
            except Exception:  # noqa: BLE001 - an unreadable gate is invalid
                state["legal_readiness_status"] = ReadinessStatus.INVALID.value
                try:
                    state["legal_readiness_sha"] = deps.legal_readiness.manifest_sha256
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
        state["is_legal_scope"] = (route != RouteType.OUT_OF_SCOPE)
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

    async def check_cache(state: AgentState) -> AgentState:
        append_action(state, Action.CHECK_CACHE)
        task = TaskType(state["task_type"])
        started = time.perf_counter()
        try:
            policy = route_spec(state.get("route", RouteType.LEGAL_LOOKUP.value)).verification_policy
            if policy is VerificationPolicy.LEGAL_CORPUS and deps.legal_readiness is not None:
                # The manifest can be replaced without restarting the API.
                # Refresh the key namespace before lookup so an entry written
                # under the previous manifest snapshot is a cache miss.
                try:
                    readiness = deps.legal_readiness.audit()
                    state["legal_readiness_status"] = readiness.status.value
                    state["legal_readiness_sha"] = readiness.manifest_sha256
                    deps.cache.update_legal_readiness_sha(readiness.manifest_sha256)
                except Exception:  # noqa: BLE001 - document-scoped verification will fail closed later
                    state["legal_readiness_status"] = ReadinessStatus.INVALID.value
                    try:
                        state["legal_readiness_sha"] = deps.legal_readiness.manifest_sha256
                    except Exception:  # noqa: BLE001 - preserve cache-as-miss behavior
                        state["legal_readiness_sha"] = ""
            value, key = await deps.cache.lookup(task, state["standalone_query"], route=state.get("route", "legal_lookup"))
            if value is not None:
                cached_documents = documents_from_dict(value.evidence)
                cache_valid, _, _ = verify_citations(value.answer, cached_documents, task)
                if not cache_valid:
                    value = None
                    state["citation_error"] = ""
                elif policy is VerificationPolicy.LEGAL_CORPUS and deps.legal_readiness is not None:
                    try:
                        readiness = deps.legal_readiness.audit()
                        state["legal_readiness_status"] = readiness.status.value
                        state["legal_readiness_sha"] = readiness.manifest_sha256
                        deps.cache.update_legal_readiness_sha(readiness.manifest_sha256)
                        allowed, _ = deps.legal_readiness.allows_documents(cached_documents)
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

    async def ask_user(state: AgentState) -> AgentState:
        append_action(state, Action.ASK_USER)
        state["answer"] = state.get("follow_up_question") or "Bạn có thể cung cấp thêm thông tin về trường hợp cần đánh giá không?"
        state["source"] = "follow_up"
        state["awaiting_user_input"] = True
        state["termination_reason"] = TerminationReason.AWAITING_USER_INPUT.value
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
            state["retrieval_queries"] = []
            return state
        state["retrieval_actions"] = int(state.get("retrieval_actions", 0)) + 1
        started = time.perf_counter()
        search_queries = _build_retrieval_queries(
            state.get("query", ""),
            state.get("standalone_query", ""),
            state.get("retrieval_queries"),
        )
        state["retrieval_queries"] = search_queries
        state["retrieval_query_count"] = len(search_queries)
        try:
            search_results = await asyncio.gather(
                *(deps.retrieval.legal(search_query) for search_query in search_queries),
                return_exceptions=True,
            )
            successful_results = [
                (index, result)
                for index, result in enumerate(search_results)
                if not isinstance(result, BaseException)
            ]
            if not successful_results:
                first_error = next(
                    (result for result in search_results if isinstance(result, BaseException)),
                    RuntimeError("all_retrieval_queries_failed"),
                )
                raise first_error
            docs = _merge_multi_query_results(
                [result for _index, result in successful_results],
                query_indices=[index for index, _result in successful_results],
            )
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
                    "query_count": len(search_queries),
                    "successful_query_count": len(successful_results),
                    "failed_query_count": len(search_results) - len(successful_results),
                    "candidate_count_after_fusion": len(docs),
                    "explicit_articles": sorted(expected_articles),
                    "candidates": [
                        {
                            "document_id": doc.document_id,
                            "legal_anchor": doc.metadata.get("Parent_Dieu") or doc.metadata.get("Dieu") or doc.metadata.get("Điều"),
                            "dense_score": doc.metadata.get("semantic_score"),
                            "bm25_score": doc.metadata.get("lexical_score"),
                            "rrf_score": doc.metadata.get("rrf_score"),
                            "multi_query_rrf_score": doc.metadata.get("multi_query_rrf_score"),
                            "retrieval_query_count": len(doc.metadata.get("multi_query_ranks") or []),
                            "combined_score": doc.metadata.get("combined_score", doc.score),
                            "rerank_score": doc.metadata.get("rerank_score"),
                            "universal_bm25_rank": doc.metadata.get("bm25_rank"),
                            "selected": index < len(selected_docs),
                            "rejection_reason": "selected" if index < len(selected_docs) else "route_evidence_limit",
                        }
                        for index, doc in enumerate(docs[:10])
                    ],
                },
            )
        except Exception as exc:  # noqa: BLE001 - retrieval failures must reach safe fallback
            state["evidence"] = []
            state["retrieval_queries"] = []
            retrieval_error = "required_anchor_parse_failed" if isinstance(exc, RequiredAnchorParseError) else type(exc).__name__
            state["retrieval_error"] = retrieval_error
            _tool_result(state, "legal_retrieval", started, ok=False, error=retrieval_error)
        return state

    async def evaluate_evidence(state: AgentState) -> AgentState:
        append_action(state, Action.EVALUATE_EVIDENCE)
        docs = documents_from_dict(state.get("evidence"))
        policy = route_spec(state.get("route", RouteType.LEGAL_LOOKUP.value)).verification_policy
        readiness_reason = ""
        if policy is VerificationPolicy.LEGAL_CORPUS and deps.legal_readiness is not None:
            try:
                readiness = deps.legal_readiness.audit()
                state["legal_readiness_status"] = readiness.status.value
                state["legal_readiness_sha"] = readiness.manifest_sha256
                allowed, gate_reason = deps.legal_readiness.allows_documents(docs)
                if not allowed:
                    readiness_reason = gate_reason
            except Exception:  # noqa: BLE001 - unreadable legacy readiness fails closed for scoped documents
                state["legal_readiness_status"] = ReadinessStatus.INVALID.value
                try:
                    state["legal_readiness_sha"] = deps.legal_readiness.manifest_sha256
                except Exception:  # noqa: BLE001 - no digest is available for a broken manifest
                    state["legal_readiness_sha"] = ""
                readiness_reason = "legal_readiness_invalid"
        if state.get("retrieval_error") == "required_anchor_parse_failed":
            readiness_reason = "required_anchor_parse_failed"
        if readiness_reason:
            assessment = EvidenceAssessment(
                False,
                readiness_reason,
                len(docs),
                sum(len((doc.content or "").strip()) for doc in docs),
                bool(docs),
            )
        else:
            # Retrieval may use a normalized standalone query, but temporal
            # qualifiers are safety intent and must survive that rewrite.
            assessment_query = " ".join(
                dict.fromkeys(
                    value
                    for value in (
                        str(state.get("query") or "").strip(),
                        str(state.get("standalone_query") or "").strip(),
                    )
                    if value
                )
            )
            assessment = deps.evidence.evaluate(
                assessment_query,
                docs,
                state["task_type"],
                expected_anchors=[LegalAnchor.model_validate(value) for value in state.get("explicit_anchor_details") or []],
                relevance_queries=list(state.get("retrieval_queries") or []),
            )
        state["retrieval_queries"] = []
        state["evidence_assessment"] = assessment.to_dict()
        state["evidence_status"] = "sufficient" if assessment.sufficient else "insufficient"
        if readiness_reason in {"legal_review_pending", "legal_readiness_invalid"}:
            state["citation_error"] = readiness_reason
        state["verification_status"] = _verification_status_for_reason(assessment.reason, valid=assessment.sufficient).value
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
            if (state.get("evidence_assessment") or {}).get("source_version_only"):
                answer = _append_source_version_caveat(answer)
            answer = propagate_list_item_citations(answer or "")
        state["answer"] = answer or ""
        state["assessment"] = None
        state["checklist"] = []
        state["case_state"] = None
        return state

    async def verify(state: AgentState) -> AgentState:
        append_action(state, Action.VERIFY_CITATIONS)
        task = TaskType(state["task_type"])
        state["answer"] = strip_citation_placeholders(state.get("answer", ""))
        if task == TaskType.CHITCHAT:
            state["citation_valid"] = True
            return state
        docs = documents_from_dict(state.get("evidence"))
        route = route_spec(state.get("route", RouteType.LEGAL_LOOKUP.value))
        policy = route.verification_policy
        if policy is VerificationPolicy.LEGAL_CORPUS and deps.legal_readiness is not None:
            try:
                readiness = deps.legal_readiness.audit()
                state["legal_readiness_status"] = readiness.status.value
                state["legal_readiness_sha"] = readiness.manifest_sha256
                allowed, readiness_reason = deps.legal_readiness.allows_documents(docs)
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
            and deps.enforce_legal_safety_circuit_breaker
            and (deps.claim_verifier is None or deps.critic_reviewer is None)
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

        # Layer two is deliberately one bounded batch call.  Production legal
        # routes require both verifier dependencies; injected unit tests can
        # opt into the same contract with the explicit dependency flag.
        claim_support_passed = False
        if valid and policy is VerificationPolicy.LEGAL_CORPUS and deps.claim_verifier is not None:
            started = time.perf_counter()
            try:
                support = await deps.claim_verifier.verify(state.get("answer", ""), docs)
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
                state["verification_status"] = support_status.value if valid else (
                    VerificationStatus.VERIFICATION_UNAVAILABLE.value
                    if support_status is VerificationStatus.VERIFICATION_UNAVAILABLE
                    else support_status.value
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
        if valid and policy is VerificationPolicy.LEGAL_CORPUS and deps.critic_reviewer is not None:
            critic_started = time.perf_counter()
            try:
                verdict = await deps.critic_reviewer.review(
                    state.get("standalone_query", state.get("query", "")),
                    state.get("answer", ""),
                    docs,
                    source_version_only=bool(
                        (state.get("evidence_assessment") or {}).get("source_version_only")
                    ),
                )
                critic_blocks_answer = (
                    verdict.fatal_error
                    or (verdict.materially_nonresponsive and not (verdict.corrected_answer or "").strip())
                    or verdict.verification_status
                    in {
                        VerificationStatus.VERIFICATION_UNAVAILABLE,
                        VerificationStatus.INSUFFICIENT_EVIDENCE,
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
                    if claim_support_passed:
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
                if deps.claim_verifier is not None:
                    try:
                        corrected_support = await deps.claim_verifier.verify(corrected_answer, docs)
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
                and verdict.approved
                and not verdict.fatal_error
                and not verdict.materially_nonresponsive
                and claim_support_passed
            ):
                # An approved critic verdict means its rewrite is optional.
                # If that rewrite fails fresh checks, retain the original draft
                # only because it already passed the independent claim verifier.
                logger.info(
                    "Discarding unsupported optional critic correction; retaining verified draft (%s)",
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
        _trace(state, reason_code="citations_verified" if valid else reason, payload={"citation_reason": reason, "citation_count": len(citations)})
        return state

    async def repair_answer(state: AgentState) -> AgentState:
        append_action(state, Action.REPAIR_ANSWER)
        state["repair_count"] = int(state.get("repair_count", 0)) + 1
        docs = documents_from_dict(state.get("evidence"))
        state["answer"] = await deps.generation.repair(state.get("answer", ""), docs, state["task_type"])
        if (state.get("evidence_assessment") or {}).get("source_version_only"):
            state["answer"] = _append_source_version_caveat(state["answer"])
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
        citation_reason = str(state.get("citation_error") or "")
        evidence_reason = str((state.get("evidence_assessment") or {}).get("reason") or "")
        reason = citation_reason if citation_reason and citation_reason != "ok" else evidence_reason
        if state.get("route") == RouteType.RESEARCH_WEB.value and not state.get("evidence"):
            reason = "official_web_source_not_found"
        if state.get("termination_reason") == TerminationReason.INVALID_INPUT.value:
            state["answer"] = "Câu hỏi cần có nội dung và không vượt quá 3.000 ký tự. Bạn hãy gửi lại câu hỏi ngắn gọn hơn."
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
        if (
            state.get("is_legal_scope")
            and not citation_reason
            and state.get("route") != RouteType.RESEARCH_WEB.value
        ):
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

    def route_after_understanding(state: AgentState) -> str:
        if state.get("citation_error") in {"legal_review_pending", "legal_readiness_invalid"}:
            return "safe_stop"
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
        if state.get("citation_error") in {"legal_review_pending", "legal_readiness_invalid"}:
            return "safe_stop"
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
        return (
            "compose"
            if state.get("evidence")
            and state.get("web_answer")
            and bool((state.get("evidence_assessment") or {}).get("sufficient"))
            else "safe_stop"
        )

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
    # Cache hits are candidates, not trusted final answers.  They must pass
    # the same final verification contract as newly generated answers.
    graph.add_edge("answer_cache", "verify")
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
        "corpus_id": (
            deps.corpus
            or vietnamese_law_corpus(collection_alias="law_collection", corpus_version=deps.cache.corpus_version)
        ).corpus_id,
        "pipeline_version": "pipeline-v3",
        "corpus_version": deps.cache.corpus_version,
        "corpus_sha": (deps.corpus.corpus_sha if deps.corpus else deps.cache.corpus_sha),
        "embedding_profile": (deps.corpus.embedding_profile if deps.corpus else deps.cache.embedding_profile),
        "corpus_as_of_date": "",
        "mode": mode,
        "route": RouteType.LEGAL_LOOKUP.value,
        "source_scope": "legal_corpus",
        "available_actions": [],
        "evidence_status": "not_evaluated",
        "run_started_at": datetime.now(UTC).isoformat(),
        "history": [],
        "context_loaded": False,
        "history_messages": 0,
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
    compiled_workflow: Any | None = None,
    precomputed_understanding: dict[str, Any] | None = None,
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
    if precomputed_understanding is not None:
        initial["precomputed_understanding"] = precomputed_understanding
    if deps.legal_readiness is not None:
        readiness = deps.legal_readiness.audit()
        initial["legal_readiness_status"] = readiness.status.value
        initial["legal_readiness_sha"] = readiness.manifest_sha256
    compiled = compiled_workflow or build_workflow(deps)
    return await compiled.ainvoke(initial)
