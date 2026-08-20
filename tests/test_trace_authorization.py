"""Authorization and retention tests for the trace inspection API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from backend.api.principal import Principal
from backend.api.routes import traces
from fastapi import HTTPException

from epr_agent.tracing.trace_context import TraceStore


def _request(principal: Principal) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(principal=principal))


def _settings(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(enable_trace_debug_api=enabled)


@pytest.mark.asyncio
async def test_trace_api_requires_explicit_flag_and_quality_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(traces, "get_settings", lambda: _settings(False))
    with pytest.raises(HTTPException, match="disabled") as disabled:
        await traces.recent_traces(_request(Principal("user-a", "oidc")), limit=20)
    assert disabled.value.status_code == 404

    monkeypatch.setattr(traces, "get_settings", lambda: _settings(True))
    with pytest.raises(HTTPException, match="operational quality scope") as forbidden:
        await traces.recent_traces(
            _request(Principal("user-a", "oidc", scopes=frozenset({"chat"}))),
            limit=20,
        )
    assert forbidden.value.status_code == 403


@pytest.mark.asyncio
async def test_trace_api_filters_non_ops_to_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    store = TraceStore(max_traces=10)
    owner_trace = store.create_trace("trace-a", "conversation-a", "user-a", "owner query")
    owner_trace.finish()
    other_trace = store.create_trace("trace-b", "conversation-b", "user-b", "other query")
    other_trace.finish()
    monkeypatch.setattr(traces, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(traces, "get_trace_store", lambda: store)

    principal = Principal("user-a", "oidc", scopes=frozenset({"quality:read"}))
    recent = await traces.recent_traces(_request(principal), limit=20)
    assert [item["trace_id"] for item in recent["items"]] == ["trace-a"]
    assert (await traces.trace_detail("trace-a", _request(principal)))["status"] == "success"
    assert (await traces.trace_detail("trace-b", _request(principal)))["status"] == "not_found"

    ops = Principal("ops", "service", scopes=frozenset({"ops"}))
    ops_recent = await traces.recent_traces(_request(ops), limit=20)
    assert {item["trace_id"] for item in ops_recent["items"]} == {"trace-a", "trace-b"}


def test_trace_store_has_bounded_retention() -> None:
    store = TraceStore(max_traces=2)
    for index in range(3):
        store.create_trace(f"trace-{index}", f"conversation-{index}", "user-a", f"query-{index}")

    assert store.get_trace("trace-0") is None
    assert [item["trace_id"] for item in store.list_recent_traces()] == ["trace-2", "trace-1"]


def test_persisted_trace_is_adapted_to_redacted_waterfall() -> None:
    waterfall = traces._persisted_to_waterfall(
        {
            "trace_id": "trace-persisted",
            "conversation_id": "conversation-a",
            "pipeline_version": "pipeline-v4",
            "duration_ms": 12.5,
            "started_at": 123.0,
            "events": [
                {
                    "sequence": 1,
                    "node": "retrieval",
                    "status": "completed",
                    "duration_ms": 4.0,
                    "payload": {"candidates": [{"document_id": "doc-1", "selected": True}]},
                }
            ],
            "tool_results": [{"answer": "must not be exposed"}],
        }
    )

    assert waterfall["query"] == ""
    assert waterfall["user_id"] == ""
    assert waterfall["total_duration_ms"] == 12.5
    assert waterfall["spans"][0]["attributes"]["candidates"][0]["document_id"] == "doc-1"
    assert "tool_results" not in waterfall
