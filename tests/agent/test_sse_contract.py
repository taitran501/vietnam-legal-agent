from __future__ import annotations

import pytest

from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.runtime import WorkflowRuntime
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


class HistoryDouble:
    async def initialize(self):
        return None

    async def load(self, user_id, conversation_id, max_messages):
        return ContextSnapshot([], None)

    async def save_exchange(self, *args, **kwargs):
        return None

    async def save_case(self, *args, **kwargs):
        return None

    async def clear_case(self, *args, **kwargs):
        return None

    async def record_run(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_stream_preserves_legacy_events_and_adds_workflow_metadata():
    doc = DocumentRecord(
        content="Nội dung điều luật EPR đủ dài để tạo câu trả lời có nguồn. " * 4,
        metadata={"Dieu": "Điều 77"},
        document_id="law-77",
        source="legal",
    )
    deps = WorkflowDependencies(
        history=HistoryDouble(),
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=[doc]),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway(),
        planner=BoundedPlanner(),
    )

    events = [
        event
        async for event in WorkflowRuntime(deps).stream(
            query="EPR về bao bì là gì?",
            user_id="u",
            conversation_id="c",
        )
    ]
    event_types = [event["type"] for event in events]
    assert "status" in event_types
    assert "workflow_step" in event_types
    assert "response_chunk" in event_types
    assert "response_complete" in event_types
    complete = next(event for event in events if event["type"] == "response_complete")
    assert complete["task_type"] == "legal_lookup"
    assert complete["trace_id"]
    assert complete["termination_reason"] == "answer_complete"
    assert complete["citations"]
    first_step = next(index for index, event in enumerate(events) if event["type"] == "workflow_step")
    response_chunk = next(index for index, event in enumerate(events) if event["type"] == "response_chunk")
    assert first_step < response_chunk
    steps = [event for event in events if event["type"] == "workflow_step"]
    assert [event["step"] for event in steps] == list(range(1, len(steps) + 1))
