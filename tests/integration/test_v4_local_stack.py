"""Opt-in real-service tests for the Docker V4 stack.

The default pytest command remains deterministic. Set EPR_RUN_INTEGRATION=1
and EPR_API_BASE_URL when PostgreSQL, Redis, Qdrant and the backend are up.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live]


def _enabled() -> bool:
    return os.getenv("EPR_RUN_INTEGRATION", "0").strip() == "1"


@pytest.mark.asyncio
async def test_real_ready_and_v4_sse_contract() -> None:
    if not _enabled():
        pytest.skip("set EPR_RUN_INTEGRATION=1 to run against the local Docker stack")

    base_url = os.getenv("EPR_API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        ready = await client.get("/api/v1/ready")
        assert ready.status_code == 200, ready.text
        assert ready.json()["status"] == "ready"

        events: list[dict] = []
        async with client.stream(
            "POST",
            "/api/v1/chat",
            json={
                "query": "Điều 77 quy định gì về trách nhiệm tái chế?",
                "conversation_id": "integration-v4-sse",
                "intent_hint": "legal_lookup",
            },
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line.removeprefix("data:").strip()))

        assert events
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert {event["pipeline_version"] for event in events} == {"pipeline-v4"}
        complete = next(event for event in events if event["type"] == "response_complete")
        assert complete["outcome"] == "completed"
        assert complete["source"] == "legal"
        assert complete["citations"]


@pytest.mark.asyncio
async def test_real_trace_is_owner_scoped_and_has_v4_decision_events() -> None:
    if not _enabled():
        pytest.skip("set EPR_RUN_INTEGRATION=1 to run against the local Docker stack")
    if os.getenv("ENABLE_TRACE_DEBUG_API", "false").lower() != "true":
        pytest.skip("enable ENABLE_TRACE_DEBUG_API=true for trace endpoint assertions")

    base_url = os.getenv("EPR_API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            json={"query": "Điều 77 quy định gì?", "conversation_id": "integration-v4-trace", "intent_hint": "legal_lookup"},
        ) as response:
            assert response.status_code == 200
            complete = None
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    event = json.loads(line.removeprefix("data:").strip())
                    if event.get("type") == "response_complete":
                        complete = event
        assert complete and complete.get("trace_id")

        trace = await client.get(f"/api/v1/traces/{complete['trace_id']}")
        assert trace.status_code == 200, trace.text
        payload = trace.json()
        waterfall = payload["waterfall"]
        assert waterfall["metadata"]["pipeline_version"] == "pipeline-v4"
        assert waterfall["total_duration_ms"] >= 0
        assert waterfall["spans"]
        assert all("name" in span and "duration_ms" in span for span in waterfall["spans"])

        # The API-key owner is the isolation boundary. A different local owner
        # cannot be simulated without auth middleware, so the production path
        # is covered by PersistenceStore's deterministic owner test.
