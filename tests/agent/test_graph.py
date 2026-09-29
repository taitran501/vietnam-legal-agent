from __future__ import annotations

import pytest

from epr_agent.agent.graph import (
    WorkflowDependencies,
    _append_source_version_caveat,
    _build_retrieval_queries,
    _merge_multi_query_results,
    run_workflow,
)
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.understanding import StaticTaskUnderstandingGateway
from epr_agent.domain.legal import explicit_anchors
from epr_agent.domain.models import DocumentRecord, TaskType
from epr_agent.domain.routes import RouteType
from epr_agent.domain.tasks import TaskUnderstanding
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.legal_readiness import SyntheticReadyLegalReadinessGate
from epr_agent.tools.retrieval import StaticRetrievalGateway
from epr_agent.tools.verifier import (
    LegalCriticVerdict,
    StaticClaimSupportVerifier,
    StaticLegalCriticReviewer,
)


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


def make_dependencies(
    *, legal=None, history=None, generation=None, cache_backend=None, claim_verifier=None, legal_readiness=None
):
    return WorkflowDependencies(
        history=history or FakeHistory(),
        cache=ScopedAnswerCache(cache_backend or InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=legal or []),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=generation or StaticGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
        claim_verifier=claim_verifier,
        legal_readiness=legal_readiness,
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
async def test_route_contract_prevents_mismatched_task_type_from_starting_case_intake():
    deps = make_dependencies(legal=[legal_doc()])
    deps.understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type=TaskType.CASE_ASSESSMENT,
            route=RouteType.LEGAL_LOOKUP,
            standalone_query="Những loại bao bì nào thuộc trách nhiệm tái chế EPR?",
            confidence=1.0,
        )
    )

    state = await run_workflow(
        "Những loại bao bì nào thuộc trách nhiệm tái chế EPR?",
        user_id="u1",
        conversation_id="route-task-type-mismatch",
        deps=deps,
    )

    assert state["route"] == RouteType.LEGAL_LOOKUP.value
    assert state["task_type"] == TaskType.LEGAL_LOOKUP.value
    assert state["termination_reason"] == "answer_complete"
    assert state["action_sequence"][-1] != "ask_user"


@pytest.mark.asyncio
async def test_pending_epr_readiness_is_checked_after_retrieval_and_stops_epr_evidence():
    deps = make_dependencies(
        legal=[legal_doc()],
        legal_readiness=SyntheticReadyLegalReadinessGate(ready=False, manifest_sha256="pending-manifest"),
    )

    state = await run_workflow(
        "Quy định EPR về bao bì là gì?",
        user_id="u1",
        conversation_id="pending-readiness",
        deps=deps,
    )

    assert state["termination_reason"] == "insufficient_evidence"
    assert state["citation_error"] == "legal_review_pending"
    assert state["legal_readiness_status"] == "pending"
    assert state["legal_readiness_sha"] == "pending-manifest"
    assert "retrieve_legal" in state["action_sequence"]
    assert "compose_answer" not in state["action_sequence"]
    assert state["source"] == "error"


@pytest.mark.asyncio
async def test_pending_epr_readiness_does_not_block_an_unrelated_legal_source():
    document = legal_doc()
    document.content = "Người lao động có trình độ cao đẳng được thử việc tối đa sáu mươi ngày. " * 4
    document.metadata.update(
        {
            "Dieu": "Điều 25. Thời gian thử việc",
            "legal_anchor": "Điều 25",
            "source": "Bộ luật Lao động số 45/2019/QH14",
            "source_title": "Bộ luật Lao động số 45/2019/QH14",
            "Document_Number": "45/2019/QH14",
            "Corpus_ID": "labor",
        }
    )
    deps = make_dependencies(
        legal=[document],
        generation=StaticGenerationGateway("Theo Điều 25, thời gian thử việc tối đa là sáu mươi ngày [1]."),
        legal_readiness=SyntheticReadyLegalReadinessGate(ready=False, manifest_sha256="pending-manifest"),
    )

    state = await run_workflow(
        "Thời gian thử việc tối đa theo Bộ luật Lao động là bao lâu?",
        user_id="u1",
        conversation_id="outside-readiness-scope",
        deps=deps,
    )

    assert state["legal_readiness_status"] == "pending"
    assert state["citation_error"] == "ok"
    assert state["termination_reason"] == "answer_complete"
    assert state["source"] == "legal"


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
async def test_missing_explicit_article_suppresses_unrelated_candidate_sources():
    deps = make_dependencies(legal=[legal_doc()])

    state = await run_workflow(
        "Điều 999 quy định gì về EPR?",
        user_id="u1",
        conversation_id="missing-999",
        deps=deps,
    )

    assert state["termination_reason"] == "insufficient_evidence"
    assert state["safe_stop_reason"] == "missing_provision"
    assert state["evidence"] == []
    assert state["citations"] == []


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
        "Hướng dẫn cách nấu phở bò Nam Định?",
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
async def test_model_retrieval_variants_are_searched_in_parallel_and_fused_once():
    deps = make_dependencies(legal=[legal_doc()])
    deps.understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type=TaskType.LEGAL_LOOKUP,
            route=RouteType.LEGAL_LOOKUP,
            standalone_query="Quy định EPR về bao bì là gì?",
            retrieval_queries=["trách nhiệm tái chế bao bì", "EPR doanh nghiệp"],
            confidence=1.0,
        )
    )

    state = await run_workflow(
        "Quy định EPR về bao bì là gì?",
        user_id="u1",
        conversation_id="multi-query-retrieval",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["retrieval_query_count"] == 3
    assert [query for _, query in deps.retrieval.calls] == [
        "Quy định EPR về bao bì là gì?",
        "trách nhiệm tái chế bao bì",
        "EPR doanh nghiệp",
    ]
    assert len(state["evidence"]) == 1
    assert state["retrieval_queries"] == []


def test_reciprocal_rank_fusion_uses_chunk_identity_across_search_queries():
    from epr_agent.domain.models import DocumentRecord

    first = DocumentRecord("provision A", {"_id": "chunk-a"}, "source", source="legal")
    second = DocumentRecord(
        "provision B", {"_id": "chunk-b", "semantic_score": 0.3}, "source", source="legal"
    )
    second_again = DocumentRecord(
        "provision B", {"_id": "chunk-b", "semantic_score": 0.9}, "source", source="legal"
    )
    third = DocumentRecord("provision C", {"_id": "chunk-c"}, "source", source="legal")

    merged = _merge_multi_query_results([[first, second], [second_again, third]])

    assert [document.content for document in merged] == ["provision B", "provision A", "provision C"]
    assert merged[0].metadata["multi_query_ranks"] == [
        {"query_index": 0, "rank": 2},
        {"query_index": 1, "rank": 1},
    ]
    assert merged[0].metadata["semantic_score"] == 0.9


def test_retrieval_reformulations_preserve_user_anchors_and_drop_new_ones():
    queries = _build_retrieval_queries(
        "Điều 77 Nghị định 08/2022/NĐ-CP quy định gì?",
        "Điều 77 Nghị định 08/2022/NĐ-CP quy định gì?",
        [
            "Điều 78 Nghị định 08/2022/NĐ-CP quy định gì?",
            "nghĩa vụ tái chế theo nghị định này",
        ],
    )

    assert len(queries) == 2
    assert "Điều 77" in queries[1]
    assert "08/2022/NĐ-CP" in queries[1]
    assert all("Điều 78" not in query for query in queries)


def test_source_version_caveat_is_not_added_twice_when_generation_already_caveats():
    answer = "Nội dung được trích dẫn. Dữ liệu chưa xác nhận hiệu lực hiện hành."

    assert _append_source_version_caveat(answer) == answer


@pytest.mark.asyncio
async def test_source_version_caveat_survives_a_citation_repair():
    source = legal_doc()
    source.metadata.update(
        {
            "Document_Number": "08/2022/NĐ-CP",
            "Current_Law_Support": False,
            "source_title": "Nghị định số 08/2022/NĐ-CP",
        }
    )
    generation = StaticGenerationGateway(answer_text="Câu trả lời không hợp lệ [99].")
    deps = make_dependencies(legal=[source], generation=generation)
    critic = StaticLegalCriticReviewer()
    deps.critic_reviewer = critic

    state = await run_workflow(
        "Điều 77 Nghị định 08/2022/NĐ-CP quy định gì?",
        user_id="u1",
        conversation_id="source-version-repair",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["evidence_assessment"]["source_version_only"] is True
    assert state["answer"].endswith("hiệu lực hiện hành.")
    assert critic.source_version_only_calls == [True]
    assert "repair_answer" in state["action_sequence"]


@pytest.mark.asyncio
async def test_critic_correction_without_citation_is_anchored_and_keeps_source_version_caveat():
    source = legal_doc()
    source.metadata.update(
        {
            "Document_Number": "08/2022/NĐ-CP",
            "Current_Law_Support": False,
            "source_title": "Nghị định số 08/2022/NĐ-CP",
        }
    )
    deps = make_dependencies(legal=[source])
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=True,
            corrected_answer="Theo Điều 77, quy định nêu đối tượng và lộ trình thực hiện trách nhiệm tái chế.",
        )
    )

    state = await run_workflow(
        "Điều 77 Nghị định 08/2022/NĐ-CP quy định gì?",
        user_id="u1",
        conversation_id="critic-correction-citation",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["citation_valid"] is True
    assert "Điều 77 [1]" in state["answer"]
    assert state["answer"].endswith("hiệu lực hiện hành.")


@pytest.mark.asyncio
async def test_grounded_critic_correction_is_rechecked_instead_of_discarded():
    deps = make_dependencies(legal=[legal_doc()], claim_verifier=StaticClaimSupportVerifier(supported=True))
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            fatal_error=False,
            corrected_answer="Điều 77 quy định nghĩa vụ tái chế bao bì [1].",
            reason_code="draft_needs_correction",
        )
    )

    state = await run_workflow(
        "Điều 77 quy định gì?",
        user_id="u1",
        conversation_id="critic-corrected-answer",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["citation_valid"] is True
    assert "draft_needs_correction" in {
        result.get("metadata", {}).get("reason_code")
        for result in state["tool_results"]
        if result.get("tool") == "legal_critic"
    }


@pytest.mark.asyncio
async def test_evidence_gate_preserves_current_law_intent_removed_by_query_rewrite():
    source = legal_doc()
    source.metadata.update(
        {
            "Document_Number": "08/2022/NĐ-CP",
            "Current_Law_Support": False,
            "source_title": "Nghị định số 08/2022/NĐ-CP",
        }
    )
    deps = make_dependencies(legal=[source])
    deps.understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type=TaskType.LEGAL_LOOKUP,
            route=RouteType.LEGAL_LOOKUP,
            standalone_query="Nghị định 08/2022/NĐ-CP",
            explicit_anchors=explicit_anchors("Nghị định 08/2022/NĐ-CP hiện còn hiệu lực không?"),
            confidence=1.0,
        )
    )

    state = await run_workflow(
        "Nghị định 08/2022/NĐ-CP hiện còn hiệu lực không?",
        user_id="u1",
        conversation_id="preserve-current-law-intent",
        deps=deps,
    )

    assert state["evidence_assessment"]["reason"] == "current_law_status_unverified"
    assert state["termination_reason"] == "insufficient_evidence"
    assert "hiệu lực hiện hành" in state["answer"]
    assert deps.generation.calls == []


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
