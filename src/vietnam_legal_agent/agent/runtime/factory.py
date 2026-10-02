from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from vietnam_legal_agent.agent.graph import default_dependencies
from vietnam_legal_agent.agent.runtime.react import AgentWorkflowRuntime
from vietnam_legal_agent.agent.runtime.workflow import WorkflowRuntime
from vietnam_legal_agent.config import get_settings


@lru_cache(maxsize=1)
def get_default_runtime() -> WorkflowRuntime:
    # Runtime selection is server-owned. The public request schema has no
    # pipeline field, so a browser cannot force an experimental workflow.

    version = get_settings().agent_pipeline_version
    if version == "pipeline-agent":
        return AgentWorkflowRuntime(default_dependencies())  # type: ignore[return-value]
    if version == "pipeline-v4":
        from vietnam_legal_agent.agent.v4 import V4WorkflowRuntime

        return V4WorkflowRuntime(default_dependencies())
    return WorkflowRuntime(default_dependencies())


async def stream_chat(
    *,
    query: str,
    user_id: str,
    conversation_id: str,
    legacy_session_id: str = "",
    mode: str = "auto",
    operation: str = "message",
    intent_hint: str = "auto",
    interaction_source: str = "composer",
    replay_metadata: dict[str, Any] | None = None,
    turn_id: str = "",
    target_assistant_message_id: int | None = None,
    runtime: WorkflowRuntime | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Public SSE event generator used by the compatibility API route."""

    selected = runtime or get_default_runtime()
    request_kwargs: dict[str, Any] = {
        "query": query,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "legacy_session_id": legacy_session_id,
        "mode": mode,
    }
    request_kwargs.update(
        operation=operation,
        intent_hint=intent_hint,
        interaction_source=interaction_source,
        replay_metadata=replay_metadata or {},
        turn_id=turn_id,
        target_assistant_message_id=target_assistant_message_id,
    )
    async for event in selected.stream(**request_kwargs):
        yield event
