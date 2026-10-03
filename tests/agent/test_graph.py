from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.graph import (
    WorkflowDependencies,
    _append_source_version_caveat,
    _build_retrieval_queries,
    _merge_multi_query_results,
    run_workflow,
)
from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.understanding import StaticTaskUnderstandingGateway
from vietnam_legal_agent.domain.legal import explicit_anchors
from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.domain.routes import RouteType
from vietnam_legal_agent.domain.tasks import TaskUnderstanding
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.generation import StaticGenerationGateway
from vietnam_legal_agent.tools.history import ContextSnapshot
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway
from vietnam_legal_agent.tools.verifier import (
    ClaimSupportResult,
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
        content="Nội dung điều luật Bộ luật Lao động có đủ thông tin để đối chiếu nghĩa vụ và hình thức thực hiện. " * 3,
        metadata={
            "Dieu": "Điều 25",
            "source": "Bộ luật Lao động 2019",
            "source_file": "universal-corpus",
            "Corpus_Version": "multi-domain-law-v2",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "legal_anchor": "Điều 25",
            "document_id": "labor-25",
        },
        document_id="labor-25",
        score=0.91,
        source=source,
    )


@pytest.mark.asyncio
async def test_legal_lookup_uses_bounded_retrieval_and_verifies_citation():
    deps = make_dependencies(legal=[legal_doc()])

    state = await run_workflow(
        "Quy định Bộ luật Lao động về người lao động là gì?",
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
async def test_graph_removes_model_citation_placeholder_before_delivery():
    deps = make_dependencies(
        legal=[legal_doc()],
        generation=StaticGenerationGateway(
            answer_text="Điều 25 quy định về thời gian thử việc [n][1]."
        ),
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="citation-placeholder",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["answer"] == "Điều 25 quy định về thời gian thử việc [1]."


@pytest.mark.asyncio
async def test_route_contract_prevents_mismatched_task_type_from_starting_case_intake():
    deps = make_dependencies(legal=[legal_doc()])
    deps.understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type=TaskType.CASE_ASSESSMENT,
            route=RouteType.LEGAL_LOOKUP,
            standalone_query="Những loại người lao động nào thuộc thời gian thử việc Bộ luật Lao động?",
            confidence=1.0,
        )
    )

    state = await run_workflow(
        "Những loại người lao động nào thuộc thời gian thử việc Bộ luật Lao động?",
        user_id="u1",
        conversation_id="route-task-type-mismatch",
        deps=deps,
    )

    assert state["route"] == RouteType.LEGAL_LOOKUP.value
    assert state["task_type"] == TaskType.LEGAL_LOOKUP.value
    assert state["termination_reason"] == "answer_complete"
    assert state["action_sequence"][-1] != "ask_user"










@pytest.mark.asyncio
async def test_answer_cache_is_only_used_for_standalone_legal_lookup():
    cache = InMemoryAnswerCache()
    scoped = ScopedAnswerCache(cache)
    await scoped.store(
        "legal_lookup",
        "Bộ luật Lao động là gì?",
        "Cached answer about Điều 25 [1].",
        evidence=[legal_doc().to_dict()],
        citations=[{"index": 1, "document_id": "labor-25", "label": "Điều 25"}],
        source="legal",
    )
    deps = make_dependencies(cache_backend=cache)

    state = await run_workflow(
        "Bộ luật Lao động là gì?",
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
        "Bộ luật Lao động và thời gian thử việc hiện nay quy định thế nào?",
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
        "Điều 999 quy định gì về Bộ luật Lao động?",
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
        "Tìm nguồn công khai về thời gian thử việc Bộ luật Lao động.",
        user_id="u1",
        conversation_id="c5-web",
        mode="research_web",
        deps=deps,
    )

    assert "retrieve_web" in state["action_sequence"]
    assert state["route"] == "research_web"


@pytest.mark.asyncio
async def test_non_legal_corpus_miss_stops_without_web_search():
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
        "Bộ luật Lao động về người lao động được quy định thế nào?",
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
            standalone_query="Quy định Bộ luật Lao động về người lao động là gì?",
            retrieval_queries=["thời gian thử việc", "Bộ luật Lao động doanh nghiệp"],
            confidence=1.0,
        )
    )

    state = await run_workflow(
        "Bộ luật Lao động người lao động chịu trách nhiệm gì?",
        user_id="u1",
        conversation_id="multi-query-retrieval",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["retrieval_query_count"] == 3
    assert [query for _, query in deps.retrieval.calls] == [
        "Bộ luật Lao động người lao động chịu trách nhiệm gì?",
        "thời gian thử việc",
        "Quy định Bộ luật Lao động về người lao động là gì?",
    ]
    assert len(state["evidence"]) == 1
    assert state["retrieval_queries"] == []


def test_reciprocal_rank_fusion_uses_chunk_identity_across_search_queries():
    from vietnam_legal_agent.domain.models import DocumentRecord

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


def test_reciprocal_rank_fusion_weights_original_and_rewritten_queries_equally():
    from vietnam_legal_agent.domain.models import DocumentRecord

    baseline_noise = [
        DocumentRecord(f"baseline-{index}", {"_id": f"baseline-{index}"}, "source", source="legal")
        for index in range(1, 4)
    ]
    targeted_sources = [
        DocumentRecord(f"target-{index}", {"_id": f"target-{index}"}, "source", source="legal")
        for index in range(1, 4)
    ]

    merged = _merge_multi_query_results([baseline_noise, targeted_sources])
    by_content = {document.content: document for document in merged}

    assert by_content["baseline-1"].metadata["multi_query_rrf_score"] == (
        by_content["target-1"].metadata["multi_query_rrf_score"]
    )
    assert by_content["target-1"].metadata["multi_query_ranks"] == [
        {"query_index": 1, "rank": 1}
    ]


def test_retrieval_reformulations_preserve_user_anchors_and_drop_new_ones():
    queries = _build_retrieval_queries(
        "Điều 25 Bộ luật Lao động 2019 quy định gì?",
        "Điều 25 Bộ luật Lao động 2019 quy định gì?",
        [
            "Điều 26 Bộ luật Lao động 2019 quy định gì?",
            "nghĩa vụ thử việc theo nghị định này",
        ],
    )

    assert len(queries) == 2
    assert "Điều 25" in queries[1]
    assert "Bộ luật Lao động 2019" in queries[1]
    assert all("Điều 26" not in query for query in queries)


def test_retrieval_preserves_two_targeted_rewrites_before_normalized_standalone_query():
    original = "Mua máy giặt bị hỏng, shop từ chối bảo hành thì tôi có quyền gì?"
    targeted = [
        "shop từ chối bảo hành máy giặt bị hỏng",
        "trách nhiệm bảo hành sản phẩm của tổ chức kinh doanh",
    ]

    queries = _build_retrieval_queries(
        original,
        "Quyền của người tiêu dùng khi cửa hàng từ chối bảo hành máy giặt bị lỗi",
        targeted,
    )

    assert queries == [original, *targeted]


def test_source_version_caveat_is_not_added_twice_when_generation_already_caveats():
    answer = "Nội dung được trích dẫn. Dữ liệu chưa xác nhận hiệu lực hiện hành."

    assert _append_source_version_caveat(answer) == answer


@pytest.mark.asyncio
async def test_source_version_caveat_survives_a_citation_repair():
    source = legal_doc()
    source.metadata.update(
        {
            "Document_Number": "45/2019/QH14",
            "Current_Law_Support": False,
            "source_title": "Bộ luật Lao động 2019",
        }
    )
    generation = StaticGenerationGateway(answer_text="Câu trả lời không hợp lệ [99].")
    deps = make_dependencies(legal=[source], generation=generation)
    critic = StaticLegalCriticReviewer()
    deps.critic_reviewer = critic

    state = await run_workflow(
        "Điều 25 Bộ luật Lao động 2019 quy định gì?",
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
            "Document_Number": "45/2019/QH14",
            "Current_Law_Support": False,
            "source_title": "Bộ luật Lao động 2019",
        }
    )
    deps = make_dependencies(legal=[source])
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=True,
            corrected_answer="Theo Điều 25, quy định nêu đối tượng và lộ trình thực hiện thời gian thử việc.",
        )
    )

    state = await run_workflow(
        "Điều 25 Bộ luật Lao động 2019 quy định gì?",
        user_id="u1",
        conversation_id="critic-correction-citation",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["citation_valid"] is True
    assert "Điều 25 [1]" in state["answer"]
    assert state["answer"].endswith("hiệu lực hiện hành.")


@pytest.mark.asyncio
async def test_grounded_critic_correction_is_rechecked_instead_of_discarded():
    deps = make_dependencies(legal=[legal_doc()], claim_verifier=StaticClaimSupportVerifier(supported=True))
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            fatal_error=False,
            corrected_answer="Điều 25 quy định nghĩa vụ thử việc người lao động [1].",
            reason_code="draft_needs_correction",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
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
async def test_rejected_optional_critic_correction_keeps_previously_verified_answer():
    original = "Theo Điều 25 [1], người sử dụng lao động phải thực hiện nghĩa vụ theo quy định."

    class FirstPassThenReject:
        calls = 0

        async def verify(self, answer, documents, *, query=""):
            _ = query
            self.calls += 1
            supported = self.calls == 1
            return ClaimSupportResult(
                supported=supported,
                unsupported_claim_count=0 if supported else 1,
                reason_code="ok" if supported else "unsupported_claim",
                verification_status="verified" if supported else "unsupported_claim",
            )

    verifier = FirstPassThenReject()
    deps = make_dependencies(
        legal=[legal_doc()],
        generation=StaticGenerationGateway(answer_text=original),
        claim_verifier=verifier,
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=True,
            corrected_answer="Theo Điều 25 [1], người lao động chắc chắn được nghỉ ngay không cần báo trước.",
            reason_code="optional_refinement",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="reject-optional-critic-correction",
        deps=deps,
    )

    assert verifier.calls == 2
    assert state["termination_reason"] == "answer_complete"
    assert state["citation_valid"] is True
    assert state["verification_status"] == "verified"
    assert state["answer"] == original


@pytest.mark.asyncio
async def test_unusable_critic_correction_does_not_safe_stop_a_verified_answer():
    original = "Theo Điều 25 [1], thời gian thử việc phải tuân theo giới hạn luật định."
    deps = make_dependencies(
        legal=[legal_doc()],
        generation=StaticGenerationGateway(answer_text=original),
        claim_verifier=StaticClaimSupportVerifier(supported=True),
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            fatal_error=False,
            materially_nonresponsive=True,
            verification_status="unsupported_claim",
            corrected_answer="Theo Điều 25 [9], câu trả lời sửa được đưa ra.",
            reason_code="critic_rewrite_has_invalid_citation",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="unusable-critic-correction",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["citation_valid"] is True
    assert state["answer"] == original


@pytest.mark.asyncio
async def test_nonfatal_rejected_critic_correction_keeps_previously_verified_answer():
    original = "Theo Điều 25 [1], thời gian thử việc phải tuân theo giới hạn luật định."

    class FirstPassThenReject:
        calls = 0

        async def verify(self, answer, documents, *, query=""):
            _ = query
            self.calls += 1
            supported = self.calls == 1
            return ClaimSupportResult(
                supported=supported,
                unsupported_claim_count=0 if supported else 1,
                reason_code="ok" if supported else "unsupported_claim",
                verification_status="verified" if supported else "unsupported_claim",
            )

    verifier = FirstPassThenReject()
    deps = make_dependencies(
        legal=[legal_doc()],
        generation=StaticGenerationGateway(answer_text=original),
        claim_verifier=verifier,
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            fatal_error=False,
            verification_status="verified",
            corrected_answer=(
                "Thời gian thử việc tối đa do tính chất công việc quyết định [1].\n\n"
                "Người lao động chắc chắn được nghỉ ngay không cần báo trước."
            ),
            reason_code="nonfatal_optional_refinement",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="reject-nonfatal-critic-correction",
        deps=deps,
    )

    assert verifier.calls == 2
    assert state["termination_reason"] == "answer_complete"
    assert state["citation_valid"] is True
    assert state["answer"] == original


@pytest.mark.asyncio
async def test_unsupported_critic_correction_cannot_restore_original_answer_when_recheck_fails():
    original = "Theo Điều 25 [1], người lao động chắc chắn được nghỉ ngay không cần báo trước."

    class FirstPassThenReject:
        calls = 0

        async def verify(self, answer, documents, *, query=""):
            _ = answer, query
            self.calls += 1
            supported = self.calls == 1
            return ClaimSupportResult(
                supported=supported,
                unsupported_claim_count=0 if supported else 1,
                reason_code="ok" if supported else "unsupported_claim",
                verification_status="verified" if supported else "unsupported_claim",
            )

    verifier = FirstPassThenReject()
    deps = make_dependencies(
        legal=[legal_doc()],
        generation=StaticGenerationGateway(answer_text=original),
        claim_verifier=verifier,
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            fatal_error=False,
            verification_status="unsupported_claim",
            corrected_answer="Theo Điều 25 [1], nghĩa vụ phải tuân theo quy định.",
            reason_code="unsupported_legal_claim",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="unsupported-critic-correction-rejected",
        deps=deps,
    )

    assert verifier.calls == 5
    assert state["termination_reason"] != "answer_complete"
    assert state["citation_valid"] is False
    assert state["answer"] != original
    assert "chưa thể xác minh" in state["answer"].casefold()
    generation_repair = next(
        item for item in state["tool_results"] if item["tool"] == "claim_support_generation_repair"
    )
    assert generation_repair["ok"] is False


@pytest.mark.asyncio
async def test_graph_passes_user_question_to_claim_verifier():
    class CapturingVerifier:
        query = ""

        async def verify(self, answer, documents, *, query=""):
            self.query = query
            return ClaimSupportResult(supported=True, reason_code="ok", verification_status="verified")

    query = "Điều 25 Bộ luật Lao động quy định gì?"
    verifier = CapturingVerifier()
    deps = make_dependencies(legal=[legal_doc()], claim_verifier=verifier)
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(approved=True, reason_code="ok")
    )

    state = await run_workflow(
        query,
        user_id="u1",
        conversation_id="claim-verifier-query-context",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert verifier.query == query


@pytest.mark.asyncio
async def test_nonfatal_critic_concern_keeps_independently_supported_answer():
    deps = make_dependencies(
        legal=[legal_doc()],
        claim_verifier=StaticClaimSupportVerifier(supported=True),
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            fatal_error=False,
            verification_status="verified",
            reason_code="incomplete_answer",
            critique="The answer could include more detail.",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="nonfatal-critic-concern",
        deps=deps,
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["citation_valid"] is True
    critic_result = next(item for item in state["tool_results"] if item.get("tool") == "legal_critic")
    assert critic_result["ok"] is True
    assert critic_result["metadata"]["nonfatal_concern_retained"] is True


@pytest.mark.asyncio
async def test_materially_nonresponsive_critic_concern_blocks_wrong_scope_answer():
    deps = make_dependencies(
        legal=[legal_doc()],
        claim_verifier=StaticClaimSupportVerifier(supported=True),
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            fatal_error=False,
            materially_nonresponsive=True,
            verification_status="unsupported_claim",
            reason_code="answer_does_not_address_question",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="nonresponsive-critic-concern",
        deps=deps,
    )

    assert state["termination_reason"] == "citation_verification_failed"
    assert state["citation_error"] == "critic_answer_does_not_address_question"
    critic_result = next(item for item in state["tool_results"] if item.get("tool") == "legal_critic")
    assert critic_result["ok"] is False


@pytest.mark.asyncio
async def test_evidence_gate_preserves_current_law_intent_removed_by_query_rewrite():
    source = legal_doc()
    source.metadata.update(
        {
            "Document_Number": "45/2019/QH14",
            "Current_Law_Support": False,
            "source_title": "Bộ luật Lao động 2019",
        }
    )
    deps = make_dependencies(legal=[source])
    deps.understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type=TaskType.LEGAL_LOOKUP,
            route=RouteType.LEGAL_LOOKUP,
            standalone_query="Bộ luật Lao động 2019",
            explicit_anchors=explicit_anchors("Bộ luật Lao động 2019 hiện còn hiệu lực không?"),
            confidence=1.0,
        )
    )

    state = await run_workflow(
        "Bộ luật Lao động 2019 hiện còn hiệu lực không?",
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
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="c8",
        deps=deps,
    )

    assert verifier.calls == 4  # original, critic correction, and bounded generation repair checks
    assert state["termination_reason"] == "citation_verification_failed"
    assert state["citation_valid"] is False
    assert "claim_support_verifier" in [item["tool"] for item in state["tool_results"]]
    assert "claim_support_generation_repair" in [item["tool"] for item in state["tool_results"]]


@pytest.mark.asyncio
async def test_claim_verifier_correction_preserves_supported_answer_without_full_safe_stop():
    class CorrectingVerifier:
        def __init__(self):
            self.calls = 0

        async def verify(self, answer, documents, *, query=""):
            self.calls += 1
            if self.calls == 1:
                return ClaimSupportResult(
                    supported=False,
                    unsupported_claim_count=1,
                    unsupported_claim_indices=[1],
                    reason_code="claim_1_overstates_the_source",
                    verification_status="unsupported_claim",
                    corrected_answer="Theo Điều 25 [1], văn bản quy định về thời gian thử việc.",
                )
            return ClaimSupportResult(
                supported=True,
                reason_code="ok",
                verification_status="verified",
            )

    verifier = CorrectingVerifier()
    deps = make_dependencies(legal=[legal_doc()], claim_verifier=verifier)

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="claim-support-correction",
        deps=deps,
    )

    assert verifier.calls == 2
    assert state["termination_reason"] == "answer_complete"
    assert state["answer"] == "Theo Điều 25 [1], văn bản quy định về thời gian thử việc."
    assert "repair_answer" not in state["action_sequence"]
    correction = next(item for item in state["tool_results"] if item["tool"] == "claim_support_correction")
    assert correction["ok"] is True


@pytest.mark.asyncio
async def test_critic_can_repair_claim_rejection_only_after_the_repair_passes_both_checks():
    class RejectThenAcceptVerifier:
        def __init__(self):
            self.calls = 0

        async def verify(self, answer, documents, *, query=""):
            self.calls += 1
            if self.calls == 1:
                return ClaimSupportResult(
                    supported=False,
                    unsupported_claim_count=1,
                    unsupported_claim_indices=[1],
                    reason_code="claim_1_needs_narrower_wording",
                    verification_status="unsupported_claim",
                )
            return ClaimSupportResult(
                supported=True,
                reason_code="ok",
                verification_status="verified",
            )

    verifier = RejectThenAcceptVerifier()
    deps = make_dependencies(
        legal=[legal_doc()],
        generation=StaticGenerationGateway(
            answer_text="Điều 25 quy định đầy đủ quyền lợi của người lao động [1]."
        ),
        claim_verifier=verifier,
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=False,
            critique="Nên giữ lại đúng phần văn bản nguồn xác nhận.",
            reason_code="unsupported_claim",
            corrected_answer="Tài liệu trích dẫn nêu nội dung về nghĩa vụ và cách thực hiện [1].",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="critic-repairs-claim-rejection",
        deps=deps,
    )

    assert verifier.calls == 2
    assert state["termination_reason"] == "answer_complete"
    assert state["answer"] == "Tài liệu trích dẫn nêu nội dung về nghĩa vụ và cách thực hiện [1]."
    correction = next(
        item for item in state["tool_results"] if item["tool"] == "claim_support_critic_correction"
    )
    assert correction["ok"] is True
    assert correction["metadata"]["structural_citations_valid"] is True


@pytest.mark.asyncio
async def test_critic_repair_does_not_bypass_a_second_claim_verification_rejection():
    verifier = StaticClaimSupportVerifier(supported=False, reason_code="claim_not_supported")
    deps = make_dependencies(
        legal=[legal_doc()],
        claim_verifier=verifier,
    )
    deps.critic_reviewer = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=True,
            critique="Đã soát.",
            corrected_answer="Điều 25 quy định về quyền lợi người lao động [1].",
        )
    )

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="critic-repair-still-needs-support",
        deps=deps,
    )

    assert state["termination_reason"] == "citation_verification_failed"
    correction = next(
        item for item in state["tool_results"] if item["tool"] == "claim_support_critic_correction"
    )
    assert correction["ok"] is False


@pytest.mark.asyncio
async def test_generation_repair_is_reverified_before_replacing_an_unsupported_draft():
    class RejectThenAcceptVerifier:
        def __init__(self):
            self.calls = 0

        async def verify(self, answer, documents, *, query=""):
            self.calls += 1
            if self.calls == 1:
                return ClaimSupportResult(
                    supported=False,
                    unsupported_claim_count=1,
                    unsupported_claim_indices=[1],
                    reason_code="claim_needs_narrower_scope",
                    verification_status="unsupported_claim",
                )
            return ClaimSupportResult(
                supported=True,
                reason_code="ok",
                verification_status="verified",
            )

    class RepairingGeneration(StaticGenerationGateway):
        async def repair(self, answer, documents, task_type, *, query=""):
            self.repair_queries.append(query)
            return "Theo Điều 25, văn bản quy định về thời gian thử việc [1]."

    verifier = RejectThenAcceptVerifier()
    generation = RepairingGeneration(answer_text="Bản nháp có nhận định vượt quá nguồn [1].")
    deps = make_dependencies(
        legal=[legal_doc()],
        generation=generation,
        claim_verifier=verifier,
    )
    deps.critic_reviewer = None

    state = await run_workflow(
        "Điều 25 quy định gì?",
        user_id="u1",
        conversation_id="generation-repairs-claim-rejection",
        deps=deps,
    )

    assert verifier.calls == 2
    assert generation.repair_queries == ["Điều 25 quy định gì?"]
    assert state["termination_reason"] == "answer_complete"
    assert state["answer"] == "Theo Điều 25, văn bản quy định về thời gian thử việc [1]."
    repair = next(
        item for item in state["tool_results"] if item["tool"] == "claim_support_generation_repair"
    )
    assert repair["ok"] is True
    assert repair["metadata"]["structural_citations_valid"] is True
