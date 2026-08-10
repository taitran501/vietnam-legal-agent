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
from epr_agent.tools.verifier import StaticClaimSupportVerifier


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


def make_dependencies(*, legal=None, history=None, generation=None, cache_backend=None, claim_verifier=None):
    return WorkflowDependencies(
        history=history or FakeHistory(),
        cache=ScopedAnswerCache(cache_backend or InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=legal or []),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=generation or StaticGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
        claim_verifier=claim_verifier,
    )


def legal_doc(source="legal"):
    return DocumentRecord(
        content="Nội dung điều luật EPR có đủ thông tin để đối chiếu nghĩa vụ và hình thức thực hiện. " * 3,
        metadata={
            "Dieu": "Điều 77",
            "source": "Nghị định 08/2022/NĐ-CP",
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "epr-law-structure-v2",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "legal_anchor": "Điều 77",
            "document_id": "law-77",
        },
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
    assert set(state["missing_facts"]) == {"product_or_packaging", "material", "activity_scope"}
    assert "retrieve_legal" not in state["action_sequence"]
    assert state["answer"]


@pytest.mark.asyncio
async def test_follow_up_resumes_active_case_with_new_fact():
    history = FakeHistory(
        active_case={
            "task_type": "assess_epr_obligation",
            "facts": {
                "business_role": "nhà sản xuất",
                "product_or_packaging": "bao bì",
                "activity_scope": "thị trường Việt Nam",
            },
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
    await scoped.store(
        "legal_lookup",
        "EPR là gì?",
        "Cached answer about Điều 77 [1].",
        evidence=[legal_doc().to_dict()],
        citations=[{"index": 1, "document_id": "law-77", "label": "Điều 77"}],
        source="legal",
    )
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
async def test_missing_corpus_evidence_stops_and_offers_explicit_web_research():
    deps = make_dependencies(legal=[])

    state = await run_workflow(
        "EPR và trách nhiệm tái chế hiện nay quy định thế nào?",
        user_id="u1",
        conversation_id="c5",
        deps=deps,
    )

    assert state["source"] == "error"
    assert state["termination_reason"] == "insufficient_evidence"
    assert state["available_actions"] == ["research_web"]
    assert "retrieve_web" not in state["action_sequence"]


@pytest.mark.asyncio
async def test_web_research_runs_only_when_user_selects_mode():
    deps = make_dependencies(legal=[])

    state = await run_workflow(
        "Tìm nguồn công khai về trách nhiệm tái chế EPR.",
        user_id="u1",
        conversation_id="c5-web",
        mode="research_web",
        deps=deps,
    )

    assert "retrieve_web" in state["action_sequence"]
    assert state["route"] == "research_web"


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


@pytest.mark.asyncio
async def test_claim_support_verifier_can_block_a_structurally_valid_answer():
    verifier = StaticClaimSupportVerifier(supported=False, reason_code="claim_not_supported")
    deps = make_dependencies(legal=[legal_doc()], claim_verifier=verifier)

    state = await run_workflow(
        "Điều 77 quy định gì?",
        user_id="u1",
        conversation_id="c8",
        deps=deps,
    )

    assert verifier.calls == 2  # initial answer plus the one permitted repair
    assert state["termination_reason"] == "citation_verification_failed"
    assert state["citation_valid"] is False
    assert "claim_support_verifier" in [item["tool"] for item in state["tool_results"]]
