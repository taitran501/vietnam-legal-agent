from __future__ import annotations

from datetime import UTC, datetime

import pytest

from epr_agent.infra.persistence import PersistenceStore, sqlite_database_url


@pytest.mark.asyncio
async def test_trace_records_are_owner_scoped_sanitized_and_keep_wall_clock_duration(tmp_path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "trace.sqlite3")))
    await store.initialize()
    started = datetime.now(UTC).isoformat()
    state = {
        "trace_id": "trace-1", "user_id": "owner-a", "conversation_id": "conversation-a",
        "task_type": "legal_lookup", "route": "legal_lookup", "corpus_id": "epr", "corpus_sha": "a" * 64,
        "embedding_profile": "openai-text-embedding-3-small-v1", "pipeline_version": "pipeline-v3",
        "source": "legal", "evidence": [{"document_id": "law-77"}], "cache_status": "not_cacheable",
        "action_sequence": ["retrieve_legal", "finish"], "tool_results": [], "termination_reason": "answer_complete",
        "run_started_at": started, "run_ended_at": datetime.now(UTC).isoformat(), "run_duration_ms": 12.5,
        "trace_events": [{"sequence": 1, "node": "retrieve_legal", "status": "completed", "reason_code": "tool_ok", "payload": {"tool": "legal_retrieval", "query": "secret", "answer": "secret", "latency_ms": 4.2, "candidates": [{"document_id": "law-77", "content": "secret", "rerank_score": 0.9}]}}],
    }
    await store.record_run(state, 10.0, 10.1)
    trace = await store.get_trace("owner-a", "trace-1")

    assert trace is not None
    assert trace["duration_ms"] == 12.5
    assert trace["route"] == "legal_lookup"
    assert trace["corpus_sha"] == "a" * 64
    assert trace["error_code"] is None
    assert trace["events"][0]["payload"] == {"tool": "legal_retrieval", "latency_ms": 4.2, "candidates": [{"document_id": "law-77", "rerank_score": 0.9}]}
    assert await store.get_trace("owner-b", "trace-1") is None
    await store.close()
