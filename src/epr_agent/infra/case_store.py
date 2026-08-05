"""Local SQLite persistence for active cases and workflow traces.

Only the refactored workflow writes these tables.  Existing conversation history
continues to use the legacy history tables during migration.  Production can
replace this class with a PostgreSQL adapter without changing graph state.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SQLiteCaseStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS case_states (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    trace_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    task_type TEXT,
                    action_sequence_json TEXT NOT NULL,
                    tool_results_json TEXT NOT NULL,
                    termination_reason TEXT,
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation ON agent_runs(conversation_id, ended_at DESC)"
            )
            conn.commit()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _load_case_sync(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, state_json, updated_at FROM case_states WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        if row["user_id"] != user_id:
            raise PermissionError("Active case does not belong to current user")
        state = json.loads(row["state_json"])
        state["updated_at"] = row["updated_at"]
        return state

    async def load_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._load_case_sync, user_id, conversation_id)

    def _save_case_sync(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> None:
        now = time.time()
        payload = json.dumps(state, ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO case_states(conversation_id, user_id, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (conversation_id, user_id, payload, now),
            )
            conn.commit()

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save_case_sync, user_id, conversation_id, state)

    def _clear_case_sync(self, user_id: str, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM case_states WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            conn.commit()

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        await asyncio.to_thread(self._clear_case_sync, user_id, conversation_id)

    def _record_run_sync(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_runs(
                    trace_id, user_id, conversation_id, task_type,
                    action_sequence_json, tool_results_json, termination_reason,
                    started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.get("trace_id", ""),
                    state.get("user_id", ""),
                    state.get("conversation_id", ""),
                    state.get("task_type"),
                    json.dumps(state.get("action_sequence", []), ensure_ascii=False),
                    json.dumps(state.get("tool_results", []), ensure_ascii=False, default=str),
                    state.get("termination_reason"),
                    started_at,
                    ended_at,
                ),
            )
            conn.commit()

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        await asyncio.to_thread(self._record_run_sync, state, started_at, ended_at)


class PostgresCaseStore:
    """Production adapter with the same contract as ``SQLiteCaseStore``.

    SQLAlchemy is imported lazily so local development remains dependency-light.
    The application should run the same idempotent table creation during startup
    or replace it with an Alembic migration in a deployment pipeline.
    """

    def __init__(self, database_url: str) -> None:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
        else:
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        self.database_url = database_url
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(self.database_url, pool_pre_ping=True)
        return self._engine

    async def initialize(self) -> None:
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS case_states (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                )
                """
            )
            await conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    trace_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    task_type TEXT,
                    action_sequence_json TEXT NOT NULL,
                    tool_results_json TEXT NOT NULL,
                    termination_reason TEXT,
                    started_at DOUBLE PRECISION NOT NULL,
                    ended_at DOUBLE PRECISION NOT NULL
                )
                """
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation ON agent_runs(conversation_id, ended_at DESC)"
            )

    async def load_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        engine = self._get_engine()
        async with engine.connect() as conn:
            result = await conn.exec_driver_sql(
                "SELECT user_id, state_json, updated_at FROM case_states WHERE conversation_id = :conversation_id",
                {"conversation_id": conversation_id},
            )
            row = result.mappings().first()
        if row is None:
            return None
        if row["user_id"] != user_id:
            raise PermissionError("Active case does not belong to current user")
        state = json.loads(row["state_json"])
        state["updated_at"] = row["updated_at"]
        return state

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> None:
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                INSERT INTO case_states(conversation_id, user_id, state_json, updated_at)
                VALUES (:conversation_id, :user_id, :state_json, :updated_at)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    state_json = EXCLUDED.state_json,
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "state_json": json.dumps(state, ensure_ascii=False, default=str),
                    "updated_at": time.time(),
                },
            )

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "DELETE FROM case_states WHERE conversation_id = :conversation_id AND user_id = :user_id",
                {"conversation_id": conversation_id, "user_id": user_id},
            )

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                INSERT INTO agent_runs(
                    trace_id, user_id, conversation_id, task_type,
                    action_sequence_json, tool_results_json, termination_reason,
                    started_at, ended_at
                ) VALUES (:trace_id, :user_id, :conversation_id, :task_type,
                          :actions, :tools, :termination_reason, :started_at, :ended_at)
                ON CONFLICT(trace_id) DO UPDATE SET
                    action_sequence_json = EXCLUDED.action_sequence_json,
                    tool_results_json = EXCLUDED.tool_results_json,
                    termination_reason = EXCLUDED.termination_reason,
                    ended_at = EXCLUDED.ended_at
                """,
                {
                    "trace_id": state.get("trace_id", ""),
                    "user_id": state.get("user_id", ""),
                    "conversation_id": state.get("conversation_id", ""),
                    "task_type": state.get("task_type"),
                    "actions": json.dumps(state.get("action_sequence", []), ensure_ascii=False),
                    "tools": json.dumps(state.get("tool_results", []), ensure_ascii=False, default=str),
                    "termination_reason": state.get("termination_reason"),
                    "started_at": started_at,
                    "ended_at": ended_at,
                },
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def default_case_store() -> SQLiteCaseStore | PostgresCaseStore:
    """Resolve the local path lazily so importing the package needs no API key."""

    from backend.config import get_settings

    settings = get_settings()
    database_url = getattr(settings, "database_url", None)
    if database_url and str(database_url).startswith(("postgresql://", "postgres://")):
        return PostgresCaseStore(str(database_url))
    configured = getattr(settings, "history_db_path", None)
    if configured:
        return SQLiteCaseStore(configured)
    return SQLiteCaseStore(Path("data") / "chat_history.sqlite3")
