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


class FakeHistory:
    def __init__(self, *, active_case=None, history=None):
        self.active_case = active_case
        self.history = history or []
        self.saved_cases = []
        self.saved_exchanges = []
        self.runs = []

    async def initialize(self):
        return None

    async def load(self, user_id, conversation_id, max_messages):
        return ContextSnapshot(self.history[-max_messages:], self.active_case)

    async def save_exchange(self, *args, **kwargs):
        self.saved_exchanges.append((args, kwargs))

    async def save_case(self, *args, **kwargs):
        self.saved_cases.append((args, kwargs))

    async def clear_case(self, *args, **kwargs):
        self.active_case = None

    async def record_run(self, state, started_at, ended_at):
        self.runs.append(state)


def make_dependencies(*, legal=None, faq=None, history=None, generation=None, cache_backend=None):
    return WorkflowDependencies(
        history=history or FakeHistory(),
        cache=ScopedAnswerCache(cache_backend or InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=legal or [], faq_documents=faq or []),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=generation or StaticGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
    )


def legal_doc(source="legal"):
    return DocumentRecord(
        content="Nội dung điều luật EPR có đủ thông tin để đối chiếu nghĩa vụ và hình thức thực hiện. " * 3,
        metadata={"Dieu": "Điều 77", "source": "Nghị định 08/2022/NĐ-CP"},
        document_id="law-77",
        score=0.91,
        source=source,
    )


@pytest.mark.asyncio
async def test_legal_lookup_uses_bounded_retrieval_and_verifies_citation():
    deps = make_dependencies(legal=[legal_doc()])

    state = await run_workflow(
        "Quy định EPR về bao bì là gì?",
        user_id="u1",
        conversation_id="c1",
        deps=deps,
    )

    assert state["task_type"] == "legal_lookup"
    assert state["termination_reason"] == "answer_complete"
    assert state["source"] == "legal"
    assert state["citation_valid"] is True
    assert "retrieve_legal" in state["action_sequence"]
    assert state["retrieval_actions"] <= 3


@pytest.mark.asyncio
async def test_assessment_stops_and_asks_for_missing_case_facts():
    deps = make_dependencies(legal=[legal_doc()])

    state = await run_workflow(
        "Tôi là nhà sản xuất, có phải thực hiện EPR không?",
        user_id="u1",
        conversation_id="c2",
        deps=deps,
    )

    assert state["task_type"] == "assess_epr_obligation"
    assert state["termination_reason"] == "awaiting_user_input"
    assert set(state["missing_facts"]) == {"product_or_packaging", "material"}
    assert "retrieve_legal" not in state["action_sequence"]
    assert state["answer"]


@pytest.mark.asyncio
async def test_follow_up_resumes_active_case_with_new_fact():
    history = FakeHistory(
        active_case={
            "task_type": "assess_epr_obligation",
            "facts": {"business_role": "nhà sản xuất", "product_or_packaging": "bao bì"},
        }
    )
    deps = make_dependencies(legal=[legal_doc()], history=history)

    state = await run_workflow(
        "Vật liệu là nhựa",
        user_id="u1",
        conversation_id="c3",
        deps=deps,
    )

    assert state["task_type"] == "assess_epr_obligation"
    assert state["missing_facts"] == []
    assert state["facts"]["material"] == "nhựa"
    assert state["termination_reason"] == "answer_complete"
    assert state["assessment"]["status"] == "preliminary"


@pytest.mark.asyncio
async def test_answer_cache_is_only_used_for_standalone_legal_lookup():
    cache = InMemoryAnswerCache()
    scoped = ScopedAnswerCache(cache)
    await cache.store(scoped.build_key("legal_lookup", "EPR là gì?"), "Cached answer [1].")
    deps = make_dependencies(cache_backend=cache)

    state = await run_workflow(
        "EPR là gì?",
        user_id="u1",
        conversation_id="c4",
        deps=deps,
    )

    assert state["source"] == "cache"
    assert state["termination_reason"] == "cache_hit"
    assert "retrieve_faq" not in state["action_sequence"]


@pytest.mark.asyncio
async def test_missing_corpus_evidence_uses_epr_only_web_fallback():
    deps = make_dependencies(legal=[])

    state = await run_workflow(
        "EPR và trách nhiệm tái chế hiện nay quy định thế nào?",
        user_id="u1",
        conversation_id="c5",
        deps=deps,
    )

    assert state["source"] == "web_search"
    assert state["termination_reason"] == "web_fallback"
    assert state["citation_valid"] is True
    assert "retrieve_web" in state["action_sequence"]


@pytest.mark.asyncio
async def test_non_epr_corpus_miss_stops_without_web_search():
    deps = make_dependencies(legal=[])

    state = await run_workflow(
        "Quy định về chứng khoán là gì?",
        user_id="u1",
        conversation_id="c6",
        deps=deps,
    )

    assert state["termination_reason"] == "out_of_scope"
    assert "retrieve_web" not in state["action_sequence"]


@pytest.mark.asyncio
async def test_one_citation_repair_is_allowed_then_workflow_finishes():
    generation = StaticGenerationGateway(answer_text="Câu trả lời không hợp lệ [99].")
    deps = make_dependencies(legal=[legal_doc()], generation=generation)

    state = await run_workflow(
        "EPR về bao bì được quy định thế nào?",
        user_id="u1",
        conversation_id="c7",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["repair_count"] == 1
    assert state["citation_valid"] is True
    assert "repair_answer" in state["action_sequence"]
