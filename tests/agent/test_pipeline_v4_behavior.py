"""Behavior contracts for the V4 case workflow.

These tests assert decisions and visible outcome states, rather than brittle
generated prose.  They are the regression guard for the incorrect generic
assessment shown by the old quick-action flow.
"""

from __future__ import annotations

import pytest

from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.v4 import V4WorkflowRuntime
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


class MemoryHistory:
    def __init__(self) -> None:
        self.case: dict | None = None

    async def initialize(self):
        return None

    async def load(self, *_args):
        return ContextSnapshot([], self.case)

    async def save_case(self, _user, _conversation, state):
        self.case = dict(state)
        return self.case

    async def clear_case(self, *_args):
        if self.case:
            self.case["status"] = "completed"

    async def save_exchange(self, *_args):
        return None

    async def record_run(self, *_args):
        return None


def legal_document(anchor: str, *, appendix: bool = False) -> DocumentRecord:
    title = "Phụ lục XXII - Tỷ lệ tái chế" if appendix else "Nghị định số 08/2022/NĐ-CP"
    return DocumentRecord(
        content=f"{anchor}. Căn cứ pháp lý để kiểm tra nghĩa vụ EPR. " * 6,
        metadata={
            "Dieu": anchor if anchor.startswith("Điều") else "",
            "legal_anchor": anchor,
            "source": title,
            "source_title": title,
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "epr-v4-test",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "provenance": "data/08_2022_ND-CP_479457.doc",
        },
        document_id=f"doc-{anchor.replace(' ', '-').replace('ụ', 'u')}",
        source="legal",
    )


def runtime(history: MemoryHistory) -> tuple[V4WorkflowRuntime, StaticRetrievalGateway]:
    retrieval = StaticRetrievalGateway(
        legal_documents=[
            legal_document("Điều 77"), legal_document("Điều 78"), legal_document("Điều 79"),
            legal_document("Điều 80"), legal_document("Điều 81"), legal_document("Phụ lục XXII", appendix=True),
        ]
    )
    deps = WorkflowDependencies(
        history=history,
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=retrieval,
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway(),
        planner=BoundedPlanner(),
    )
    return V4WorkflowRuntime(deps, answer_chunk_delay_s=0), retrieval


@pytest.mark.asyncio
async def test_assessment_action_asks_for_missing_facts_before_assessment_card():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    state = await app.run(
        query="Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?",
        user_id="v4-user", conversation_id="v4-case", intent_hint="case_assessment", interaction_source="quick_action",
    )
    assert state["route"] == "case_assessment"
    assert state["outcome"] == "needs_information"
    assert state["result_type"] == "none"
    assert state["assessment"]["status"] == "needs_information"
    assert "market_placement" in state["missing_facts"]
    assert retrieval.requests == []
    assert history.case and history.case["schema_version"] == "v4"


@pytest.mark.asyncio
async def test_completed_assessment_requires_all_mandatory_issue_evidence():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    state = await app.run(
        query=(
            "Tôi là nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, "
            "kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng."
        ),
        user_id="v4-user", conversation_id="v4-complete", intent_hint="case_assessment",
    )
    assert state["outcome"] == "completed", (state["evidence_assessment"], state["issue_states"])
    assert state["assessment"]["status"] == "likely_in_scope"
    assert set(state["required_issues"]) == set(state["covered_issues"])
    assert len(retrieval.requests) == 5
    assert all(request.issue_id for request in retrieval.requests)


@pytest.mark.asyncio
async def test_missing_appendix_evidence_is_safe_stop_not_completed_assessment():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    retrieval.legal_documents = [legal_document("Điều 77")]
    state = await app.run(
        query=(
            "Tôi là nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, "
            "kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng."
        ),
        user_id="v4-user", conversation_id="v4-no-appendix", intent_hint="case_assessment",
    )
    assert state["outcome"] == "insufficient_evidence"
    assert state["result_type"] == "none"
    assert state["termination_reason"] == "insufficient_evidence"


@pytest.mark.asyncio
async def test_v4_sse_emits_case_update_and_input_required_before_completion():
    history = MemoryHistory()
    app, _ = runtime(history)
    events = [
        event
        async for event in app.stream(
            query="Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?",
            user_id="v4-user",
            conversation_id="v4-sse",
            intent_hint="case_assessment",
            interaction_source="quick_action",
        )
    ]
    event_types = [event["type"] for event in events]
    assert "input_required" in event_types
    assert "case_update" in event_types
    complete = next(event for event in events if event["type"] == "response_complete")
    assert complete["outcome"] == "needs_information"
    assert complete["result_type"] == "none"
    assert complete["pipeline_version"] == "pipeline-v4"
