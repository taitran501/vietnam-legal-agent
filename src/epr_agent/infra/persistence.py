"""Unified durable storage for conversations and bounded-agent state.

PostgreSQL is the production source of truth.  The same repository runs on
SQLite through ``aiosqlite`` for local development and deterministic tests, so
the API and workflow never need a second write path to Redis or raw SQLite.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, delete, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None) -> float | None:
    return value.timestamp() if value else None


class DatabaseSchemaMismatch(RuntimeError):
    """Raised when a legacy database would be unsafe to read with the current ORM."""

    code = "database_schema_mismatch"

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(
            "Database schema is incompatible with this release. "
            "Run `python -m scripts.migrate_legacy_sqlite --database <path>` first. "
            f"Detected: {', '.join(issues)}"
        )


class Base(DeclarativeBase):
    """SQLAlchemy declarative base used by Alembic and the local adapter."""


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="complete", nullable=False)
    superseded_by_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ConversationTurnRecord(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    operation: Mapped[str] = mapped_column(String(32), nullable=False, default="message")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    replay_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    user_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assistant_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_assistant_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class FeedbackRecord(Base):
    __tablename__ = "message_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ConversationSummaryRecord(Base):
    __tablename__ = "conversation_summaries"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CaseStateRecord(Base):
    __tablename__ = "case_states"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="collecting")
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    missing_facts: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_query: Mapped[str] = mapped_column(Text, default="", nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), default="legacy-v3", nullable=False)
    decision_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_states: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    as_of_date: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"

    trace_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corpus_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corpus_sha: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action_sequence: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tool_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    understanding_confidence: Mapped[float | None] = mapped_column(nullable=True)
    required_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    covered_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRunEventRecord(Base):
    __tablename__ = "agent_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.trace_id", ondelete="CASCADE"), index=True, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


_EXPECTED_SCHEMA_COLUMNS: dict[str, set[str]] = {
    "users": {"id", "created_at"},
    "conversations": {"id", "user_id", "title", "archived", "pinned", "created_at", "updated_at"},
    "messages": {
        "id", "conversation_id", "role", "content", "metadata", "turn_id", "status",
        "superseded_by_message_id", "created_at", "updated_at",
    },
    "conversation_turns": {
        "id", "conversation_id", "user_id", "query", "mode", "operation", "status", "replay_metadata",
        "user_message_id", "assistant_message_id", "target_assistant_message_id", "error_code", "created_at", "updated_at",
    },
    "conversation_summaries": {"conversation_id", "summary", "updated_at"},
    "case_states": {
        "conversation_id", "user_id", "task_type", "status", "facts", "missing_facts", "last_query",
        "schema_version", "decision_status", "issue_states", "as_of_date", "created_at", "updated_at",
    },
    "agent_runs": {
        "trace_id", "user_id", "conversation_id", "task_type", "route", "corpus_id", "corpus_sha",
        "embedding_profile", "pipeline_version", "source", "duration_ms", "evidence_count", "cache_status",
        "error_code", "action_sequence", "tool_results", "termination_reason", "outcome", "result_type",
        "understanding_confidence", "required_issue_count", "covered_issue_count", "started_at", "ended_at",
    },
    "agent_run_events": {
        "id", "trace_id", "sequence", "node", "status", "reason_code", "tool_name", "duration_ms",
        "error_code", "payload", "created_at",
    },
    "message_feedback": {
        "id", "user_id", "conversation_id", "message_id", "rating", "comment", "created_at", "updated_at",
    },
}


def _schema_snapshot(sync_connection: Any) -> tuple[set[str], dict[str, dict[str, str]]]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    columns: dict[str, dict[str, str]] = {}
    for table in tables & set(_EXPECTED_SCHEMA_COLUMNS):
        columns[table] = {
            str(item["name"]): type(item["type"]).__name__.lower()
            for item in inspector.get_columns(table)
        }
    return tables, columns


def _schema_issues(snapshot: tuple[set[str], dict[str, dict[str, str]]]) -> list[str]:
    tables, columns = snapshot
    app_tables = tables & set(_EXPECTED_SCHEMA_COLUMNS)
    if not app_tables:
        return []
    issues: list[str] = []
    for table, expected in _EXPECTED_SCHEMA_COLUMNS.items():
        if table not in tables:
            issues.append(f"{table}:missing_table")
            continue
        missing = expected - set(columns.get(table, {}))
        issues.extend(f"{table}:{name}_missing" for name in sorted(missing))
    if "metadata_json" in columns.get("messages", {}):
        issues.append("messages:legacy_metadata_json")
    if "short_summary" in columns.get("conversation_summaries", {}):
        issues.append("conversation_summaries:legacy_short_summary")
    if columns.get("conversations", {}).get("created_at") in {"float", "real", "numeric"}:
        issues.append("conversations:legacy_real_timestamp")
    if columns.get("messages", {}).get("created_at") in {"float", "real", "numeric"}:
        issues.append("messages:legacy_real_timestamp")
    return sorted(set(issues))


def normalise_database_url(database_url: str) -> str:
    """Return an async SQLAlchemy URL without mutating caller configuration."""

    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("sqlite://") and not database_url.startswith("sqlite+aiosqlite://"):
        return database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return database_url


def sqlite_database_url(path: str) -> str:
    return "sqlite+aiosqlite:///" + path.replace("\\", "/")


class PersistenceStore:
    """Repository API shared by history, active case, and agent trace code."""

    def __init__(self, database_url: str) -> None:
        self.database_url = normalise_database_url(database_url)
        self._engine: AsyncEngine | None = None
        self._sessions: async_sessionmaker | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            options: dict[str, Any] = {"pool_pre_ping": True}
            if self.database_url.startswith("sqlite"):
                options["connect_args"] = {"timeout": 10}
            self._engine = create_async_engine(self.database_url, **options)
        return self._engine

    @property
    def sessions(self) -> async_sessionmaker:
        if self._sessions is None:
            self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        return self._sessions

    async def initialize(self) -> None:
        """Create a fresh test/local schema, but never paper over a legacy schema."""

        async with self.engine.begin() as connection:
            snapshot = await connection.run_sync(_schema_snapshot)
            if not snapshot[0] & set(_EXPECTED_SCHEMA_COLUMNS):
                await connection.run_sync(Base.metadata.create_all)
                return
            issues = _schema_issues(snapshot)
            if issues:
                raise DatabaseSchemaMismatch(issues)

    async def schema_status(self) -> dict[str, Any]:
        """Return a side-effect-free schema compatibility result for readiness."""

        async with self.engine.connect() as connection:
            snapshot = await connection.run_sync(_schema_snapshot)
        issues = _schema_issues(snapshot)
        if not snapshot[0] & set(_EXPECTED_SCHEMA_COLUMNS):
            return {"status": "missing", "code": "database_schema_missing", "issues": ["application_tables_missing"]}
        if issues:
            return {"status": "incompatible", "code": DatabaseSchemaMismatch.code, "issues": issues}
        return {"status": "ready", "code": "ok", "issues": []}

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessions = None

    @staticmethod
    def _title(seed: str | None) -> str:
        text = " ".join((seed or "").split())
        if not text:
            return "New Conversation"
        return text[:80] + ("..." if len(text) > 80 else "")

    @staticmethod
    def _case_payload(record: CaseStateRecord) -> dict[str, Any]:
        return {
            "schema_version": record.schema_version,
            "task_type": record.task_type,
            "status": record.status,
            "facts": dict(record.facts or {}),
            "missing_facts": list(record.missing_facts or []),
            "last_query": record.last_query,
            "decision_status": record.decision_status,
            "issue_states": dict(record.issue_states or {}),
            "as_of_date": record.as_of_date,
            "updated_at": _timestamp(record.updated_at),
        }

    async def _ensure_user(self, session, user_id: str) -> None:
        if await session.get(UserRecord, user_id) is None:
            session.add(UserRecord(id=user_id))

    async def ensure_conversation(
        self, user_id: str, conversation_id: str | None, title_seed: str | None = None
    ) -> str:
        conversation_id = conversation_id or str(uuid.uuid4())
        async with self.sessions() as session, session.begin():
            await self._ensure_user(session, user_id)
            conversation = await session.get(ConversationRecord, conversation_id)
            if conversation is not None:
                if conversation.user_id != user_id:
                    raise PermissionError("Conversation does not belong to current user")
                return conversation_id
            session.add(
                ConversationRecord(
                    id=conversation_id,
                    user_id=user_id,
                    title=self._title(title_seed),
                )
            )
        return conversation_id

    async def _owned_conversation(self, session, user_id: str, conversation_id: str) -> ConversationRecord | None:
        conversation = await session.get(ConversationRecord, conversation_id)
        return conversation if conversation is not None and conversation.user_id == user_id else None

    async def append_exchange(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        await self.ensure_conversation(user_id, conversation_id, user_message)
        now = _utcnow()
        summary = "\n".join(
            item
            for item in (
                f"user: {' '.join(user_message.split())[:360]}" if user_message else "",
                f"assistant: {' '.join(assistant_message.split())[:360]}" if assistant_message else "",
            )
            if item
        )
        async with self.sessions() as session, session.begin():
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            if conversation is None:
                raise PermissionError("Conversation does not belong to current user")
            conversation.updated_at = now
            if conversation.title == "New Conversation" and user_message.strip():
                conversation.title = self._title(user_message)
            user_record = MessageRecord(
                conversation_id=conversation_id,
                role="user",
                content=user_message,
                message_metadata={},
                status="complete",
                updated_at=now,
            )
            assistant_record = MessageRecord(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_message,
                message_metadata=dict(metadata or {}),
                status="complete",
                updated_at=now,
            )
            session.add_all([user_record, assistant_record])
            await session.flush()
            existing = await session.get(ConversationSummaryRecord, conversation_id)
            if existing is None:
                session.add(ConversationSummaryRecord(conversation_id=conversation_id, summary=summary, updated_at=now))
            else:
                existing.summary = summary
                existing.updated_at = now
            return int(assistant_record.id)

    @staticmethod
    def _turn_payload(turn: ConversationTurnRecord, assistant: MessageRecord | None = None) -> dict[str, Any]:
        return {
            "turn_id": turn.id,
            "conversation_id": turn.conversation_id,
            "user_message_id": turn.user_message_id,
            "assistant_message_id": turn.assistant_message_id,
            "target_assistant_message_id": turn.target_assistant_message_id,
            "status": turn.status,
            "query": turn.query,
            "mode": turn.mode,
            "operation": turn.operation,
            "replay_metadata": dict(turn.replay_metadata or {}),
            "content": assistant.content if assistant is not None else "",
            "metadata": dict(assistant.message_metadata or {}) if assistant is not None else {},
            "error_code": turn.error_code,
        }

    @staticmethod
    def _message_payload(message: MessageRecord) -> dict[str, Any]:
        return {
            "id": int(message.id),
            "role": message.role,
            "content": message.content,
            "timestamp": message.created_at.isoformat(),
            "updated_at": message.updated_at.isoformat(),
            "metadata": dict(message.message_metadata or {}),
            "turn_id": message.turn_id,
            "status": message.status,
            "superseded_by_message_id": message.superseded_by_message_id,
        }

    async def begin_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        query: str,
        *,
        mode: str = "auto",
        operation: str = "message",
        replay_metadata: dict[str, Any] | None = None,
        target_assistant_message_id: int | None = None,
    ) -> dict[str, Any]:
        """Create one owned user/assistant turn, or return its idempotent existing handle."""

        await self.ensure_conversation(user_id, conversation_id, query)
        now = _utcnow()
        async with self.sessions() as session, session.begin():
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            if conversation is None:
                raise PermissionError("Conversation does not belong to current user")
            existing = await session.get(ConversationTurnRecord, turn_id)
            if existing is not None:
                if existing.user_id != user_id or existing.conversation_id != conversation_id:
                    raise PermissionError("Turn does not belong to current user")
                if (
                    existing.operation != operation
                    or existing.target_assistant_message_id != target_assistant_message_id
                    or (target_assistant_message_id is None and (existing.query != query or existing.mode != mode))
                ):
                    raise ValueError("turn_id was already used with a different request")
                assistant = await session.get(MessageRecord, existing.assistant_message_id)
                return self._turn_payload(existing, assistant)

            user_message_id: int | None = None
            if target_assistant_message_id is not None:
                target = await session.get(MessageRecord, target_assistant_message_id)
                if (
                    target is None
                    or target.conversation_id != conversation_id
                    or target.role != "assistant"
                    or target.status not in {"complete", "stopped", "failed"}
                ):
                    raise ValueError("target assistant message is not available for replay")
                user_message_id = await session.scalar(
                    select(MessageRecord.id)
                    .where(
                        MessageRecord.conversation_id == conversation_id,
                        MessageRecord.role == "user",
                        MessageRecord.id < target_assistant_message_id,
                    )
                    .order_by(MessageRecord.id.desc())
                    .limit(1)
                )
                if user_message_id is None:
                    raise ValueError("target assistant message has no preceding user message")
                user_message = await session.get(MessageRecord, user_message_id)
                if user_message is None:
                    raise ValueError("target assistant message has no preceding user message")
                query = user_message.content
                stored_replay = dict((target.message_metadata or {}).get("replay_metadata") or {})
                if stored_replay:
                    replay_metadata = stored_replay
                mode = str((replay_metadata or {}).get("query_mode") or mode)
            else:
                user_message = MessageRecord(
                    conversation_id=conversation_id,
                    role="user",
                    content=query,
                    message_metadata={},
                    turn_id=turn_id,
                    status="complete",
                    created_at=now,
                    updated_at=now,
                )
                session.add(user_message)
                await session.flush()
                user_message_id = int(user_message.id)

            assistant_message = MessageRecord(
                conversation_id=conversation_id,
                role="assistant",
                content="",
                message_metadata={"replay_metadata": dict(replay_metadata or {})},
                turn_id=turn_id,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            session.add(assistant_message)
            await session.flush()
            turn = ConversationTurnRecord(
                id=turn_id,
                conversation_id=conversation_id,
                user_id=user_id,
                query=query,
                mode=mode,
                operation=operation,
                status="pending",
                replay_metadata=dict(replay_metadata or {}),
                user_message_id=user_message_id,
                assistant_message_id=int(assistant_message.id),
                target_assistant_message_id=target_assistant_message_id,
                created_at=now,
                updated_at=now,
            )
            session.add(turn)
            conversation.updated_at = now
            if conversation.title == "New Conversation" and query.strip():
                conversation.title = self._title(query)
            await session.flush()
            return self._turn_payload(turn, assistant_message)

    async def update_turn_content(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        content: str,
    ) -> bool:
        """Persist a bounded partial response unless the user already stopped the turn."""

        async with self.sessions() as session, session.begin():
            turn = await session.get(ConversationTurnRecord, turn_id)
            if turn is None or turn.user_id != user_id or turn.conversation_id != conversation_id:
                return False
            if turn.status not in {"pending", "streaming"}:
                return False
            assistant = await session.get(MessageRecord, turn.assistant_message_id)
            if assistant is None:
                return False
            now = _utcnow()
            turn.status = "streaming"
            turn.updated_at = now
            assistant.status = "streaming"
            assistant.content = content
            assistant.updated_at = now
            return True

    async def is_turn_cancelled(self, user_id: str, conversation_id: str, turn_id: str) -> bool:
        async with self.sessions() as session:
            turn = await session.get(ConversationTurnRecord, turn_id)
            return bool(
                turn is not None
                and turn.user_id == user_id
                and turn.conversation_id == conversation_id
                and turn.status == "stopped"
            )

    async def cancel_turn(self, user_id: str, conversation_id: str, turn_id: str) -> dict[str, Any] | None:
        """Idempotently mark an owned non-terminal turn as stopped."""

        async with self.sessions() as session, session.begin():
            turn = await session.get(ConversationTurnRecord, turn_id)
            if turn is None or turn.user_id != user_id or turn.conversation_id != conversation_id:
                return None
            assistant = await session.get(MessageRecord, turn.assistant_message_id)
            if turn.status in {"pending", "streaming"}:
                now = _utcnow()
                turn.status = "stopped"
                turn.updated_at = now
                if assistant is not None:
                    assistant.status = "stopped"
                    assistant.updated_at = now
                    metadata = dict(assistant.message_metadata or {})
                    metadata["turn_status"] = "stopped"
                    assistant.message_metadata = metadata
            return self._turn_payload(turn, assistant)

    async def finish_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        *,
        content: str,
        metadata: dict[str, Any] | None = None,
        status: str = "complete",
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        """Commit the terminal assistant state without duplicating its user message."""

        if status not in {"complete", "stopped", "failed"}:
            raise ValueError("terminal turn status must be complete, stopped, or failed")
        async with self.sessions() as session, session.begin():
            turn = await session.get(ConversationTurnRecord, turn_id)
            if turn is None or turn.user_id != user_id or turn.conversation_id != conversation_id:
                return None
            assistant = await session.get(MessageRecord, turn.assistant_message_id)
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            if assistant is None or conversation is None:
                return None
            if turn.status in {"complete", "failed", "superseded"}:
                return self._turn_payload(turn, assistant)
            # Cancellation wins over a late completion from another worker.
            was_cancelled = turn.status == "stopped"
            final_status = "stopped" if was_cancelled else status
            now = _utcnow()
            # A late worker completion must not replace the bounded partial
            # text that was visible when the user pressed Stop.
            if not (was_cancelled and status == "complete"):
                assistant.content = content
            assistant.status = final_status
            assistant.updated_at = now
            assistant_metadata = dict(metadata or assistant.message_metadata or {})
            assistant_metadata["turn_status"] = final_status
            if error_code:
                assistant_metadata["error_code"] = error_code
            assistant.message_metadata = assistant_metadata
            turn.status = final_status
            turn.error_code = error_code
            turn.updated_at = now
            conversation.updated_at = now

            if final_status == "complete":
                if turn.target_assistant_message_id is not None:
                    previous = await session.get(MessageRecord, turn.target_assistant_message_id)
                    if previous is not None and previous.conversation_id == conversation_id:
                        previous.status = "superseded"
                        previous.superseded_by_message_id = int(assistant.id)
                        previous.updated_at = now
                summary_text = "\n".join(
                    item for item in (
                        f"user: {' '.join(turn.query.split())[:360]}" if turn.query else "",
                        f"assistant: {' '.join(content.split())[:360]}" if content else "",
                    ) if item
                )
                summary = await session.get(ConversationSummaryRecord, conversation_id)
                if summary is None:
                    session.add(ConversationSummaryRecord(
                        conversation_id=conversation_id,
                        summary=summary_text,
                        updated_at=now,
                    ))
                else:
                    summary.summary = summary_text
                    summary.updated_at = now
            return self._turn_payload(turn, assistant)

    async def resolve_assistant_message_id(self, user_id: str, conversation_id: str, message_index: int) -> int | None:
        """Resolve the legacy array index only inside the owned conversation."""

        async with self.sessions() as session:
            if await self._owned_conversation(session, user_id, conversation_id) is None:
                return None
            result = await session.execute(
                select(MessageRecord)
                .where(MessageRecord.conversation_id == conversation_id)
                .order_by(MessageRecord.id)
            )
            messages = list(result.scalars().all())
            if message_index < 0 or message_index >= len(messages):
                return None
            message = messages[message_index]
            return int(message.id) if message.role == "assistant" else None

    async def save_feedback(
        self,
        user_id: str,
        conversation_id: str,
        message_id: int,
        rating: int,
        comment: str | None = None,
    ) -> dict[str, Any] | None:
        """Create or update feedback after enforcing conversation ownership."""

        if rating not in {1, 2}:
            raise ValueError("rating must be 1 or 2")
        async with self.sessions() as session, session.begin():
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            message = await session.get(MessageRecord, message_id)
            if (
                conversation is None
                or message is None
                or message.conversation_id != conversation_id
                or message.role != "assistant"
                or message.status != "complete"
            ):
                return None
            result = await session.execute(
                select(FeedbackRecord).where(
                    FeedbackRecord.user_id == user_id,
                    FeedbackRecord.message_id == message_id,
                )
            )
            feedback = result.scalar_one_or_none()
            now = _utcnow()
            if feedback is None:
                feedback = FeedbackRecord(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    rating=rating,
                    comment=comment,
                    created_at=now,
                    updated_at=now,
                )
                session.add(feedback)
            else:
                feedback.rating = rating
                feedback.comment = comment
                feedback.updated_at = now
            await session.flush()
            message_metadata = dict(message.message_metadata or {})
            message_metadata["feedback"] = {"rating": rating, "comment": comment}
            message.message_metadata = message_metadata
            return {
                "id": int(feedback.id) if feedback.id else None,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "rating": rating,
                "comment": comment,
                "updated_at": _timestamp(now),
            }

    async def feedback_stats(self) -> dict[str, Any]:
        async with self.sessions() as session:
            result = await session.execute(select(FeedbackRecord.rating))
            ratings = [int(value) for value in result.scalars().all()]
        total_up = sum(1 for rating in ratings if rating == 2)
        total_down = sum(1 for rating in ratings if rating == 1)
        total = len(ratings)
        return {
            "total_up": total_up,
            "total_down": total_down,
            "total_feedback": total,
            "satisfaction_rate": round(total_up / total * 100, 1) if total else 0.0,
        }

    async def get_recent_history(self, user_id: str, conversation_id: str, max_messages: int) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            if await self._owned_conversation(session, user_id, conversation_id) is None:
                return []
            result = await session.execute(
                select(MessageRecord)
                .where(
                    MessageRecord.conversation_id == conversation_id,
                    MessageRecord.status == "complete",
                    MessageRecord.turn_id.is_(None)
                    | MessageRecord.turn_id.not_in(
                        select(ConversationTurnRecord.id).where(
                            ConversationTurnRecord.status.in_({"pending", "streaming"})
                        )
                    ),
                )
                .order_by(MessageRecord.id.desc())
                .limit(max(1, max_messages))
            )
            messages = list(reversed(result.scalars().all()))
        return [self._message_payload(message) for message in messages]

    async def get_summary(self, user_id: str, conversation_id: str) -> str:
        async with self.sessions() as session:
            if await self._owned_conversation(session, user_id, conversation_id) is None:
                return ""
            summary = await session.get(ConversationSummaryRecord, conversation_id)
            return summary.summary if summary else ""

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
        search: str = "",
    ) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            counts = (
                select(
                    MessageRecord.conversation_id.label("conversation_id"),
                    func.count(MessageRecord.id).label("message_count"),
                )
                .where(MessageRecord.status != "superseded")
                .group_by(MessageRecord.conversation_id)
                .subquery()
            )
            query = (
                select(ConversationRecord, func.coalesce(counts.c.message_count, 0))
                .outerjoin(counts, counts.c.conversation_id == ConversationRecord.id)
                .where(ConversationRecord.user_id == user_id)
            )
            if not include_archived:
                query = query.where(ConversationRecord.archived.is_(False))
            if search.strip():
                query = query.where(func.lower(ConversationRecord.title).contains(search.strip().casefold()))
            result = await session.execute(
                query.order_by(ConversationRecord.pinned.desc(), ConversationRecord.updated_at.desc())
                .offset(max(0, offset))
                .limit(min(max(1, limit), 100))
            )
            return [
                    {
                        "id": conversation.id,
                        "title": conversation.title,
                        "created_at": _timestamp(conversation.created_at) or 0.0,
                        "updated_at": _timestamp(conversation.updated_at),
                        "message_count": int(message_count or 0),
                        "archived": conversation.archived,
                        "pinned": conversation.pinned,
                    }
                for conversation, message_count in result.all()
            ]

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        async with self.sessions() as session:
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            if conversation is None:
                return None
            result = await session.execute(
                select(MessageRecord)
                .where(
                    MessageRecord.conversation_id == conversation_id,
                    MessageRecord.status != "superseded",
                )
                .order_by(MessageRecord.id)
            )
            messages = result.scalars().all()
        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": _timestamp(conversation.created_at) or 0.0,
            "updated_at": _timestamp(conversation.updated_at),
            "message_count": len(messages),
            "archived": conversation.archived,
            "pinned": conversation.pinned,
            "messages": [self._message_payload(message) for message in messages],
        }

    async def list_messages(
        self, user_id: str, conversation_id: str, limit: int = 50, cursor: int | None = None
    ) -> dict[str, Any]:
        async with self.sessions() as session:
            if await self._owned_conversation(session, user_id, conversation_id) is None:
                return {"conversation_id": conversation_id, "messages": [], "next_cursor": None}
            query = select(MessageRecord).where(
                MessageRecord.conversation_id == conversation_id,
                MessageRecord.status != "superseded",
            )
            if cursor is not None:
                query = query.where(MessageRecord.id > cursor)
            result = await session.execute(query.order_by(MessageRecord.id).limit(min(max(1, limit), 100) + 1))
            messages = result.scalars().all()
        has_more = len(messages) > limit
        page = messages[:limit]
        return {
            "conversation_id": conversation_id,
            "messages": [self._message_payload(message) for message in page],
            "next_cursor": page[-1].id if has_more and page else None,
        }

    async def _update_conversation(self, user_id: str, conversation_id: str, **changes: Any) -> bool:
        async with self.sessions() as session, session.begin():
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            if conversation is None:
                return False
            for name, value in changes.items():
                setattr(conversation, name, value)
            conversation.updated_at = _utcnow()
        return True

    async def rename_conversation(self, user_id: str, conversation_id: str, title: str) -> bool:
        return await self._update_conversation(user_id, conversation_id, title=self._title(title))

    async def archive_conversation(self, user_id: str, conversation_id: str, archived: bool = True) -> bool:
        return await self._update_conversation(user_id, conversation_id, archived=archived)

    async def pin_conversation(self, user_id: str, conversation_id: str, pinned: bool = True) -> bool:
        return await self._update_conversation(user_id, conversation_id, pinned=pinned)

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        async with self.sessions() as session, session.begin():
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            if conversation is None:
                return False
            # PostgreSQL enforces the declared foreign-key cascades. Delete
            # dependents explicitly as well so the local SQLite adapter has
            # the same behaviour even if foreign-key PRAGMAs are unavailable.
            await session.execute(delete(AgentRunRecord).where(AgentRunRecord.conversation_id == conversation_id))
            await session.execute(delete(CaseStateRecord).where(CaseStateRecord.conversation_id == conversation_id))
            await session.execute(
                delete(ConversationSummaryRecord).where(ConversationSummaryRecord.conversation_id == conversation_id)
            )
            await session.execute(delete(FeedbackRecord).where(FeedbackRecord.conversation_id == conversation_id))
            await session.execute(
                delete(ConversationTurnRecord).where(ConversationTurnRecord.conversation_id == conversation_id)
            )
            await session.execute(delete(MessageRecord).where(MessageRecord.conversation_id == conversation_id))
            await session.delete(conversation)
        return True

    async def load_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        async with self.sessions() as session:
            record = await session.get(CaseStateRecord, conversation_id)
            if record is None or record.user_id != user_id or record.status == "completed":
                return None
            return self._case_payload(record)

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        async with self.sessions() as session:
            record = await session.get(CaseStateRecord, conversation_id)
            return self._case_payload(record) if record is not None and record.user_id == user_id else None

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_conversation(user_id, conversation_id, state.get("last_query") or state.get("query"))
        now = _utcnow()
        facts = {key: value for key, value in dict(state.get("facts") or {}).items() if value}
        missing = list(state.get("missing_facts") or [])
        status = str(state.get("status") or ("ready" if not missing else "collecting"))
        async with self.sessions() as session:
            async with session.begin():
                record = await session.get(CaseStateRecord, conversation_id)
                if record is not None and record.user_id != user_id:
                    raise PermissionError("Active case does not belong to current user")
                if record is None:
                    record = CaseStateRecord(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        task_type=str(state.get("task_type") or "assess_epr_obligation"),
                        status=status,
                        facts=facts,
                        missing_facts=missing,
                        last_query=str(state.get("last_query") or state.get("query") or ""),
                        schema_version=str(state.get("schema_version") or "legacy-v3"),
                        decision_status=state.get("decision_status"),
                        issue_states=dict(state.get("issue_states") or {}),
                        as_of_date=str(state.get("as_of_date") or ""),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(record)
                else:
                    record.task_type = str(state.get("task_type") or record.task_type)
                    record.status = status
                    record.facts = facts
                    record.missing_facts = missing
                    record.last_query = str(state.get("last_query") or state.get("query") or record.last_query)
                    record.schema_version = str(state.get("schema_version") or record.schema_version)
                    record.decision_status = state.get("decision_status")
                    record.issue_states = dict(state.get("issue_states") or {})
                    record.as_of_date = str(state.get("as_of_date") or record.as_of_date)
                    record.updated_at = now
            return self._case_payload(record)

    async def complete_case(self, user_id: str, conversation_id: str) -> None:
        async with self.sessions() as session, session.begin():
            record = await session.get(CaseStateRecord, conversation_id)
            if record is not None and record.user_id == user_id:
                record.status = "completed"
                record.missing_facts = []
                record.updated_at = _utcnow()

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        """Compatibility name: completed cases are hidden from future workflow turns."""

        await self.complete_case(user_id, conversation_id)

    @staticmethod
    def _trace_time(raw: Any, fallback: datetime) -> datetime:
        if isinstance(raw, str):
            try:
                value = datetime.fromisoformat(raw)
                return value if value.tzinfo else value.replace(tzinfo=UTC)
            except ValueError:
                pass
        return fallback

    @staticmethod
    def _event_payload(value: Any) -> dict[str, Any]:
        """Persist an allowlisted operational trace, never conversation data.

        Trace debug is useful only when it shows the decision and score path.
        It must not become a second store for raw user messages, prompts, or
        generated prose.  Nested values are filtered recursively because a
        candidate object can otherwise smuggle source text through metadata.
        """

        allowed = {
            "tool", "latency_ms", "count", "error_code", "cache_status",
            "history_messages", "has_active_case", "task_type", "route",
            "is_follow_up", "explicit_anchors", "confidence", "missing_facts",
            "query_length", "documents_considered", "total_chars",
            "has_legal_metadata", "relevance_checked", "sufficient", "citation_reason",
            "citation_count", "candidates", "explicit_articles", "selected",
            "rejection_reason", "reason", "source_scope", "model", "token_usage",
            "retrieval_attempt", "evidence_status", "explicit_user_request",
            "pipeline_version", "outcome", "result_type", "required_issues", "covered_issues",
            "issue_plan", "fact_provenance", "coverage_reason",
        }
        candidate_allowed = {
            "document_id", "legal_anchor", "dense_score", "bm25_score",
            "rrf_score", "combined_score", "rerank_score", "selected",
            "rejection_reason", "rank", "shadow_rank", "cross_encoder_score",
        }
        sensitive = {"query", "standalone_query", "history", "prompt", "answer", "content", "system_prompt", "api_key"}

        def clean(item: Any, *, candidate: bool = False) -> Any:
            if isinstance(item, list):
                return [clean(entry, candidate=candidate) for entry in item][:20]
            if not isinstance(item, dict):
                return item
            result: dict[str, Any] = {}
            valid_keys = candidate_allowed if candidate else allowed
            for key, raw in item.items():
                key_text = str(key)
                if key_text in sensitive or key_text not in valid_keys:
                    continue
                if key_text == "issue_plan" and isinstance(raw, list):
                    result[key_text] = [
                        {
                            "issue_id": str(entry.get("issue_id") or ""),
                            "required_anchors": [str(anchor) for anchor in list(entry.get("required_anchors") or [])][:6],
                        }
                        for entry in raw[:20]
                        if isinstance(entry, dict)
                    ]
                elif key_text == "fact_provenance" and isinstance(raw, dict):
                    result[key_text] = {
                        str(name): {
                            "source": str(value.get("source") or ""),
                            "verified": bool(value.get("verified")),
                        }
                        for name, value in raw.items()
                        if isinstance(value, dict)
                    }
                else:
                    result[key_text] = clean(raw, candidate=(key_text == "candidates"))
            return result

        return clean(dict(value or {}) if isinstance(value, dict) else {})

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        now = _utcnow()
        async with self.sessions() as session, session.begin():
            await self._ensure_user(session, str(state.get("user_id") or "dev-local"))
            await session.flush()
            conversation_id = str(state.get("conversation_id") or "")
            if conversation_id and await session.get(ConversationRecord, conversation_id) is None:
                session.add(
                    ConversationRecord(
                        id=conversation_id,
                        user_id=str(state.get("user_id") or "dev-local"),
                        title="New Conversation",
                    )
                )
                await session.flush()
            trace_id = str(state.get("trace_id") or uuid.uuid4())
            record = await session.get(AgentRunRecord, trace_id)
            values = {
                "user_id": str(state.get("user_id") or "dev-local"),
                "conversation_id": conversation_id,
                "task_type": state.get("task_type"),
                "route": state.get("route"),
                "corpus_id": state.get("corpus_id"),
                "corpus_sha": state.get("corpus_sha"),
                "embedding_profile": state.get("embedding_profile"),
                "pipeline_version": state.get("pipeline_version"),
                "source": state.get("source"),
                "duration_ms": float(state.get("run_duration_ms") or max(0.0, (ended_at - started_at) * 1000)),
                "evidence_count": len(state.get("evidence") or []),
                "cache_status": state.get("cache_status"),
                "error_code": (
                    state.get("error")
                    or (state.get("citation_error") if state.get("citation_error") not in (None, "", "ok") else None)
                ),
                "action_sequence": list(state.get("action_sequence") or []),
                "tool_results": list(state.get("tool_results") or []),
                "termination_reason": state.get("termination_reason"),
                "outcome": state.get("outcome"),
                "result_type": state.get("result_type"),
                "understanding_confidence": state.get("understanding_confidence"),
                "required_issue_count": len(state.get("required_issues") or []),
                "covered_issue_count": len(state.get("covered_issues") or []),
                "started_at": self._trace_time(state.get("run_started_at"), now),
                "ended_at": self._trace_time(state.get("run_ended_at"), _utcnow()),
            }
            if record is None:
                session.add(AgentRunRecord(trace_id=trace_id, **values))
            else:
                for name, value in values.items():
                    setattr(record, name, value)
            await session.flush()
            await session.execute(delete(AgentRunEventRecord).where(AgentRunEventRecord.trace_id == trace_id))
            for event in state.get("trace_events") or []:
                payload = self._event_payload(event.get("payload"))
                session.add(
                    AgentRunEventRecord(
                        trace_id=trace_id,
                        sequence=int(event.get("sequence") or 0),
                        node=str(event.get("node") or "unknown"),
                        status=str(event.get("status") or "completed"),
                        reason_code=str(event.get("reason_code") or ""),
                        tool_name=str(payload.get("tool") or "") or None,
                        duration_ms=float(payload["latency_ms"]) if payload.get("latency_ms") is not None else None,
                        error_code=str(payload.get("error_code") or "") or None,
                        payload=payload,
                    )
                )

    @staticmethod
    def _run_payload(record: AgentRunRecord, events: list[AgentRunEventRecord]) -> dict[str, Any]:
        return {
            "trace_id": record.trace_id,
            "conversation_id": record.conversation_id,
            "task_type": record.task_type,
            "route": record.route,
            "corpus_id": record.corpus_id,
            "corpus_sha": record.corpus_sha,
            "embedding_profile": record.embedding_profile,
            "pipeline_version": record.pipeline_version,
            "source": record.source,
            "duration_ms": record.duration_ms,
            "evidence_count": record.evidence_count,
            "cache_status": record.cache_status,
            "error_code": record.error_code,
            "action_sequence": list(record.action_sequence or []),
            "tool_results": list(record.tool_results or []),
            "termination_reason": record.termination_reason,
            "outcome": record.outcome,
            "result_type": record.result_type,
            "understanding_confidence": record.understanding_confidence,
            "required_issue_count": record.required_issue_count,
            "covered_issue_count": record.covered_issue_count,
            "started_at": _timestamp(record.started_at),
            "ended_at": _timestamp(record.ended_at),
            "events": [
                {
                    "sequence": event.sequence,
                    "node": event.node,
                    "status": event.status,
                    "reason_code": event.reason_code,
                    "tool_name": event.tool_name,
                    "duration_ms": event.duration_ms,
                    "error_code": event.error_code,
                    "payload": dict(event.payload or {}),
                }
                for event in events
            ],
        }

    async def get_trace(self, user_id: str, trace_id: str) -> dict[str, Any] | None:
        async with self.sessions() as session:
            record = await session.get(AgentRunRecord, trace_id)
            if record is None or record.user_id != user_id:
                return None
            result = await session.execute(
                select(AgentRunEventRecord)
                .where(AgentRunEventRecord.trace_id == trace_id)
                .order_by(AgentRunEventRecord.sequence, AgentRunEventRecord.id)
            )
            return self._run_payload(record, list(result.scalars().all()))

    async def get_trace_for_ops(self, trace_id: str) -> dict[str, Any] | None:
        """Load one trace for an already-authorized operations principal."""

        async with self.sessions() as session:
            record = await session.get(AgentRunRecord, trace_id)
            if record is None:
                return None
            result = await session.execute(
                select(AgentRunEventRecord)
                .where(AgentRunEventRecord.trace_id == trace_id)
                .order_by(AgentRunEventRecord.sequence, AgentRunEventRecord.id)
            )
            return self._run_payload(record, list(result.scalars().all()))

    async def list_recent_traces(self, user_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List recent redacted traces, optionally restricted to one owner."""

        async with self.sessions() as session:
            statement = select(AgentRunRecord)
            if user_id is not None:
                statement = statement.where(AgentRunRecord.user_id == user_id)
            result = await session.execute(
                statement.order_by(AgentRunRecord.started_at.desc()).limit(min(max(1, limit), 100))
            )
            return [self._run_payload(record, []) for record in result.scalars().all()]

    async def list_traces(self, user_id: str, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            result = await session.execute(
                select(AgentRunRecord)
                .where(AgentRunRecord.user_id == user_id, AgentRunRecord.conversation_id == conversation_id)
                .order_by(AgentRunRecord.started_at.desc())
                .limit(min(max(1, limit), 50))
            )
            return [self._run_payload(record, []) for record in result.scalars().all()]


_stores: dict[str, PersistenceStore] = {}
_store_lock = asyncio.Lock()


async def get_persistence_store(database_url: str) -> PersistenceStore:
    """Return one process-local adapter per URL; no data is cached in memory."""

    url = normalise_database_url(database_url)
    async with _store_lock:
        store = _stores.get(url)
        if store is None:
            store = PersistenceStore(url)
            _stores[url] = store
        return store


async def close_persistence_stores() -> None:
    for store in list(_stores.values()):
        await store.close()
    _stores.clear()
