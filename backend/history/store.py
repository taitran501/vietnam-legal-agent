"""Account-level persistent chat history backed by SQLite.

This module is intentionally dependency-light (stdlib sqlite3) so it can run
without adding heavy ORM dependencies during migration from session-only memory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from backend.config import get_settings

logger = logging.getLogger(__name__)


def _db_path() -> Path:
    settings = get_settings()
    path = getattr(settings, "history_db_path", None)
    if not path:
        # Safe fallback while config is being rolled out.
        path = Path(__file__).resolve().parents[2] / "data" / "chat_history.sqlite3"
    return Path(path)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _now_ts() -> float:
    return time.time()


def _default_title(seed: str | None) -> str:
    if not seed:
        return "New Conversation"
    text = " ".join(seed.replace("\n", " ").split()).strip()
    if not text:
        return "New Conversation"
    return text[:80] + ("..." if len(text) > 80 else "")


def _init_history_store_sync() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT,
                metadata_json TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                CHECK (role IN ('user', 'assistant', 'system'))
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                conversation_id TEXT PRIMARY KEY,
                short_summary TEXT NOT NULL,
                last_updated REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id, created_at ASC)"
        )

        conn.commit()


async def init_history_store() -> None:
    await asyncio.to_thread(_init_history_store_sync)


def _ensure_user_sync(user_id: str) -> None:
    ts = _now_ts()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(id, created_at) VALUES (?, ?)",
            (user_id, ts),
        )
        conn.commit()


def _ensure_conversation_sync(user_id: str, conversation_id: str | None, title_seed: str | None) -> str:
    _ensure_user_sync(user_id)

    cid = conversation_id or str(uuid.uuid4())
    ts = _now_ts()
    title = _default_title(title_seed)

    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id FROM conversations WHERE id = ?",
            (cid,),
        ).fetchone()

        if row is not None:
            if row["user_id"] != user_id:
                raise PermissionError("Conversation does not belong to current user")
            return cid

        conn.execute(
            """
            INSERT INTO conversations(id, user_id, title, archived, pinned, created_at, updated_at)
            VALUES (?, ?, ?, 0, 0, ?, ?)
            """,
            (cid, user_id, title, ts, ts),
        )
        conn.commit()

    return cid


async def ensure_conversation(user_id: str, conversation_id: str | None, title_seed: str | None = None) -> str:
    return await asyncio.to_thread(_ensure_conversation_sync, user_id, conversation_id, title_seed)


def _append_exchange_sync(
    user_id: str,
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    cid = _ensure_conversation_sync(user_id, conversation_id, user_msg)
    ts = _now_ts()
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages(conversation_id, role, content, model, metadata_json, created_at) VALUES (?, 'user', ?, ?, ?, ?)",
            (cid, user_msg, model, meta_json, ts),
        )
        conn.execute(
            "INSERT INTO messages(conversation_id, role, content, model, metadata_json, created_at) VALUES (?, 'assistant', ?, ?, ?, ?)",
            (cid, assistant_msg, model, meta_json, ts),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
            (ts, cid, user_id),
        )
        conn.commit()


async def append_exchange(
    user_id: str,
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await asyncio.to_thread(
        _append_exchange_sync,
        user_id,
        conversation_id,
        user_msg,
        assistant_msg,
        model,
        metadata,
    )


def _get_recent_history_sync(user_id: str, conversation_id: str, max_messages: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        owner = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if owner is None:
            return []

        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (conversation_id, max_messages),
        ).fetchall()

    items = [
        {
            "role": r["role"],
            "content": r["content"],
            "timestamp": r["created_at"],
        }
        for r in reversed(rows)
    ]
    return items


async def get_recent_history(user_id: str, conversation_id: str, max_messages: int) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_get_recent_history_sync, user_id, conversation_id, max_messages)


def _list_conversations_sync(user_id: str, limit: int, offset: int, include_archived: bool) -> list[dict[str, Any]]:
    archived_filter = "" if include_archived else "AND c.archived = 0"
    sql = f"""
    SELECT
        c.id,
        c.title,
        c.created_at,
        c.updated_at,
        c.archived,
        c.pinned,
        COALESCE(COUNT(m.id), 0) AS message_count
    FROM conversations c
    LEFT JOIN messages m ON c.id = m.conversation_id
    WHERE c.user_id = ? {archived_filter}
    GROUP BY c.id
    ORDER BY c.pinned DESC, c.updated_at DESC
    LIMIT ? OFFSET ?
    """

    with _connect() as conn:
        rows = conn.execute(sql, (user_id, limit, offset)).fetchall()

    return [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "archived": bool(r["archived"]),
            "pinned": bool(r["pinned"]),
            "message_count": int(r["message_count"]),
        }
        for r in rows
    ]


async def list_conversations(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_conversations_sync, user_id, limit, offset, include_archived)


def _get_conversation_sync(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at, archived, pinned FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            return None

        messages = conn.execute(
            "SELECT role, content, model, metadata_json, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, id ASC",
            (conversation_id,),
        ).fetchall()

    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived": bool(row["archived"]),
        "pinned": bool(row["pinned"]),
        "messages": [
            {
                "role": m["role"],
                "content": m["content"],
                "model": m["model"],
                "metadata": json.loads(m["metadata_json"]) if m["metadata_json"] else None,
                "timestamp": m["created_at"],
            }
            for m in messages
        ],
        "message_count": len(messages),
    }


async def get_conversation(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_conversation_sync, user_id, conversation_id)


def _list_messages_sync(
    user_id: str,
    conversation_id: str,
    limit: int,
    cursor: int | None,
) -> dict[str, Any]:
    """Return messages page ordered oldest->newest with cursor on message id."""
    safe_limit = max(1, min(limit, 200))

    with _connect() as conn:
        owner = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if owner is None:
            return {"messages": [], "next_cursor": None}

        if cursor is not None:
            rows = conn.execute(
                """
                SELECT id, role, content, model, metadata_json, created_at
                FROM messages
                WHERE conversation_id = ? AND id < ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, cursor, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, role, content, model, metadata_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, safe_limit),
            ).fetchall()

        if not rows:
            return {"messages": [], "next_cursor": None}

        min_id = min(r["id"] for r in rows)
        has_more = conn.execute(
            "SELECT 1 FROM messages WHERE conversation_id = ? AND id < ? LIMIT 1",
            (conversation_id, min_id),
        ).fetchone() is not None

    ordered = list(reversed(rows))
    items = [
        {
            "id": m["id"],
            "role": m["role"],
            "content": m["content"],
            "model": m["model"],
            "metadata": json.loads(m["metadata_json"]) if m["metadata_json"] else None,
            "timestamp": m["created_at"],
        }
        for m in ordered
    ]
    return {
        "messages": items,
        "next_cursor": min_id if has_more else None,
    }


async def list_messages(
    user_id: str,
    conversation_id: str,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(_list_messages_sync, user_id, conversation_id, limit, cursor)


def _rename_conversation_sync(user_id: str, conversation_id: str, title: str) -> bool:
    title_clean = " ".join(title.strip().split())
    if not title_clean:
        return False

    with _connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (title_clean[:200], _now_ts(), conversation_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


async def rename_conversation(user_id: str, conversation_id: str, title: str) -> bool:
    return await asyncio.to_thread(_rename_conversation_sync, user_id, conversation_id, title)


def _archive_conversation_sync(user_id: str, conversation_id: str, archived: bool) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET archived = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (1 if archived else 0, _now_ts(), conversation_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


async def archive_conversation(user_id: str, conversation_id: str, archived: bool = True) -> bool:
    return await asyncio.to_thread(_archive_conversation_sync, user_id, conversation_id, archived)


def _pin_conversation_sync(user_id: str, conversation_id: str, pinned: bool) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET pinned = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (1 if pinned else 0, _now_ts(), conversation_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


async def pin_conversation(user_id: str, conversation_id: str, pinned: bool = True) -> bool:
    return await asyncio.to_thread(_pin_conversation_sync, user_id, conversation_id, pinned)


def _delete_conversation_sync(user_id: str, conversation_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


async def delete_conversation(user_id: str, conversation_id: str) -> bool:
    return await asyncio.to_thread(_delete_conversation_sync, user_id, conversation_id)
