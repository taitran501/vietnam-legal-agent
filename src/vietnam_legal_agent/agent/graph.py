"""Compatibility exports for the bounded LangGraph workflow."""

from vietnam_legal_agent.agent.workflow.builder import build_workflow
from vietnam_legal_agent.agent.workflow.contracts import (
    WorkflowDependencies,
    _append_source_version_caveat,
    _build_retrieval_queries,
    _has_source_version_caveat,
    _merge_multi_query_results,
    _retrieval_document_key,
    _tool_result,
    _trace,
    _verification_status_for_reason,
    default_dependencies,
)
from vietnam_legal_agent.agent.workflow.execution import create_initial_state, run_workflow

__all__ = [
    "WorkflowDependencies",
    "_append_source_version_caveat",
    "_build_retrieval_queries",
    "_has_source_version_caveat",
    "_merge_multi_query_results",
    "_retrieval_document_key",
    "_tool_result",
    "_trace",
    "_verification_status_for_reason",
    "build_workflow",
    "create_initial_state",
    "default_dependencies",
    "run_workflow",
]
