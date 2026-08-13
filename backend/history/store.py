"""Conversation-history facade over the unified SQLAlchemy repository.

The public functions deliberately keep the old names so the existing FastAPI
routes and regression tests continue to work.  Redis is no longer a durable
history fallback; it is limited to cache, rate limits, and short-lived UI
context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config import get_settings
from epr_agent.infra.persistence import get_persistence_store, sqlite_database_url


def _db_path() -> Path:
    settings = get_settings()
    return Path(settings.history_db_path)


def _database_url() -> str:
    settings = get_settings()
    configured = getattr(settings, "database_url", None)
    if configured:
        return str(configured)
    return sqlite_database_url(str(_db_path()))


async def _store():
    return await get_persistence_store(_database_url())


async def init_history_store() -> None:
    await (await _store()).initialize()


async def ensure_conversation(user_id: str, conversation_id: str | None, title_seed: str | None = None) -> str:
    return await (await _store()).ensure_conversation(user_id, conversation_id, title_seed)


async def append_exchange(
    user_id: str,
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
    metadata: dict[str, Any] | None = None,
) -> int | None:
    return await (await _store()).append_exchange(user_id, conversation_id, user_msg, assistant_msg, metadata)


async def resolve_assistant_message_id(user_id: str, conversation_id: str, message_index: int) -> int | None:
    return await (await _store()).resolve_assistant_message_id(user_id, conversation_id, message_index)


async def save_feedback(
    user_id: str,
    conversation_id: str,
    message_id: int,
    rating: int,
    comment: str | None = None,
) -> dict[str, Any] | None:
    return await (await _store()).save_feedback(user_id, conversation_id, message_id, rating, comment)


async def feedback_stats() -> dict[str, Any]:
    return await (await _store()).feedback_stats()


async def get_recent_history(user_id: str, conversation_id: str, max_messages: int) -> list[dict[str, Any]]:
    return await (await _store()).get_recent_history(user_id, conversation_id, max_messages)


async def get_conversation_summary(user_id: str, conversation_id: str) -> str:
    return await (await _store()).get_summary(user_id, conversation_id)


async def get_case_state(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    """Return the case workspace state, including a completed case for UI display."""

    return await (await _store()).get_case(user_id, conversation_id)


async def save_case_state(user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return await (await _store()).save_case(user_id, conversation_id, state)


async def list_conversations(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
    search: str = "",
) -> list[dict[str, Any]]:
    return await (await _store()).list_conversations(user_id, limit, offset, include_archived, search)


async def get_conversation(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    return await (await _store()).get_conversation(user_id, conversation_id)


async def list_messages(
    user_id: str, conversation_id: str, limit: int = 50, cursor: int | None = None
) -> dict[str, Any]:
    return await (await _store()).list_messages(user_id, conversation_id, limit, cursor)


async def rename_conversation(user_id: str, conversation_id: str, title: str) -> bool:
    return await (await _store()).rename_conversation(user_id, conversation_id, title)


async def archive_conversation(user_id: str, conversation_id: str, archived: bool = True) -> bool:
    return await (await _store()).archive_conversation(user_id, conversation_id, archived)


async def pin_conversation(user_id: str, conversation_id: str, pinned: bool = True) -> bool:
    return await (await _store()).pin_conversation(user_id, conversation_id, pinned)


async def delete_conversation(user_id: str, conversation_id: str) -> bool:
    return await (await _store()).delete_conversation(user_id, conversation_id)


async def get_trace(user_id: str, trace_id: str) -> dict[str, Any] | None:
    return await (await _store()).get_trace(user_id, trace_id)


async def list_traces(user_id: str, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return await (await _store()).list_traces(user_id, conversation_id, limit)
