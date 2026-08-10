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
    runtime: WorkflowRuntime | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Return the stable SSE event contract for FastAPI or another HTTP host."""

    async for event in stream_chat(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        legacy_session_id=legacy_session_id,
        runtime=runtime,
    ):
        yield event
