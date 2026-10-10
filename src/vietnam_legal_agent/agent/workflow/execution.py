from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from vietnam_legal_agent.agent.workflow.builder import build_workflow
from vietnam_legal_agent.agent.workflow.contracts import WorkflowDependencies
from vietnam_legal_agent.domain.corpus import vietnamese_law_corpus
from vietnam_legal_agent.domain.models import AgentState
from vietnam_legal_agent.domain.routes import RouteType


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
