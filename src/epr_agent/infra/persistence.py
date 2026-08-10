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

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None) -> float | None:
    return value.timestamp() if value else None


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


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
    corpus_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action_sequence: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tool_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        """Create local tables. Production startup should run Alembic first."""

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

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
            "task_type": record.task_type,
            "status": record.status,
            "facts": dict(record.facts or {}),
            "missing_facts": list(record.missing_facts or []),
            "last_query": record.last_query,
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
    ) -> None:
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
            session.add_all(
                [
                    MessageRecord(conversation_id=conversation_id, role="user", content=user_message, message_metadata={}),
                    MessageRecord(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=assistant_message,
                        message_metadata=dict(metadata or {}),
                    ),
                ]
            )
            existing = await session.get(ConversationSummaryRecord, conversation_id)
            if existing is None:
                session.add(ConversationSummaryRecord(conversation_id=conversation_id, summary=summary, updated_at=now))
            else:
                existing.summary = summary
                existing.updated_at = now

    async def get_recent_history(self, user_id: str, conversation_id: str, max_messages: int) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            if await self._owned_conversation(session, user_id, conversation_id) is None:
                return []
            result = await session.execute(
                select(MessageRecord)
                .where(MessageRecord.conversation_id == conversation_id)
                .order_by(MessageRecord.id.desc())
                .limit(max(1, max_messages))
            )
            messages = list(reversed(result.scalars().all()))
        return [
            {
                "role": message.role,
                "content": message.content,
                "timestamp": message.created_at.isoformat(),
                "metadata": dict(message.message_metadata or {}),
            }
            for message in messages
        ]

    async def get_summary(self, user_id: str, conversation_id: str) -> str:
        async with self.sessions() as session:
            if await self._owned_conversation(session, user_id, conversation_id) is None:
                return ""
            summary = await session.get(ConversationSummaryRecord, conversation_id)
            return summary.summary if summary else ""

    async def list_conversations(
        self, user_id: str, limit: int = 50, offset: int = 0, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            query = select(ConversationRecord).where(ConversationRecord.user_id == user_id)
            if not include_archived:
                query = query.where(ConversationRecord.archived.is_(False))
            result = await session.execute(
                query.order_by(ConversationRecord.pinned.desc(), ConversationRecord.updated_at.desc())
                .offset(max(0, offset))
                .limit(min(max(1, limit), 100))
            )
            conversations = result.scalars().all()
            payload: list[dict[str, Any]] = []
            for conversation in conversations:
                count = await session.scalar(
                    select(func.count(MessageRecord.id)).where(MessageRecord.conversation_id == conversation.id)
                )
                payload.append(
                    {
                        "id": conversation.id,
                        "title": conversation.title,
                        "created_at": _timestamp(conversation.created_at) or 0.0,
                        "updated_at": _timestamp(conversation.updated_at),
                        "message_count": int(count or 0),
                        "archived": conversation.archived,
                        "pinned": conversation.pinned,
                    }
                )
            return payload

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        async with self.sessions() as session:
            conversation = await self._owned_conversation(session, user_id, conversation_id)
            if conversation is None:
                return None
            result = await session.execute(
                select(MessageRecord).where(MessageRecord.conversation_id == conversation_id).order_by(MessageRecord.id)
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
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.created_at.isoformat(),
                    "metadata": dict(message.message_metadata or {}),
                }
                for message in messages
            ],
        }

    async def list_messages(
        self, user_id: str, conversation_id: str, limit: int = 50, cursor: int | None = None
    ) -> dict[str, Any]:
        async with self.sessions() as session:
            if await self._owned_conversation(session, user_id, conversation_id) is None:
                return {"conversation_id": conversation_id, "messages": [], "next_cursor": None}
            query = select(MessageRecord).where(MessageRecord.conversation_id == conversation_id)
            if cursor is not None:
                query = query.where(MessageRecord.id > cursor)
            result = await session.execute(query.order_by(MessageRecord.id).limit(min(max(1, limit), 100) + 1))
            messages = result.scalars().all()
        has_more = len(messages) > limit
        page = messages[:limit]
        return {
            "conversation_id": conversation_id,
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.created_at.isoformat(),
                    "metadata": dict(message.message_metadata or {}),
                }
                for message in page
            ],
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
        status = "ready" if not missing else "collecting"
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
        """Keep trace records operational: never duplicate raw conversation content."""

        payload = dict(value or {}) if isinstance(value, dict) else {}
        for key in ("query", "standalone_query", "history", "prompt", "answer", "content"):
            payload.pop(key, None)
        return payload

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
                "corpus_id": state.get("corpus_id"),
                "pipeline_version": state.get("pipeline_version"),
                "source": state.get("source"),
                "duration_ms": float(state.get("run_duration_ms") or max(0.0, (ended_at - started_at) * 1000)),
                "evidence_count": len(state.get("evidence") or []),
                "cache_status": state.get("cache_status"),
                "error_code": state.get("citation_error") or state.get("error"),
                "action_sequence": list(state.get("action_sequence") or []),
                "tool_results": list(state.get("tool_results") or []),
                "termination_reason": state.get("termination_reason"),
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
            "corpus_id": record.corpus_id,
            "pipeline_version": record.pipeline_version,
            "source": record.source,
            "duration_ms": record.duration_ms,
            "evidence_count": record.evidence_count,
            "cache_status": record.cache_status,
            "error_code": record.error_code,
            "action_sequence": list(record.action_sequence or []),
            "tool_results": list(record.tool_results or []),
            "termination_reason": record.termination_reason,
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
