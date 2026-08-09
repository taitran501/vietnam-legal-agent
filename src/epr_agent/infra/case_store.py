"""Compatibility adapters for callers that previously used a separate case DB.

The implementation now delegates case state and run traces to the unified
SQLAlchemy repository.  Keeping these names avoids breaking focused unit tests
and any older import while eliminating the former second SQLite schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .persistence import PersistenceStore, normalise_database_url, sqlite_database_url


class SQLiteCaseStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._store = PersistenceStore(sqlite_database_url(str(self.path)))

    async def initialize(self) -> None:
        await self._store.initialize()

    async def load_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return await self._store.load_case(user_id, conversation_id)

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return await self._store.save_case(user_id, conversation_id, state)

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        await self._store.clear_case(user_id, conversation_id)

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        await self._store.record_run(state, started_at, ended_at)


class PostgresCaseStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = normalise_database_url(database_url)
        self._store = PersistenceStore(self.database_url)

    async def initialize(self) -> None:
        await self._store.initialize()

    async def load_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return await self._store.load_case(user_id, conversation_id)

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return await self._store.save_case(user_id, conversation_id, state)

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        await self._store.clear_case(user_id, conversation_id)

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        await self._store.record_run(state, started_at, ended_at)

    async def close(self) -> None:
        await self._store.close()


def default_case_store() -> SQLiteCaseStore | PostgresCaseStore:
    from backend.config import get_settings

    settings = get_settings()
    database_url = getattr(settings, "database_url", None)
    if database_url and str(database_url).startswith(("postgresql://", "postgres://")):
        return PostgresCaseStore(str(database_url))
    return SQLiteCaseStore(getattr(settings, "history_db_path", Path("data") / "chat_history.sqlite3"))
