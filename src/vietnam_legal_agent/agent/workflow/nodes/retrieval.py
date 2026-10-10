"""LangGraph implementation of the bounded legal workflow."""

from __future__ import annotations

import asyncio
import logging
import time

from vietnam_legal_agent.domain.legal import LegalAnchor, explicit_anchors
from vietnam_legal_agent.domain.models import (
    Action,
    AgentState,
    EvidenceAssessment,
    append_action,
    documents_from_dict,
    documents_to_dict,
)
from vietnam_legal_agent.domain.routes import RouteType, route_spec
from vietnam_legal_agent.domain.verification import (
    VerificationPolicy,
)
from vietnam_legal_agent.tools.legal_readiness import (
    ReadinessStatus,
)
from vietnam_legal_agent.tools.retrieval import (
    RequiredAnchorParseError,
)

logger = logging.getLogger(__name__)

from vietnam_legal_agent.agent.workflow.contracts import (
    _build_retrieval_queries,
    _merge_multi_query_results,
    _tool_result,
    _trace,
    _verification_status_for_reason,
)
from vietnam_legal_agent.agent.workflow.nodes.context import WorkflowNodeContext


class RetrievalNodeHandlers(WorkflowNodeContext):
    async def retrieve_legal(self, state: AgentState) -> AgentState:
        append_action(state, Action.RETRIEVE_LEGAL)
        if not self.planner.can_retrieve(state):
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
                *(self.deps.retrieval.legal(search_query) for search_query in search_queries),
                return_exceptions=True,
            )
            successful_results = [
                (index, result) for index, result in enumerate(search_results) if not isinstance(result, BaseException)
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
                            "legal_anchor": doc.metadata.get("Parent_Dieu")
                            or doc.metadata.get("Dieu")
                            or doc.metadata.get("Điều"),
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
            retrieval_error = (
                "required_anchor_parse_failed" if isinstance(exc, RequiredAnchorParseError) else type(exc).__name__
            )
            state["retrieval_error"] = retrieval_error
            _tool_result(state, "legal_retrieval", started, ok=False, error=retrieval_error)
        return state

    async def evaluate_evidence(self, state: AgentState) -> AgentState:
        append_action(state, Action.EVALUATE_EVIDENCE)
        docs = documents_from_dict(state.get("evidence"))
        policy = route_spec(state.get("route", RouteType.LEGAL_LOOKUP.value)).verification_policy
        readiness_reason = ""
        if policy is VerificationPolicy.LEGAL_CORPUS and self.deps.legal_readiness is not None:
            try:
                readiness = self.deps.legal_readiness.audit()
                state["legal_readiness_status"] = readiness.status.value
                state["legal_readiness_sha"] = readiness.manifest_sha256
                allowed, gate_reason = self.deps.legal_readiness.allows_documents(docs)
                if not allowed:
                    readiness_reason = gate_reason
            except Exception:  # noqa: BLE001 - unreadable legacy readiness fails closed for scoped documents
                state["legal_readiness_status"] = ReadinessStatus.INVALID.value
                try:
                    state["legal_readiness_sha"] = self.deps.legal_readiness.manifest_sha256
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
            assessment = self.deps.evidence.evaluate(
                assessment_query,
                docs,
                state["task_type"],
                expected_anchors=[
                    LegalAnchor.model_validate(value) for value in state.get("explicit_anchor_details") or []
                ],
                relevance_queries=list(state.get("retrieval_queries") or []),
            )
        state["retrieval_queries"] = []
        state["evidence_assessment"] = assessment.to_dict()
        state["evidence_status"] = "sufficient" if assessment.sufficient else "insufficient"
        if readiness_reason in {"legal_review_pending", "legal_readiness_invalid"}:
            state["citation_error"] = readiness_reason
        state["verification_status"] = _verification_status_for_reason(
            assessment.reason, valid=assessment.sufficient
        ).value
        _trace(state, reason_code=assessment.reason, payload=assessment.to_dict())
        return state

    async def retrieve_web(self, state: AgentState) -> AgentState:
        append_action(state, Action.RETRIEVE_WEB)
        if state.get("route") != RouteType.RESEARCH_WEB.value or not self.planner.can_retrieve(state):
            state["web_answer"] = ""
            state["evidence"] = []
            return state
        state["retrieval_actions"] = int(state.get("retrieval_actions", 0)) + 1
        started = time.perf_counter()
        try:
            answer, docs = await self.deps.generation.web(state["standalone_query"])
            state["web_answer"] = answer
            state["evidence"] = documents_to_dict(docs)
            state["source"] = "web_search" if docs else ""
            state["source_scope"] = "web_research"
            # Web evidence is explicitly labelled and structurally checked,
            # but it is never accepted as legal-corpus evidence.
            web_assessment = self.deps.evidence.evaluate(state["standalone_query"], docs, state["task_type"])
            state["evidence_assessment"] = web_assessment.to_dict()
            state["evidence_status"] = "sufficient" if web_assessment.sufficient else "insufficient"
            _tool_result(
                state,
                "web_search",
                started,
                ok=bool(docs and answer),
                count=len(docs),
                metadata={"explicit_user_request": True},
            )
        except Exception as exc:  # noqa: BLE001 - web failure is an observable safe stop
            state["web_answer"] = ""
            state["evidence"] = []
            _tool_result(state, "web_search", started, ok=False, error=type(exc).__name__)
        return state

    def route_after_legal(self, state: AgentState) -> str:
        return "evaluate_evidence"

    def route_after_evidence(self, state: AgentState) -> str:
        decision = self.planner.after_evidence(state)
        if decision.action == Action.COMPOSE_ANSWER:
            return "compose"
        return "safe_stop"

    def route_after_web(self, state: AgentState) -> str:
        return (
            "compose"
            if state.get("evidence")
            and state.get("web_answer")
            and bool((state.get("evidence_assessment") or {}).get("sufficient"))
            else "safe_stop"
        )
