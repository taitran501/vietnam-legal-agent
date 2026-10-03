"""Stable, lazy imports for the runtime implementations."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vietnam_legal_agent.agent.runtime.factory import get_default_runtime, stream_chat
    from vietnam_legal_agent.agent.runtime.presentation import (
        _ACTION_STATUS,
        _cited_evidence_indices,
        _documents_for_api,
        _metadata,
        _source_snapshots,
        split_verified_answer_for_stream,
    )
    from vietnam_legal_agent.agent.runtime.react import AgentWorkflowRuntime
    from vietnam_legal_agent.agent.runtime.workflow import WorkflowRuntime
    from vietnam_legal_agent.agent.workflow.contracts import WorkflowDependencies

__all__ = [
    "_ACTION_STATUS",
    "AgentWorkflowRuntime",
    "WorkflowDependencies",
    "WorkflowRuntime",
    "_cited_evidence_indices",
    "_documents_for_api",
    "_metadata",
    "_source_snapshots",
    "default_dependencies",
    "get_default_runtime",
    "split_verified_answer_for_stream",
    "stream_chat",
]

_EXPORTS = {
    "_ACTION_STATUS": ("vietnam_legal_agent.agent.runtime.presentation", "_ACTION_STATUS"),
    "AgentWorkflowRuntime": ("vietnam_legal_agent.agent.runtime.react", "AgentWorkflowRuntime"),
    "WorkflowDependencies": ("vietnam_legal_agent.agent.workflow.contracts", "WorkflowDependencies"),
    "WorkflowRuntime": ("vietnam_legal_agent.agent.runtime.workflow", "WorkflowRuntime"),
    "_cited_evidence_indices": (
        "vietnam_legal_agent.agent.runtime.presentation",
        "_cited_evidence_indices",
    ),
    "_documents_for_api": ("vietnam_legal_agent.agent.runtime.presentation", "_documents_for_api"),
    "_metadata": ("vietnam_legal_agent.agent.runtime.presentation", "_metadata"),
    "_source_snapshots": ("vietnam_legal_agent.agent.runtime.presentation", "_source_snapshots"),
    "default_dependencies": ("vietnam_legal_agent.agent.workflow.contracts", "default_dependencies"),
    "get_default_runtime": ("vietnam_legal_agent.agent.runtime.factory", "get_default_runtime"),
    "split_verified_answer_for_stream": (
        "vietnam_legal_agent.agent.runtime.presentation",
        "split_verified_answer_for_stream",
    ),
    "stream_chat": ("vietnam_legal_agent.agent.runtime.factory", "stream_chat"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
