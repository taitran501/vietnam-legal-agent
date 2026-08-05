from __future__ import annotations

import pytest

from epr_agent.infra.case_store import SQLiteCaseStore


@pytest.mark.asyncio
async def test_sqlite_case_store_persists_active_case_and_agent_run(tmp_path):
    store = SQLiteCaseStore(tmp_path / "workflow.sqlite3")
    await store.initialize()
    state = {
        "trace_id": "trace-1",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "task_type": "assess_epr_obligation",
        "facts": {"business_role": "nhà sản xuất"},
        "action_sequence": ["load_context", "ask_user"],
        "tool_results": [],
        "termination_reason": "awaiting_user_input",
    }
    await store.save_case("user-1", "conversation-1", state)
    loaded = await store.load_case("user-1", "conversation-1")
    assert loaded["facts"]["business_role"] == "nhà sản xuất"

    await store.record_run(state, 1.0, 2.0)
    await store.clear_case("user-1", "conversation-1")
    assert await store.load_case("user-1", "conversation-1") is None
