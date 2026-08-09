"""History and active-case gateway backed by one durable repository.

Recent history is short-term context for a conversation.  An active case is a
separate, small set of explicit business facts; it is not profile memory and
is never used to infer data that the user did not provide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

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
    ) -> None: ...

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]: ...

    async def clear_case(self, user_id: str, conversation_id: str) -> None: ...

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None: ...

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None: ...


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
    ) -> None:
        await (await self._resolve_store()).append_exchange(
            user_id,
            conversation_id,
            user_message,
            assistant_message,
            metadata,
        )

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return await (await self._resolve_store()).save_case(user_id, conversation_id, state)

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        await (await self._resolve_store()).complete_case(user_id, conversation_id)

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return await (await self._resolve_store()).get_case(user_id, conversation_id)

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        await (await self._resolve_store()).record_run(state, started_at, ended_at)


# This alias preserves prior imports while intentionally removing the old
# history-plus-separate-case-store migration path.
LegacyHistoryGateway = UnifiedHistoryGateway
