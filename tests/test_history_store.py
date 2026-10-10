"""Tests for persistent account-level history store."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from backend.history import store

from vietnam_legal_agent.infra.persistence import MessageRecord, PersistenceStore, _utcnow, sqlite_database_url


@pytest.mark.asyncio
async def test_init_and_append_and_read(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"

    with patch("backend.history.store._db_path", return_value=db_path):
        await store.init_history_store()

        conversation_id = await store.ensure_conversation(
            user_id="u1",
            conversation_id="conv-1",
            title_seed="Hello law",
        )
        assert conversation_id == "conv-1"

        await store.append_exchange(
            user_id="u1",
            conversation_id="conv-1",
            user_msg="Q1",
            assistant_msg="A1",
        )

        history = await store.get_recent_history("u1", "conv-1", max_messages=10)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Q1"
        assert history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_ownership_enforced(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"

    with patch("backend.history.store._db_path", return_value=db_path):
        await store.init_history_store()
        await store.ensure_conversation("owner-a", "conv-x", "My chat")

        with pytest.raises(PermissionError):
            await store.ensure_conversation("owner-b", "conv-x", "Other")


@pytest.mark.asyncio
async def test_list_and_delete_conversation(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"

    with patch("backend.history.store._db_path", return_value=db_path):
        await store.init_history_store()
        await store.ensure_conversation("u1", "conv-1", "Title 1")
        await store.append_exchange("u1", "conv-1", "Q", "A")

        sessions = await store.list_conversations("u1", limit=10, offset=0)
        assert len(sessions) == 1
        assert sessions[0]["id"] == "conv-1"
        assert sessions[0]["message_count"] == 2

        deleted = await store.delete_conversation("u1", "conv-1")
        assert deleted is True

        sessions_after = await store.list_conversations("u1", limit=10, offset=0)
        assert sessions_after == []


@pytest.mark.asyncio
async def test_message_cursor_pagination(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"

    with patch("backend.history.store._db_path", return_value=db_path):
        await store.init_history_store()
        await store.ensure_conversation("u1", "conv-page", "Paged")

        # 6 messages total (3 exchanges)
        await store.append_exchange("u1", "conv-page", "Q1", "A1")
        await store.append_exchange("u1", "conv-page", "Q2", "A2")
        await store.append_exchange("u1", "conv-page", "Q3", "A3")

        page1 = await store.list_messages("u1", "conv-page", limit=4, cursor=None)
        assert len(page1["messages"]) == 4
        assert page1["next_cursor"] is not None

        page2 = await store.list_messages("u1", "conv-page", limit=4, cursor=page1["next_cursor"])
        assert len(page2["messages"]) == 2
        assert page2["next_cursor"] is None


@pytest.mark.asyncio
async def test_pin_and_unpin_conversation(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"

    with patch("backend.history.store._db_path", return_value=db_path):
        await store.init_history_store()
        await store.ensure_conversation("u1", "conv-pin", "Pin me")

        pinned = await store.pin_conversation("u1", "conv-pin", True)
        assert pinned is True
        conv = await store.get_conversation("u1", "conv-pin")
        assert conv is not None and conv["pinned"] is True

        unpinned = await store.pin_conversation("u1", "conv-pin", False)
        assert unpinned is True
        conv2 = await store.get_conversation("u1", "conv-pin")
        assert conv2 is not None and conv2["pinned"] is False


@pytest.mark.asyncio
async def test_list_conversations_supports_server_side_title_search(tmp_path: Path):
    db_path = tmp_path / "search.sqlite3"

    with patch("backend.history.store._db_path", return_value=db_path):
        await store.init_history_store()
        await store.ensure_conversation("u-search", "conv-legal", "Quyền lợi người lao động")
        await store.ensure_conversation("u-search", "conv-other", "Chào hỏi")
        await store.append_exchange("u-search", "conv-legal", "Điều 25?", "Câu trả lời")

        results = await store.list_conversations("u-search", search="NGƯỜI LAO ĐỘNG")

    assert [item["id"] for item in results] == ["conv-legal"]
    assert results[0]["message_count"] == 2


@pytest.mark.asyncio
async def test_history_alternation_consistency_after_cancelled_turn(tmp_path: Path):
    """Interrupted turns must not leave orphaned user messages or consecutive user turns."""
    db_path = tmp_path / "alternation.sqlite3"
    p_store = PersistenceStore(sqlite_database_url(str(db_path)))
    await p_store.initialize()
    try:
        # Turn 1: user "Q1" -> assistant "A1" (complete)
        await p_store.begin_turn("u1", "conv-alt", "turn-1", "Q1", mode="auto", operation="message")
        await p_store.finish_turn("u1", "conv-alt", "turn-1", content="A1", status="complete")

        # Turn 2: user "Q2" -> cancelled mid-flight (stopped)
        await p_store.begin_turn("u1", "conv-alt", "turn-2", "Q2", mode="auto", operation="message")
        await p_store.cancel_turn("u1", "conv-alt", "turn-2")

        # After cancellation: history must drop the orphaned Q2 from the stopped turn
        history_after_cancel = await p_store.get_recent_history("u1", "conv-alt", max_messages=10)
        assert len(history_after_cancel) == 2
        assert [m["role"] for m in history_after_cancel] == ["user", "assistant"]
        assert [m["content"] for m in history_after_cancel] == ["Q1", "A1"]

        # Turn 3: user "Q3" -> assistant "A3" (complete)
        await p_store.begin_turn("u1", "conv-alt", "turn-3", "Q3", mode="auto", operation="message")
        await p_store.finish_turn("u1", "conv-alt", "turn-3", content="A3", status="complete")

        # History must contain strictly alternating [user, assistant, user, assistant]
        history_final = await p_store.get_recent_history("u1", "conv-alt", max_messages=10)
        assert len(history_final) == 4
        assert [m["role"] for m in history_final] == ["user", "assistant", "user", "assistant"]
        assert [m["content"] for m in history_final] == ["Q1", "A1", "Q3", "A3"]
    finally:
        await p_store.close()


@pytest.mark.asyncio
async def test_history_alternation_drops_trailing_orphaned_user_and_deduplicates(tmp_path: Path):
    """Sanitize consecutive identical roles and drop trailing uncompleted user prompts."""
    db_path = tmp_path / "dedup.sqlite3"
    p_store = PersistenceStore(sqlite_database_url(str(db_path)))
    await p_store.initialize()
    try:
        await p_store.ensure_conversation("u1", "conv-dedup", "Title")
        # Direct session insertion to simulate consecutive user messages and trailing user
        now = _utcnow()
        async with p_store.sessions() as session, session.begin():
            session.add(MessageRecord(conversation_id="conv-dedup", role="user", content="Q1_old", status="complete", created_at=now, updated_at=now))
            session.add(MessageRecord(conversation_id="conv-dedup", role="user", content="Q1_new", status="complete", created_at=now, updated_at=now))
            session.add(MessageRecord(conversation_id="conv-dedup", role="assistant", content="A1", status="complete", created_at=now, updated_at=now))
            session.add(MessageRecord(conversation_id="conv-dedup", role="user", content="Q2_trailing", status="complete", created_at=now, updated_at=now))

        history = await p_store.get_recent_history("u1", "conv-dedup", max_messages=10)
        # Q1_old was superseded by Q1_new, A1 is assistant, Q2_trailing is dropped
        assert len(history) == 2
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert [m["content"] for m in history] == ["Q1_new", "A1"]
    finally:
        await p_store.close()

