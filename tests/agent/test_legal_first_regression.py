from __future__ import annotations

import pytest

from epr_agent.agent.graph import WorkflowDependencies, run_workflow
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


class History:
    async def initialize(self): pass
    async def load(self, *_): return ContextSnapshot([], None)
    async def save_exchange(self, *_args, **_kwargs): pass
    async def save_case(self, *_args, **_kwargs): pass
    async def clear_case(self, *_args, **_kwargs): pass
    async def record_run(self, *_args, **_kwargs): pass


@pytest.mark.asyncio
async def test_article_77_is_legal_first_top_evidence_without_faq_or_repair() -> None:
    article_76 = DocumentRecord(
        content="Điều 76 có nội dung khác về EPR. " * 20,
        metadata={"Dieu": "Điều 76", "source": "Nghị định 08/2022", "Corpus_Version": "test-v1"},
        document_id="law-76", source="legal", score=0.99,
    )
    article_77 = DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế của nhà sản xuất, nhập khẩu. " * 20,
        metadata={"Dieu": "Điều 77", "source": "Nghị định 08/2022", "Corpus_Version": "test-v1"},
        document_id="law-77", source="legal", score=0.8,
    )
    deps = WorkflowDependencies(
        history=History(), cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=[article_76, article_77]),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway("Theo Điều 77, nhà sản xuất và nhập khẩu có trách nhiệm tái chế [1]."),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1),
    )

    state = await run_workflow("Điều 77 quy định gì về trách nhiệm tái chế?", user_id="u", conversation_id="c", deps=deps)

    assert state["termination_reason"] == "answer_complete"
    assert state["source"] == "legal"
    assert state["evidence"][0]["document_id"] == "law-77"
    assert "retrieve_legal" in state["action_sequence"]
    assert not any("faq" in action for action in state["action_sequence"])
    assert state["repair_count"] == 0
    assert state["citation_valid"] is True
    candidates = state["tool_results"][-1]["metadata"]["candidates"]
    assert candidates[0]["legal_anchor"] == "Điều 77"
