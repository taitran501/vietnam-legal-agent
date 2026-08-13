"""History and active-case gateway backed by one durable repository.

Recent history is short-term context for a conversation.  An active case is a
separate, small set of explicit business facts; it is not profile memory and
is never used to infer data that the user did not provide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from epr_agent.domain.models import AgentState
from epr_agent.infra.persistence import PersistenceStore, get_persistence_store


@dataclass(slots=True)
class ContextSnapshot:
    history: list[dict[str, Any]]
    active_case: dict[str, Any] | None
    summary: str = ""


class HistoryGateway(Protocol):
    async def initialize(self) -> None: ...

    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot: ...

    async def save_exchange(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> int | None: ...

    async def begin_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        query: str,
        *,
        mode: str,
        operation: str,
        replay_metadata: dict[str, Any],
        target_assistant_message_id: int | None,
    ) -> dict[str, Any]: ...

    async def update_turn_content(
        self, user_id: str, conversation_id: str, turn_id: str, content: str
    ) -> bool: ...

    async def is_turn_cancelled(self, user_id: str, conversation_id: str, turn_id: str) -> bool: ...

    async def cancel_turn(
        self, user_id: str, conversation_id: str, turn_id: str
    ) -> dict[str, Any] | None: ...

    async def finish_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        *,
        content: str,
        metadata: dict[str, Any] | None,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any] | None: ...

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]: ...

    async def clear_case(self, user_id: str, conversation_id: str) -> None: ...

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None: ...

    async def record_run(self, state: AgentState, started_at: float, ended_at: float) -> None: ...


class UnifiedHistoryGateway:
    """Single source of truth for chats, summaries, cases, and workflow runs."""

    def __init__(self, store: PersistenceStore | None = None) -> None:
        self._store = store

    async def _resolve_store(self) -> PersistenceStore:
        if self._store is None:
            from backend.history.store import _database_url

            self._store = await get_persistence_store(_database_url())
        return self._store

    async def initialize(self) -> None:
        await (await self._resolve_store()).initialize()

    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot:
        store = await self._resolve_store()
        await store.ensure_conversation(user_id, conversation_id)
        history = await store.get_recent_history(user_id, conversation_id, max_messages)
        return ContextSnapshot(
            history=history,
            active_case=await store.load_case(user_id, conversation_id),
            summary=await store.get_summary(user_id, conversation_id),
        )

    async def save_exchange(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> int | None:
        return await (await self._resolve_store()).append_exchange(
            user_id,
            conversation_id,
            user_message,
            assistant_message,
            metadata,
        )

    async def begin_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        query: str,
        *,
        mode: str,
        operation: str,
        replay_metadata: dict[str, Any],
        target_assistant_message_id: int | None,
    ) -> dict[str, Any]:
        return await (await self._resolve_store()).begin_turn(
            user_id,
            conversation_id,
            turn_id,
            query,
            mode=mode,
            operation=operation,
            replay_metadata=replay_metadata,
            target_assistant_message_id=target_assistant_message_id,
        )

    async def update_turn_content(
        self, user_id: str, conversation_id: str, turn_id: str, content: str
    ) -> bool:
        return await (await self._resolve_store()).update_turn_content(
            user_id, conversation_id, turn_id, content
        )

    async def is_turn_cancelled(self, user_id: str, conversation_id: str, turn_id: str) -> bool:
        return await (await self._resolve_store()).is_turn_cancelled(user_id, conversation_id, turn_id)

    async def cancel_turn(
        self, user_id: str, conversation_id: str, turn_id: str
    ) -> dict[str, Any] | None:
        return await (await self._resolve_store()).cancel_turn(user_id, conversation_id, turn_id)

    async def finish_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        *,
        content: str,
        metadata: dict[str, Any] | None,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        return await (await self._resolve_store()).finish_turn(
            user_id,
            conversation_id,
            turn_id,
            content=content,
            metadata=metadata,
            status=status,
            error_code=error_code,
        )

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return await (await self._resolve_store()).save_case(user_id, conversation_id, state)

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        await (await self._resolve_store()).complete_case(user_id, conversation_id)

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return await (await self._resolve_store()).get_case(user_id, conversation_id)

    async def record_run(self, state: AgentState, started_at: float, ended_at: float) -> None:
        await (await self._resolve_store()).record_run(dict(state), started_at, ended_at)


# This alias preserves prior imports while intentionally removing the old
# history-plus-separate-case-store migration path.
LegacyHistoryGateway = UnifiedHistoryGateway
