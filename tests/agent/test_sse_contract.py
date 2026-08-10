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
        metadata={
            "Dieu": "Điều 77", "source": "Nghị định 08/2022/NĐ-CP", "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "epr-law-structure-v2", "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1", "legal_anchor": "Điều 77",
        },
        document_id="law-77",
        source="legal",
    )
    deps = WorkflowDependencies(
        history=HistoryDouble(),
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=[doc]),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway(
            "Theo Điều 77 [1], nhà sản xuất và nhập khẩu phải đối chiếu trách nhiệm tái chế. " * 8
        ),
        planner=BoundedPlanner(),
    )

    events = [
        event
        async for event in WorkflowRuntime(deps, answer_chunk_delay_s=0).stream(
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
    chunks = [event for event in events if event["type"] == "response_chunk"]
    assert len(chunks) > 1
    assert "".join(str(event["chunk"]) for event in chunks) == complete["text"]
    assert [event["chunk_index"] for event in chunks] == list(range(1, len(chunks) + 1))
    assert {event["chunk_count"] for event in chunks} == {len(chunks)}
    verify_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "workflow_step" and event["action"] == "verify_citations"
    )
    assert verify_index < response_chunk
    steps = [event for event in events if event["type"] == "workflow_step"]
    assert [event["step"] for event in steps] == list(range(1, len(steps) + 1))
