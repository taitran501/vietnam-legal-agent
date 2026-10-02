import pytest

from vietnam_legal_agent.domain.legal import LegalAnchor
from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.tools.evidence import (
    EvidenceEvaluator,
    document_matches_anchor,
    filter_universal_retrieval_neighbors,
    legal_claim_segments,
    legal_relevance_checker,
    propagate_list_item_citations,
    verify_citations,
    verify_web_citations,
)


def document():
    return DocumentRecord(
        content=(
            "Điều 36 Bộ luật Lao động quy định quyền đơn phương chấm dứt hợp đồng "
            "và thời hạn báo trước cho người lao động. "
        ) * 4,
        metadata={
            "Dieu": "Điều 36",
            "legal_anchor": "Điều 36",
            "source": "Bộ luật Lao động 2019",
            "source_file": "tests/fixtures/multi_domain_legal_sources.json",
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
            "Corpus_Version": "test-v3",
            "Corpus_SHA256": "test-corpus-sha",
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
        },
        document_id="labor-law-36",
        source="legal",
    )


def test_evidence_evaluator_requires_document_and_source_metadata():
    evaluator = EvidenceEvaluator(min_chars=20)
    result = evaluator.evaluate("quy định pháp luật", [document()], TaskType.LEGAL_LOOKUP)
    assert result.sufficient is True
    assert result.reason == "ok"

    short = DocumentRecord("x", {}, "bad", source="legal")
    assert evaluator.evaluate("quy định pháp luật", [short], TaskType.LEGAL_LOOKUP).sufficient is False


def test_citation_verifier_checks_each_sentence_in_a_paragraph():
    answer = (
        "Theo Điều 36, người lao động có quyền chấm dứt hợp đồng [1]. "
        "Người lao động phải được trả lương trong thời gian này."
    )

    valid, _citations, reason = verify_citations(answer, [document()], TaskType.LEGAL_LOOKUP)

    assert valid is False
    assert reason == "legal_claim_without_citation"


@pytest.mark.asyncio
async def test_claim_support_verifier_sends_each_sentence_as_a_separate_claim(monkeypatch):
    import json

    from vietnam_legal_agent.tools.verifier import ClaimSupportResult, StructuredClaimSupportVerifier

    captured = {}

    class Model:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            captured["payload"] = json.loads(messages[1][1].split("\n", 1)[1])
            return ClaimSupportResult(supported=False, reason_code="unsupported_claims_reported")

    monkeypatch.setattr("vietnam_legal_agent.infra.llm_instances.get_llm_smart", lambda: Model())
    answer = (
        "Theo Điều 36, người lao động có quyền chấm dứt hợp đồng [1]. "
        "Người lao động phải được trả lương trong thời gian này."
    )

    await StructuredClaimSupportVerifier().verify(answer, [document()])

    claims = captured["payload"]["claims"]
    assert len(claims) == 2
    assert claims[0]["citation_indices"] == [1]
    assert claims[1]["citation_indices"] == []


def test_evidence_evaluator_rejects_explicitly_unresolved_current_law_source():
    evaluator = EvidenceEvaluator(min_chars=20)
    unresolved = document()
    unresolved.metadata["Current_Law_Support"] = False

    result = evaluator.evaluate("Điều 36 hiện hành", [unresolved], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "current_law_status_unverified"


def test_evidence_evaluator_allows_an_exact_source_version_lookup_with_a_warning():
    unresolved = document()
    unresolved.metadata.update(
        {
            "Current_Law_Support": False,
            "semantic_score": 0.6773,
            "rerank_score": 0.3177,
            "combined_score": 0.0474,
        }
    )

    result = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    ).evaluate(
        "Điều 36 Bộ luật Lao động 2019 quy định gì?",
        [unresolved],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True
    assert result.source_version_only is True
    assert result.has_superseded_sources is True
    assert result.relevance_checked is False
    assert any("current legal status is unverified" in warning for warning in result.temporal_warnings)


def test_generic_lookup_can_be_answered_with_a_caveat_from_one_unresolved_instrument():
    unresolved = document()
    unresolved.metadata.update(
        {
            "Current_Law_Support": False,
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
            "semantic_score": 0.9,
        }
    )
    checked_queries: list[str] = []

    def relevant(query, _documents):
        checked_queries.append(query)
        return query == "thời hạn báo trước"

    result = EvidenceEvaluator(min_chars=20, relevance_checker=relevant).evaluate(
        "Người sử dụng lao động phải báo trước bao lâu?",
        [unresolved],
        TaskType.LEGAL_LOOKUP,
        relevance_queries=["thời hạn báo trước"],
    )

    assert result.sufficient is True
    assert result.source_version_only is True
    assert result.relevance_checked is True
    assert checked_queries == [
        "Người sử dụng lao động phải báo trước bao lâu?",
        "thời hạn báo trước",
    ]


def test_ordinary_lookup_allows_mixed_status_chunks_from_one_instrument():
    unresolved = document()
    unresolved.metadata.update(
        {
            "Current_Law_Support": False,
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
        }
    )
    verified = document()
    verified.metadata.update(
        {
            "Current_Law_Support": True,
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
        }
    )

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Người sử dụng lao động có thể chấm dứt hợp đồng lao động trong trường hợp nào?",
        [unresolved, verified],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True
    assert result.source_version_only is True
    assert result.has_superseded_sources is True


def test_simple_legal_lookup_can_use_an_unresolved_source_version():
    unresolved = document()
    unresolved.metadata.update(
        {
            "Current_Law_Support": False,
            "Effective_Status": "unknown",
            "semantic_score": 0.9,
        }
    )
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate(
        "Người sử dụng lao động phải báo trước bao lâu?",
        [unresolved],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True, result.reason
    assert result.source_version_only is True
    assert result.relevance_checked is True
    assert any("chưa xác nhận nội dung hiện hành" in warning for warning in result.temporal_warnings)


@pytest.mark.parametrize(
    ("query", "task_type"),
    [
        ("Bộ luật Lao động 2019 hiện còn hiệu lực không?", TaskType.LEGAL_LOOKUP),
        ("Nghĩa vụ của tôi theo pháp luật là gì?", TaskType.CASE_ASSESSMENT),
    ],
)
def test_source_version_scoping_does_not_relax_current_status_or_case_advice(query, task_type):
    unresolved = document()
    unresolved.metadata.update(
        {
            "Current_Law_Support": False,
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
        }
    )

    result = EvidenceEvaluator(min_chars=20).evaluate(query, [unresolved], task_type)

    assert result.sufficient is False
    assert result.source_version_only is False


def test_exact_named_article_source_is_not_rejected_by_generic_relevance_score():
    exact = DocumentRecord(
        content=(
            "Điều 41 quy định nghĩa vụ của người sử dụng lao động khi đơn phương "
            "chấm dứt hợp đồng lao động trái pháp luật. "
        )
        * 5,
        metadata={
            "source_article": "Điều 41",
            "legal_anchor": "Điều 41. Nghĩa vụ của người sử dụng lao động khi đơn phương chấm dứt hợp đồng lao động trái pháp luật",
            "Document_Number": "45/2019/QH14",
            "source_title": "Điều 41 Bộ luật số 45/2019/QH14",
            "topic": "Lao động",
            "source_kind": "legal_corpus",
            "corpus_source": "universal_legal",
        },
        document_id="universal:45/2019/QH14",
        score=0.0,
        source="Pháp điển & Luật Quốc gia",
    )
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate(
        "Điều 41 Bộ luật Lao động 2019 quy định gì?",
        [exact],
        TaskType.LEGAL_LOOKUP,
        expected_anchors=[
            LegalAnchor(document_title="Bộ luật Lao động 2019", article="Điều 41"),
        ],
    )

    assert result.sufficient is True
    assert result.relevance_checked is False


def test_current_status_question_has_a_specific_stop_when_corpus_has_no_status_metadata():
    article = DocumentRecord(
        content="Điều 41 quy định nghĩa vụ của người sử dụng lao động khi chấm dứt hợp đồng trái pháp luật. " * 3,
        metadata={
            "source_article": "Điều 41",
            "legal_anchor": "Điều 41",
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
            "source": "Văn bản pháp luật",
            "source_kind": "legal_corpus",
            "corpus_source": "universal_legal",
        },
        document_id="labor-code-41",
        source="legal",
    )

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Điều 41 Bộ luật Lao động 2019 hiện nay còn hiệu lực không?",
        [article],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is False
    assert result.reason == "current_law_status_unverified"
    assert result.documents_considered == 1


def test_clause_amendment_support_flag_does_not_verify_instrument_current_status():
    article = DocumentRecord(
        content="Điều 92 quy định về điều kiện hoạt động. " * 5,
        metadata={
            "legal_anchor": "Điều 92",
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
            "Current_Law_Support": True,
            "Effective_Status": "base_source",
            "source": "Bộ luật Lao động 2019",
        },
        document_id="law-08-92",
        source="legal",
    )

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Bộ luật Lao động 2019 hiện còn hiệu lực không?",
        [article],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is False
    assert result.reason == "current_law_status_unverified"


def test_current_status_requires_explicit_review_and_a_known_status():
    article = DocumentRecord(
        content="Điều 92 quy định về điều kiện hoạt động. " * 5,
        metadata={
            "legal_anchor": "Điều 92",
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
            "Current_Law_Support": True,
            "Current_Law_Status_Verified": True,
            "Effective_Status": "active",
            "source": "Bộ luật Lao động 2019",
        },
        document_id="law-08-92-reviewed",
        source="legal",
    )

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Bộ luật Lao động 2019 hiện còn hiệu lực không?",
        [article],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True
    assert result.reason == "ok"


def test_official_web_relevance_does_not_require_a_vector_score():
    web_article = DocumentRecord(
        content="Điều 41 quy định nghĩa vụ của người sử dụng lao động khi đơn phương chấm dứt hợp đồng trái pháp luật. " * 2,
        metadata={
            "title": "Điều 41 Bộ luật Lao động",
            "official_url": "https://vbpl.vn/example",
            "authority": "official",
            "source_kind": "official_web",
        },
        document_id="web-labor-41",
        source="web",
    )
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=lambda _query, _documents: False)

    result = evaluator.evaluate(
        "Điều 41 Bộ luật Lao động quy định gì?",
        [web_article],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True
    assert result.relevance_checked is True


def test_official_web_source_with_the_wrong_article_fails_anchor_relevance():
    web_article = DocumentRecord(
        content="Điều 40 quy định về quyền đơn phương chấm dứt hợp đồng lao động. " * 3,
        metadata={
            "title": "Điều 40 Bộ luật Lao động",
            "official_url": "https://vbpl.vn/example",
            "authority": "official",
            "source_kind": "official_web",
        },
        document_id="web-labor-40",
        source="web",
    )

    result = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    ).evaluate("Điều 41 Bộ luật Lao động quy định gì?", [web_article], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_ordinary_reference_to_current_document_does_not_trigger_current_law_gate():
    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Một quy định pháp luật chưa có trong văn bản hiện tại là gì?",
        [document()],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.reason == "ok"


@pytest.mark.parametrize(
    ("query", "task_type", "expected_reason"),
    [
        (
            "Điều 36 Bộ luật Lao động 2019 hiện hành quy định gì?",
            TaskType.LEGAL_LOOKUP,
            "current_law_status_unverified",
        ),
        (
            "Điều 36 Bộ luật Lao động 2019 áp dụng cho công ty tôi không?",
            TaskType.CASE_ASSESSMENT,
            "superseded_or_unresolved_source",
        ),
    ],
)
def test_evidence_evaluator_keeps_current_law_and_case_advice_fail_closed(query, task_type, expected_reason):
    unresolved = document()
    unresolved.metadata.update(
        {
            "Current_Law_Support": False,
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
        }
    )

    result = EvidenceEvaluator(min_chars=20).evaluate(query, [unresolved], task_type)

    assert result.sufficient is False
    assert result.reason == expected_reason
    assert result.source_version_only is False


def test_evidence_evaluator_preserves_legacy_documents_without_amendment_metadata():
    evaluator = EvidenceEvaluator(min_chars=20)
    assert evaluator.evaluate("Điều 36", [document()], TaskType.LEGAL_LOOKUP).sufficient is True


def test_evidence_evaluator_requires_the_requested_clause_and_point():
    evaluator = EvidenceEvaluator(min_chars=20)
    detailed = document()
    detailed.metadata.update(
        {
            "Document_Number": "45/2019/QH14",
            "Khoan": "Khoản 2",
            "Diem": "Điểm a",
            "legal_anchor": "45/2019/QH14 | Điều 36 | Khoản 2 | Điểm a",
        }
    )

    exact = LegalAnchor(
        document_number="45/2019/QH14",
        article="Điều 36",
        clause="Khoản 2",
        point="Điểm a",
    )
    assert evaluator.evaluate("Điều 36", [detailed], TaskType.LEGAL_LOOKUP, expected_anchors=[exact]).sufficient is True

    wrong_point = exact.model_copy(update={"point": "Điểm b"})
    assert evaluator.evaluate("Điều 36", [detailed], TaskType.LEGAL_LOOKUP, expected_anchors=[wrong_point]).reason == "explicit_anchor_not_found"


def test_evidence_evaluator_rejects_a_nearby_article_from_the_wrong_instrument():
    wrong_instrument = document()
    wrong_instrument.metadata.update(
        {
            "Document_Number": "45/2019/QH14",
            "legal_anchor": "45/2019/QH14 | Điều 36",
        }
    )
    requested = LegalAnchor(document_number="08/2026/QH16", article="Điều 36")

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Luật số 08/2026/QH16 Điều 36 quy định gì?",
        [wrong_instrument],
        TaskType.LEGAL_LOOKUP,
        expected_anchors=[requested],
    )

    assert result.sufficient is False
    assert result.reason == "source_relevance_mismatch"


def test_evidence_evaluator_accepts_canonical_instrument_number_metadata():
    exact = document()
    exact.metadata.update(
        {
            "instrument_number": "08/2026/QH16",
            "legal_anchor": "08/2026/QH16 | Điều 36",
        }
    )
    requested = LegalAnchor(document_number="08/2026/QH16", article="Điều 36")

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Luật số 08/2026/QH16 Điều 36 quy định gì?",
        [exact],
        TaskType.LEGAL_LOOKUP,
        expected_anchors=[requested],
    )

    assert result.sufficient is True


def test_evidence_evaluator_matches_an_explicit_appendix_anchor():
    appendix = document()
    appendix.metadata.update(
        {
            "legal_anchor": "Phụ lục I",
            "Dieu": "",
            "Document_Number": "45/2019/QH14",
            "source": "Bộ luật Lao động 2019 - Phụ lục I",
        }
    )
    requested = LegalAnchor(document_number="45/2019/QH14", appendix="Phụ lục I")

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Phụ lục I quy định gì?",
        [appendix],
        TaskType.LEGAL_LOOKUP,
        expected_anchors=[requested],
    )

    assert result.sufficient is True


def test_relevance_gate_rejects_nearest_but_weak_unanchored_documents():
    weak = document()
    weak.metadata["rerank_score"] = 0.31
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    result = evaluator.evaluate("Luật lao động của nước ngoài nói gì?", [weak], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_relevance_gate_keeps_explicit_legal_anchor_even_when_its_score_is_low():
    exact = document()
    exact.metadata.update({"rerank_score": 0.31, "explicit_match": True})
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    assert evaluator.evaluate("Điều 36 quy định gì?", [exact], TaskType.LEGAL_LOOKUP).sufficient is True


def test_relevance_gate_stops_when_user_explicitly_requests_an_absent_rule():
    strong_but_unrelated = document()
    strong_but_unrelated.metadata["rerank_score"] = 0.92
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    result = evaluator.evaluate(
        "Một quy định pháp luật chưa có trong văn bản hiện tại là gì?",
        [strong_but_unrelated],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_relevance_gate_rejects_high_score_without_domain_overlap():
    unrelated = document()
    unrelated.content = "Quy định về vận tải đường sắt và cấp phép phương tiện." * 4
    unrelated.metadata["rerank_score"] = 0.95
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    result = evaluator.evaluate("Bitcoin và thị trường tài chính quốc tế", [unrelated], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_relevance_gate_rejects_documents_without_score_or_explicit_match():
    no_score = document()
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    result = evaluator.evaluate("pháp luật nghĩa vụ báo trước hợp đồng lao động", [no_score], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_relevance_gate_keeps_strong_semantic_match_when_cross_encoder_logit_is_negative():
    exact = document()
    exact.content = "Người lao động có trình độ cao đẳng được thử việc tối đa sáu mươi ngày."
    exact.metadata.update(
        {
            "Dieu": "Điều 25. Thời gian thử việc",
            "semantic_score": 0.9333,
            "heuristic_rerank_score": 0.28,
            "rerank_score": -0.4166,
            "cross_encoder_score": -0.4166,
        }
    )
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate(
        "Người lao động có trình độ cao đẳng được thử việc tối đa bao lâu?",
        [exact],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True


def test_relevance_gate_does_not_accept_cross_encoder_logit_as_a_normalized_score():
    unrelated = document()
    unrelated.content = "Quy định về vận tải đường sắt và cấp phép phương tiện." * 4
    unrelated.metadata.update(
        {
            "rerank_score": 2.8,
            "cross_encoder_score": 2.8,
            "semantic_score": 0.62,
        }
    )
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate(
        "Bitcoin và thị trường tài chính quốc tế",
        [unrelated],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_universal_corpus_bm25_magnitude_is_not_treated_as_a_relevance_score():
    unrelated = document()
    unrelated.content = "Quy định về vận tải đường sắt và cấp phép phương tiện." * 4
    unrelated.metadata.update({"corpus_source": "universal_legal", "score": 500.0})
    unrelated.score = 500.0
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate(
        "Bitcoin và thị trường tài chính quốc tế",
        [unrelated],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_universal_corpus_relevance_uses_text_when_no_normalized_model_score_exists():
    relevant = document()
    relevant.content = "Điều 25 quy định thời gian thử việc; người có trình độ cao đẳng được thử việc tối đa 60 ngày." * 2
    relevant.metadata.update({"corpus_source": "universal_legal", "topic": "Lao động"})
    relevant.score = None
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate(
        "Người lao động có trình độ cao đẳng được thử việc tối đa bao lâu?",
        [relevant],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True


def test_universal_bm25_candidate_is_not_rejected_for_query_paraphrase():
    deposit_provision = document()
    deposit_provision.content = (
        "Điều 328. Đặt cọc. Trường hợp bên nhận đặt cọc từ chối giao kết, thực hiện hợp đồng, "
        "thì phải trả cho bên đặt cọc tài sản đặt cọc và một khoản tiền tương đương. "
    ) * 2
    deposit_provision.metadata.update(
        {
            "corpus_source": "universal_legal",
            "bm25_rank": -69.9,
            "legal_anchor": "Điều 328",
        }
    )
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate(
        "Chủ nhà giữ tiền đặt cọc thuê nhà thì xử lý thế nào?",
        [deposit_provision],
        TaskType.LEGAL_LOOKUP,
    )

    assert result.sufficient is True


@pytest.mark.parametrize(
    ("query", "unrelated_content"),
    [
        (
            "Tôi muốn đăng ký hộ kinh doanh. Cần chuẩn bị hồ sơ gì?",
            "Người tiêu dùng được bảo vệ quyền lợi khi giao dịch với tổ chức, cá nhân kinh doanh. " * 3,
        ),
        (
            "Công ty cho tôi nghỉ việc ngay mà không báo trước. Tôi có quyền lợi gì?",
            "Người tiêu dùng được thông báo đầy đủ và yêu cầu bồi thường để bảo vệ quyền lợi. " * 3,
        ),
    ],
)
def test_universal_relevance_rejects_documents_matching_only_shared_legal_terms(
    query: str, unrelated_content: str
):
    unrelated = document()
    unrelated.content = unrelated_content
    unrelated.metadata["corpus_source"] = "universal_legal"
    checker = legal_relevance_checker(min_rerank_score=0.40)

    assert checker(query, [unrelated]) is False


@pytest.mark.parametrize(
    ("query", "answer_content", "neighbor_content"),
    [
        (
            "Tôi muốn đăng ký hộ kinh doanh. Cần chuẩn bị hồ sơ gì?",
            "Chủ hộ kinh doanh nộp hồ sơ đăng ký tại cơ quan có thẩm quyền. " * 3,
            "Người tiêu dùng được thông báo và bảo vệ quyền lợi khi giao dịch với tổ chức kinh doanh. " * 3,
        ),
        (
            "Chấm dứt hợp đồng lao động phải báo trước bao lâu?",
            "Người sử dụng lao động đơn phương chấm dứt hợp đồng phải báo trước theo quy định. " * 3,
            "Người tiêu dùng được thông báo đầy đủ và yêu cầu bồi thường để bảo vệ quyền lợi. " * 3,
        ),
    ],
)
def test_universal_retrieval_prefers_contextual_phrases_over_shared_legal_vocabulary(
    query: str, answer_content: str, neighbor_content: str
):
    relevant = document()
    relevant.content = answer_content
    relevant.metadata.update({"corpus_source": "universal_legal", "topic": "target"})
    neighbor = document()
    neighbor.content = neighbor_content
    neighbor.metadata.update({"corpus_source": "universal_legal", "topic": "neighbor"})

    selected = filter_universal_retrieval_neighbors(query, [neighbor, relevant])

    assert selected == [relevant]


def test_relevance_gate_rejects_old_instrument_for_generic_new_law_query():
    old_source = document()
    old_source.metadata.update(
        {
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
            "rerank_score": 0.98,
        }
    )
    evaluator = EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    )

    result = evaluator.evaluate("2026 có luật gì mới không?", [old_source], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_citation_verifier_rejects_missing_and_out_of_range_citations():
    docs = [document()]
    valid, _, reason = verify_citations("Theo Điều 36 [1], đây là kết luận có căn cứ.", docs, TaskType.LEGAL_LOOKUP)
    assert valid is True
    assert reason == "ok"
    invalid, _, invalid_reason = verify_citations("Kết luận [2].", docs, TaskType.LEGAL_LOOKUP)
    assert invalid is False
    assert invalid_reason == "citation_out_of_range"
    missing, _, missing_reason = verify_citations("Kết luận.", docs, TaskType.LEGAL_LOOKUP)
    assert missing is False
    assert missing_reason == "answer_has_no_citation"


def test_claim_segments_exclude_bibliography_and_disclaimer_lines():
    segments = legal_claim_segments(
        "Theo Điều 36 [1], người sử dụng lao động phải thực hiện nghĩa vụ báo trước.\n"
        "📚 Nguồn tham khảo:\n"
        "- Điều 36. Đối tượng, lộ trình thực hiện nghĩa vụ báo trước\n"
        "Kết quả này không thay thế tư vấn pháp lý."
    )

    assert segments == ["Theo Điều 36 [1], người sử dụng lao động phải thực hiện nghĩa vụ báo trước."]


def test_claim_segments_split_after_sentence_final_citation():
    answer = (
        "Theo Điều 10, shop không được từ chối đổi trả hàng giao sai mô tả [1]. "
        "Bạn có thể khiếu nại đến cơ quan bảo vệ người tiêu dùng hoặc khởi kiện [1]."
    )

    assert legal_claim_segments(answer) == [
        "Theo Điều 10, shop không được từ chối đổi trả hàng giao sai mô tả [1].",
        "Bạn có thể khiếu nại đến cơ quan bảo vệ người tiêu dùng hoặc khởi kiện [1].",
    ]


def test_claim_segments_keep_scope_caveats_that_also_include_user_advice():
    segments = legal_claim_segments(
        "Bạn có quyền yêu cầu đổi trả theo quy định này [1]. "
        "Tuy nhiên, quy định này chỉ áp dụng cho một nhóm giao dịch cụ thể, và bạn nên kiểm tra hợp đồng."
    )

    assert len(segments) == 2
    assert "bạn nên kiểm tra hợp đồng" in segments[1].casefold()
    assert "chỉ áp dụng cho một nhóm giao dịch cụ thể" in segments[1].casefold()


def test_claim_segments_include_unanchored_rights_claims_before_a_cited_explanation():
    answer = (
        "Bạn có quyền yêu cầu đổi hoặc hoàn tiền nếu hàng giao bị vỡ. "
        "Theo Điều 36 [1], phạm vi áp dụng phụ thuộc vào điều kiện được nêu trong nguồn."
    )

    assert legal_claim_segments(answer) == [
        "Bạn có quyền yêu cầu đổi hoặc hoàn tiền nếu hàng giao bị vỡ.",
        "Theo Điều 36 [1], phạm vi áp dụng phụ thuộc vào điều kiện được nêu trong nguồn.",
    ]
    valid, _, reason = verify_citations(answer, [document()], TaskType.LEGAL_LOOKUP)
    assert valid is False
    assert reason == "legal_claim_without_citation"


def test_claim_segments_include_every_numbered_legal_list_item():
    answer = (
        "Các quyền cơ bản gồm:\n"
        "1. Được bảo đảm an toàn về tính mạng, sức khỏe, danh dự, nhân phẩm, uy tín, tài sản [1]\n"
        "2. Được cung cấp thông tin chính xác, đầy đủ về sản phẩm, hàng hóa, dịch vụ [1]\n"
        "3. Lựa chọn sản phẩm, hàng hóa, dịch vụ [1]\n"
        "4. Góp ý kiến với tổ chức, cá nhân kinh doanh [1]"
    )

    assert legal_claim_segments(answer) == [
        "Các quyền cơ bản gồm: Được bảo đảm an toàn về tính mạng, sức khỏe, danh dự, nhân phẩm, uy tín, tài sản [1]",
        "Các quyền cơ bản gồm: Được cung cấp thông tin chính xác, đầy đủ về sản phẩm, hàng hóa, dịch vụ [1]",
        "Các quyền cơ bản gồm: Lựa chọn sản phẩm, hàng hóa, dịch vụ [1]",
        "Các quyền cơ bản gồm: Góp ý kiến với tổ chức, cá nhân kinh doanh [1]",
    ]


def test_claim_segments_carry_eligibility_context_into_list_items():
    segments = legal_claim_segments(
        "Cổ đông hoặc nhóm cổ đông sở hữu từ 5% tổng số cổ phần phổ thông trở lên có quyền:\n"
        "1. Yêu cầu triệu tập họp trong trường hợp luật quy định [1]\n"
        "2. Quyền khác theo quy định của Luật này và Điều lệ công ty [1]"
    )

    assert len(segments) == 2
    assert all("sở hữu từ 5% tổng số cổ phần phổ thông trở lên" in claim for claim in segments)


def test_citation_verifier_requires_citations_on_each_numbered_list_item():
    docs = [document()]
    answer = (
        "Các quyền gồm:\n"
        "1. Được cung cấp thông tin đầy đủ [1]\n"
        "2. Lựa chọn hàng hóa phù hợp"
    )

    valid, _, reason = verify_citations(answer, docs, TaskType.LEGAL_LOOKUP)

    assert valid is False
    assert reason == "legal_claim_without_citation"


def test_list_item_citation_propagation_fills_missing_citations_from_nearest_sibling():
    answer = (
        "Thời hạn phụ thuộc vào loại công việc:\n"
        "1. Không quá 180 ngày với người quản lý doanh nghiệp.\n"
        "2. Không quá 60 ngày với công việc cần trình độ cao đẳng trở lên.\n"
        "3. Không quá 30 ngày với công việc cần trình độ trung cấp.\n"
        "4. Không quá 06 ngày làm việc với công việc khác [2]."
    )

    repaired = propagate_list_item_citations(answer)

    assert repaired.count("[2]") == 4
    assert legal_claim_segments(repaired) == [
        "Thời hạn phụ thuộc vào loại công việc: Không quá 180 ngày với người quản lý doanh nghiệp. [2]",
        "Thời hạn phụ thuộc vào loại công việc: Không quá 60 ngày với công việc cần trình độ cao đẳng trở lên. [2]",
        "Thời hạn phụ thuộc vào loại công việc: Không quá 30 ngày với công việc cần trình độ trung cấp. [2]",
        "Thời hạn phụ thuộc vào loại công việc: Không quá 06 ngày làm việc với công việc khác [2].",
    ]


def test_claim_segments_ignore_corpus_clause_number_lines_without_claim_text():
    assert legal_claim_segments(
        "Theo Điều 25 [1]:\n1. [1]\nQuy định bắt buộc được nêu tại khoản này [1]."
    ) == ["Quy định bắt buộc được nêu tại khoản này [1]."]


def test_citation_verifier_requires_each_legal_claim_to_have_a_source():
    docs = [document()]
    valid, _, reason = verify_citations(
        "Theo quy định, doanh nghiệp phải thực hiện nghĩa vụ báo trước.\nNguồn tham khảo: [1]",
        docs,
        TaskType.LEGAL_LOOKUP,
    )
    assert valid is False
    assert reason == "legal_claim_without_citation"


def test_citation_verifier_rejects_article_not_present_in_cited_evidence():
    docs = [document()]
    valid, _, reason = verify_citations(
        "Theo Điều 81 [1], doanh nghiệp phải đóng góp tài chính.",
        docs,
        TaskType.LEGAL_LOOKUP,
    )
    assert valid is False
    assert reason == "article_reference_not_in_evidence"


def test_citation_verifier_accepts_supported_article_claim():
    docs = [document()]
    valid, _, reason = verify_citations(
        "Theo Điều 36 [1], doanh nghiệp phải đối chiếu nghĩa vụ báo trước.",
        docs,
        TaskType.LEGAL_LOOKUP,
    )
    assert valid is True
    assert reason == "ok"


def test_citation_verifier_accepts_mixed_corpus_and_official_web_evidence():
    web_document = DocumentRecord(
        content="Trang văn bản chính thức về nghĩa vụ khi chấm dứt hợp đồng lao động.",
        document_id="web:1:official-labor-source",
        source="web",
        metadata={
            "title": "Cổng văn bản chính thức",
            "official_url": "https://vbpl.vn/example",
            "authority": "official",
            "source_kind": "official_web",
        },
    )
    answer = "Theo Điều 36 [1] và nguồn chính thức [2], cần đối chiếu nghĩa vụ báo trước."

    valid, citations, reason = verify_citations(
        answer,
        [document(), web_document],
        TaskType.LEGAL_LOOKUP,
    )

    assert valid is True
    assert reason == "ok"
    assert len(citations) == 2
    web_valid, _, web_reason = verify_web_citations(answer, [document(), web_document])
    assert web_valid is True
    assert web_reason == "ok"


def test_mixed_source_citation_rejects_web_document_without_official_metadata():
    web_document = DocumentRecord(
        content="Trích đoạn chưa được xác thực nguồn.",
        document_id="web:1:untrusted",
        source="web",
        metadata={"title": "Nguồn thiếu URL"},
    )

    valid, _, reason = verify_citations(
        "Theo Điều 36 [1], cần đối chiếu nghĩa vụ.",
        [document(), web_document],
        TaskType.LEGAL_LOOKUP,
    )

    assert valid is False
    assert reason == "web_source_metadata_missing"


def test_required_article_anchor_does_not_match_a_body_mention_in_another_article():
    decoy = document()
    decoy.metadata.update({"Dieu": "Điều 139", "Parent_Dieu": "Điều 139", "legal_anchor": "Điều 139"})
    decoy.content += " Điều 36 được nhắc ở đây, nhưng đây vẫn là Điều 139."

    assert document_matches_anchor(decoy, LegalAnchor(article="Điều 36")) is False


def test_named_statute_anchor_rejects_same_article_from_another_law():
    wrong_law = document()
    wrong_law.metadata.update(
        {
            "Dieu": "Điều 41",
            "legal_anchor": "Điều 41",
            "Document_Number": "82/2015/QH13",
            "source_title": "Luật Tài nguyên, môi trường biển và hải đảo 2015",
            "source": "Luật Tài nguyên, môi trường biển và hải đảo 2015",
            "topic": "Môi trường",
        }
    )
    right_law = DocumentRecord(
        content="Điều 41 Bộ luật Lao động quy định nghĩa vụ khi đơn phương chấm dứt hợp đồng trái luật.",
        metadata={
            "Dieu": "Điều 41",
            "source_article": "Điều 41",
            "legal_anchor": "Điều 41",
            "Document_Number": "45/2019/QH14",
            "source_title": "(Điều 41 Bộ luật số 45/2019/QH14)",
            "law_ref": "(Điều 41 Bộ luật số 45/2019/QH14)",
            "topic": "Lao động",
            "source_kind": "legal_corpus",
        },
        document_id="labor-code-41",
        source="legal",
    )
    anchor = LegalAnchor(article="Điều 41", document_title="Bộ luật Lao động 2019")

    assert document_matches_anchor(wrong_law, anchor) is False
    assert document_matches_anchor(right_law, anchor) is True
