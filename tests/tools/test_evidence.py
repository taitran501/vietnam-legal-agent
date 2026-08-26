from epr_agent.domain.legal import LegalAnchor
from epr_agent.domain.models import DocumentRecord, TaskType
from epr_agent.tools.evidence import (
    EvidenceEvaluator,
    legal_claim_segments,
    legal_relevance_checker,
    verify_citations,
)


def document():
    return DocumentRecord(
        content="Nội dung điều luật EPR đủ dài để kiểm tra evidence và citation. " * 4,
        metadata={
            "Dieu": "Điều 77",
            "legal_anchor": "Điều 77",
            "source": "Nghị định 08/2022",
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "test-v3",
            "Corpus_SHA256": "test-corpus-sha",
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
        },
        document_id="law-77",
        source="legal",
    )


def test_evidence_evaluator_requires_document_and_source_metadata():
    evaluator = EvidenceEvaluator(min_chars=20)
    result = evaluator.evaluate("EPR", [document()], TaskType.LEGAL_LOOKUP)
    assert result.sufficient is True
    assert result.reason == "ok"

    short = DocumentRecord("x", {}, "bad", source="legal")
    assert evaluator.evaluate("EPR", [short], TaskType.LEGAL_LOOKUP).sufficient is False


def test_evidence_evaluator_rejects_explicitly_unresolved_current_law_source():
    evaluator = EvidenceEvaluator(min_chars=20)
    unresolved = document()
    unresolved.metadata["Current_Law_Support"] = False

    result = evaluator.evaluate("Điều 77 hiện hành", [unresolved], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "superseded_or_unresolved_source"


def test_evidence_evaluator_preserves_legacy_documents_without_amendment_metadata():
    evaluator = EvidenceEvaluator(min_chars=20)
    assert evaluator.evaluate("Điều 77", [document()], TaskType.LEGAL_LOOKUP).sufficient is True


def test_evidence_evaluator_requires_the_requested_clause_and_point():
    evaluator = EvidenceEvaluator(min_chars=20)
    detailed = document()
    detailed.metadata.update(
        {
            "Document_Number": "08/2022/NĐ-CP",
            "Khoan": "Khoản 2",
            "Diem": "Điểm a",
            "legal_anchor": "08/2022/NĐ-CP | Điều 77 | Khoản 2 | Điểm a",
        }
    )

    exact = LegalAnchor(
        document_number="08/2022/NĐ-CP",
        article="Điều 77",
        clause="Khoản 2",
        point="Điểm a",
    )
    assert evaluator.evaluate("Điều 77", [detailed], TaskType.LEGAL_LOOKUP, expected_anchors=[exact]).sufficient is True

    wrong_point = exact.model_copy(update={"point": "Điểm b"})
    assert evaluator.evaluate("Điều 77", [detailed], TaskType.LEGAL_LOOKUP, expected_anchors=[wrong_point]).reason == "explicit_anchor_not_found"


def test_evidence_evaluator_rejects_a_nearby_article_from_the_wrong_instrument():
    wrong_instrument = document()
    wrong_instrument.metadata.update(
        {
            "Document_Number": "08/2022/NĐ-CP",
            "legal_anchor": "08/2022/NĐ-CP | Điều 77",
        }
    )
    requested = LegalAnchor(document_number="08/2026/QH16", article="Điều 77")

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Luật số 08/2026/QH16 Điều 77 quy định gì?",
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
            "legal_anchor": "08/2026/QH16 | Điều 77",
        }
    )
    requested = LegalAnchor(document_number="08/2026/QH16", article="Điều 77")

    result = EvidenceEvaluator(min_chars=20).evaluate(
        "Luật số 08/2026/QH16 Điều 77 quy định gì?",
        [exact],
        TaskType.LEGAL_LOOKUP,
        expected_anchors=[requested],
    )

    assert result.sufficient is True


def test_relevance_gate_rejects_nearest_but_weak_unanchored_documents():
    weak = document()
    weak.metadata["rerank_score"] = 0.31
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    result = evaluator.evaluate("Luật EPR của châu Âu nói gì?", [weak], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_relevance_gate_keeps_explicit_legal_anchor_even_when_its_score_is_low():
    exact = document()
    exact.metadata.update({"rerank_score": 0.31, "explicit_match": True})
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    assert evaluator.evaluate("Điều 77 quy định gì?", [exact], TaskType.LEGAL_LOOKUP).sufficient is True


def test_relevance_gate_stops_when_user_explicitly_requests_an_absent_rule():
    strong_but_unrelated = document()
    strong_but_unrelated.metadata["rerank_score"] = 0.92
    evaluator = EvidenceEvaluator(min_chars=20, relevance_checker=legal_relevance_checker(min_rerank_score=0.40))

    result = evaluator.evaluate(
        "Một quy định EPR chưa có trong văn bản hiện tại là gì?",
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

    result = evaluator.evaluate("EPR trách nhiệm tái chế bao bì", [no_score], TaskType.LEGAL_LOOKUP)

    assert result.sufficient is False
    assert result.reason == "relevance_check_failed"


def test_citation_verifier_rejects_missing_and_out_of_range_citations():
    docs = [document()]
    valid, _, reason = verify_citations("Theo Điều 77 [1], đây là kết luận có căn cứ.", docs, TaskType.LEGAL_LOOKUP)
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
        "Theo Điều 77 [1], nhà sản xuất phải thực hiện trách nhiệm tái chế.\n"
        "📚 Nguồn tham khảo:\n"
        "- Điều 77. Đối tượng, lộ trình thực hiện trách nhiệm tái chế\n"
        "Kết quả này không thay thế tư vấn pháp lý."
    )

    assert segments == ["Theo Điều 77 [1], nhà sản xuất phải thực hiện trách nhiệm tái chế."]


def test_citation_verifier_requires_each_legal_claim_to_have_a_source():
    docs = [document()]
    valid, _, reason = verify_citations(
        "Theo quy định, doanh nghiệp phải thực hiện nghĩa vụ tái chế.\nNguồn tham khảo: [1]",
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
        "Theo Điều 77 [1], doanh nghiệp phải đối chiếu trách nhiệm tái chế.",
        docs,
        TaskType.LEGAL_LOOKUP,
    )
    assert valid is True
    assert reason == "ok"
