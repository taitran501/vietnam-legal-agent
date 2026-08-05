"""History and active-case adapters.

History is conversation-level short-term context.  The active case is a small
structured state that lets a later turn resume an assessment; it is not a
general user-profile memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from epr_agent.infra.case_store import SQLiteCaseStore, default_case_store

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ContextSnapshot:
    history: list[dict[str, Any]]
    active_case: dict[str, Any] | None
    summary: str = ""


class HistoryGateway(Protocol):
    async def initialize(self) -> None: ...

    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot: ...

    async def save_exchange(self, user_id: str, conversation_id: str, user_message: str, assistant_message: str, metadata: dict[str, Any]) -> None: ...

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> None: ...

    async def clear_case(self, user_id: str, conversation_id: str) -> None: ...

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None: ...


class LegacyHistoryGateway:
    """Use the existing SQLite conversation store during the migration."""

    def __init__(self, case_store: SQLiteCaseStore | None = None) -> None:
        self.case_store = case_store or default_case_store()

    async def initialize(self) -> None:
        await self.case_store.initialize()
        try:
            from backend.history import init_history_store

            await init_history_store()
        except Exception as exc:  # noqa: BLE001 - local history is a graceful-degradation boundary
            logger.warning("Legacy history initialization unavailable: %s", exc)

    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot:
        history: list[dict[str, Any]] = []
        try:
            from backend.history import ensure_conversation, get_recent_history

            await ensure_conversation(user_id, conversation_id)
            history = await get_recent_history(user_id, conversation_id, max_messages)
        except Exception as exc:  # noqa: BLE001 - fall back to hot session context
            logger.warning("Conversation history load failed: %s", exc)
            try:
                from backend.memory.session_store import get_history

                history = await get_history(conversation_id)
            except Exception as fallback_exc:  # noqa: BLE001 - no history is still a valid new session
                logger.warning("Session history fallback failed: %s", fallback_exc)

        active_case = await self.case_store.load_case(user_id, conversation_id)
        summary = self._summarise_recent(history)
        return ContextSnapshot(history=history, active_case=active_case, summary=summary)

    async def save_exchange(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> None:
        try:
            from backend.history import append_exchange

            await append_exchange(
                user_id=user_id,
                conversation_id=conversation_id,
                user_msg=user_message,
                assistant_msg=assistant_message,
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001 - answer delivery must survive history outage
            logger.warning("Conversation history save failed: %s", exc)

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> None:
        await self.case_store.save_case(user_id, conversation_id, state)

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        await self.case_store.clear_case(user_id, conversation_id)

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        await self.case_store.record_run(state, started_at, ended_at)

    @staticmethod
    def _summarise_recent(history: list[dict[str, Any]]) -> str:
        parts = []
        for item in history[-4:]:
            role = item.get("role", "")
            content = " ".join(str(item.get("content", "")).split())
            if content:
                parts.append(f"{role}: {content[:240]}")
        return "\n".join(parts)
