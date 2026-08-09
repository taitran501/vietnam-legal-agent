"""Tests for persistent account-level history store."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from backend.history import store


@pytest.mark.asyncio
async def test_init_and_append_and_read(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"

    with patch("backend.history.store._db_path", return_value=db_path):
        await store.init_history_store()

        conversation_id = await store.ensure_conversation(
            user_id="u1",
            conversation_id="conv-1",
            title_seed="Hello EPR",
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
