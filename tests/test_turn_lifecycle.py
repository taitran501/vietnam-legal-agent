from __future__ import annotations

import pytest

from epr_agent.infra.persistence import PersistenceStore, sqlite_database_url
from epr_agent.tools.history import UnifiedHistoryGateway
from tests.agent.v4_test_support import runtime


@pytest.mark.asyncio
async def test_cancelled_turn_keeps_partial_and_cannot_be_completed_or_rated(tmp_path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "turns.sqlite3")))
    await store.initialize()
    try:
        started = await store.begin_turn(
            "owner-a",
            "conversation-a",
            "turn-a",
            "Điều 77 quy định gì?",
            mode="auto",
            operation="message",
            replay_metadata={"query_mode": "auto", "operation": "message"},
        )
        assert started["status"] == "pending"
        assert started["user_message_id"] is not None
        assert started["assistant_message_id"] is not None
        # The in-flight user message must not be fed back into its own agent context.
        assert await store.get_recent_history("owner-a", "conversation-a", 10) == []

        assert await store.update_turn_content(
            "owner-a", "conversation-a", "turn-a", "Phần đã hiển thị."
        )
        stopped = await store.cancel_turn("owner-a", "conversation-a", "turn-a")
        stopped_again = await store.cancel_turn("owner-a", "conversation-a", "turn-a")
        assert stopped and stopped_again and stopped["status"] == stopped_again["status"] == "stopped"
        assert await store.cancel_turn("owner-b", "conversation-a", "turn-a") is None

        late = await store.finish_turn(
            "owner-a",
            "conversation-a",
            "turn-a",
            content="Đây là kết luận đầy đủ đến muộn.",
            metadata={"safe_stop_reason": ""},
            status="complete",
        )
        assert late and late["status"] == "stopped"
        assert late["content"] == "Phần đã hiển thị."
        assert await store.save_feedback(
            "owner-a", "conversation-a", int(started["assistant_message_id"]), 2
        ) is None

        conversation = await store.get_conversation("owner-a", "conversation-a")
        assert conversation is not None
        assert [message["status"] for message in conversation["messages"]] == ["complete", "stopped"]
        assert conversation["messages"][-1]["content"] == "Phần đã hiển thị."
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_replay_uses_server_descriptor_and_only_supersedes_after_success(tmp_path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "replay.sqlite3")))
    await store.initialize()
    try:
        original_descriptor = {
            "query_mode": "research_web",
            "intent": "legal_lookup",
            "operation": "message",
            "interaction_source": "quick_action",
            "case_patch": {"market_placement": "vietnam_market"},
            "fact_updates": {
                "market_placement": {
                    "value": "vietnam_market",
                    "confirmation_status": "user_confirmed",
                }
            },
        }
        original = await store.begin_turn(
            "owner",
            "conversation",
            "turn-original",
            "Tra cứu Điều 78",
            mode="research_web",
            operation="message",
            replay_metadata=original_descriptor,
        )
        original_message_id = int(original["assistant_message_id"])
        await store.finish_turn(
            "owner",
            "conversation",
            "turn-original",
            content="Câu trả lời cũ [1].",
            metadata={"replay_metadata": original_descriptor},
            status="complete",
        )

        replay = await store.begin_turn(
            "owner",
            "conversation",
            "turn-replay-failed",
            "query bị browser thay đổi",
            mode="auto",
            operation="regenerate",
            replay_metadata={"query_mode": "auto"},
            target_assistant_message_id=original_message_id,
        )
        assert replay["query"] == "Tra cứu Điều 78"
        assert replay["mode"] == "research_web"
        assert replay["replay_metadata"] == original_descriptor
        duplicate = await store.begin_turn(
            "owner",
            "conversation",
            "turn-replay-failed",
            "anything",
            mode="auto",
            operation="regenerate",
            replay_metadata={},
            target_assistant_message_id=original_message_id,
        )
        assert duplicate["assistant_message_id"] == replay["assistant_message_id"]
        await store.finish_turn(
            "owner",
            "conversation",
            "turn-replay-failed",
            content="Không thể tạo lại.",
            metadata={},
            status="failed",
            error_code="pipeline_error",
        )
        after_failure = await store.get_conversation("owner", "conversation")
        assert after_failure is not None
        assert any(message["id"] == original_message_id for message in after_failure["messages"])

        successful = await store.begin_turn(
            "owner",
            "conversation",
            "turn-replay-success",
            "",
            mode="auto",
            operation="retry",
            replay_metadata={},
            target_assistant_message_id=original_message_id,
        )
        await store.finish_turn(
            "owner",
            "conversation",
            "turn-replay-success",
            content="Câu trả lời mới [1].",
            metadata={"replay_metadata": original_descriptor},
            status="complete",
        )
        after_success = await store.get_conversation("owner", "conversation")
        assert after_success is not None
        visible_ids = {message["id"] for message in after_success["messages"]}
        assert original_message_id not in visible_ids
        assert int(successful["assistant_message_id"]) in visible_ids
        # Both replay attempts reuse the one original user message.
        assert sum(message["role"] == "user" for message in after_success["messages"]) == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_v4_stream_emits_ids_and_persists_a_stopped_partial(tmp_path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "stream.sqlite3")))
    await store.initialize()
    workflow, _, _ = runtime(answer_chunk_delay_s=0)
    workflow.deps.history = UnifiedHistoryGateway(store)
    events: list[dict] = []
    cancelled = False
    try:
        async for event in workflow.stream(
            query="Điều 77 quy định gì về EPR?",
            user_id="owner-stream",
            conversation_id="conversation-stream",
            turn_id="turn-stream",
            mode="auto",
            operation="message",
            intent_hint="legal_lookup",
            interaction_source="composer",
            case_patch={},
            fact_updates={},
            replay_metadata={},
        ):
            events.append(event)
            if event["type"] == "response_chunk" and not cancelled:
                cancelled = True
                stopped = await store.cancel_turn(
                    "owner-stream", "conversation-stream", "turn-stream"
                )
                assert stopped and stopped["status"] == "stopped"

        first = events[0]
        assert first["type"] == "status"
        assert first["stage"] == "turn_started"
        assert first["turn_id"] == "turn-stream"
        assert first["user_message_id"]
        assert first["assistant_message_id"]
        assert events[-1]["type"] == "response_stopped", {
            "count": len(events),
            "last": events[-1],
        }
        assert not any(event["type"] == "response_complete" for event in events)

        conversation = await store.get_conversation("owner-stream", "conversation-stream")
        assert conversation is not None
        assistant = [message for message in conversation["messages"] if message["role"] == "assistant"][-1]
        assert assistant["status"] == "stopped"
        assert assistant["content"]
        assert assistant["metadata"]["turn_status"] == "stopped"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_v4_completed_stream_reuses_placeholder_message_id(tmp_path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "complete.sqlite3")))
    await store.initialize()
    workflow, _, _ = runtime(answer_chunk_delay_s=0)
    workflow.deps.history = UnifiedHistoryGateway(store)
    try:
        events = [
            event
            async for event in workflow.stream(
                query="Điều 77 quy định gì về EPR?",
                user_id="owner-complete",
                conversation_id="conversation-complete",
                turn_id="turn-complete",
                mode="auto",
                operation="message",
                intent_hint="legal_lookup",
                interaction_source="composer",
                case_patch={},
                fact_updates={},
                replay_metadata={},
            )
        ]
        started = events[0]
        completed = events[-1]
        assert completed["type"] == "response_complete"
        assert str(started["assistant_message_id"]) == completed["assistant_message_id"]
        conversation = await store.get_conversation("owner-complete", "conversation-complete")
        assert conversation is not None
        assert conversation["message_count"] == 2
        assert [message["status"] for message in conversation["messages"]] == ["complete", "complete"]
    finally:
        await store.close()
