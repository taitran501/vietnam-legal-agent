"""API-facing bridge kept separate from the domain graph."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from epr_agent.agent.runtime import WorkflowRuntime, stream_chat


async def stream_chat_events(
    *,
    query: str,
    user_id: str,
    conversation_id: str,
    legacy_session_id: str = "",
    mode: str = "auto",
    operation: str = "message",
    intent_hint: str = "auto",
    interaction_source: str = "composer",
    case_patch: dict[str, str] | None = None,
    fact_updates: dict[str, dict[str, Any]] | None = None,
    replay_metadata: dict[str, Any] | None = None,
    runtime: WorkflowRuntime | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Return the stable SSE event contract for FastAPI or another HTTP host."""

    async for event in stream_chat(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        legacy_session_id=legacy_session_id,
        mode=mode,
        operation=operation,
        intent_hint=intent_hint,
        interaction_source=interaction_source,
        case_patch=case_patch or {},
        fact_updates=fact_updates or {},
        replay_metadata=replay_metadata or {},
        runtime=runtime,
    ):
        yield event
