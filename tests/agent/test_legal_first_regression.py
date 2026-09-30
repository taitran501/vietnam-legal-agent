from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.graph import WorkflowDependencies, run_workflow
from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.generation import StaticGenerationGateway
from vietnam_legal_agent.tools.history import ContextSnapshot
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


class History:
    async def initialize(self): pass
    async def load(self, *_): return ContextSnapshot([], None)
    async def save_exchange(self, *_args, **_kwargs): pass
    async def save_case(self, *_args, **_kwargs): pass
    async def clear_case(self, *_args, **_kwargs): pass
    async def record_run(self, *_args, **_kwargs): pass


@pytest.mark.asyncio
async def test_article_25_is_legal_first_top_evidence_without_faq_or_repair() -> None:
    article_24 = DocumentRecord(
        content="Điều 24 quy định nội dung khác về giao kết hợp đồng lao động. " * 20,
        metadata={
            "Dieu": "Điều 24", "source": "Bộ luật Lao động 2019", "source_file": "universal-corpus",
            "Corpus_Version": "test-v1", "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1", "legal_anchor": "Điều 24",
        },
        document_id="law-24", source="legal", score=0.99,
    )
    article_25 = DocumentRecord(
        content="Điều 25 quy định thời gian thử việc tối đa đối với từng nhóm công việc. " * 20,
        metadata={
            "Dieu": "Điều 25", "source": "Bộ luật Lao động 2019", "source_file": "universal-corpus",
            "Corpus_Version": "test-v1", "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1", "legal_anchor": "Điều 25",
        },
        document_id="law-25", source="legal", score=0.8,
    )
    deps = WorkflowDependencies(
        history=History(), cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=[article_24, article_25]),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway("Theo Điều 25, thời gian thử việc được giới hạn theo nhóm công việc [1]."),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1),
    )

    state = await run_workflow("Điều 25 quy định gì về thời gian thử việc?", user_id="u", conversation_id="c", deps=deps)

    assert state["termination_reason"] == "answer_complete"
    assert state["source"] == "legal"
    assert state["evidence"][0]["document_id"] == "law-25"
    assert "retrieve_legal" in state["action_sequence"]
    assert not any("faq" in action for action in state["action_sequence"])
    assert state["repair_count"] == 0
    assert state["citation_valid"] is True
    candidates = state["tool_results"][-1]["metadata"]["candidates"]
    assert candidates[0]["legal_anchor"] == "Điều 25"
