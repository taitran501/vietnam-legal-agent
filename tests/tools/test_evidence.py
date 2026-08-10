from epr_agent.domain.models import DocumentRecord, TaskType
from epr_agent.tools.evidence import EvidenceEvaluator, verify_citations


def document():
    return DocumentRecord(
        content="Nội dung điều luật EPR đủ dài để kiểm tra evidence và citation. " * 4,
        metadata={"Dieu": "Điều 77"},
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


def test_citation_verifier_rejects_missing_and_out_of_range_citations():
    docs = [document()]
    valid, _, reason = verify_citations("Kết luận [1].", docs, TaskType.LEGAL_LOOKUP)
    assert valid is True
    assert reason == "ok"
    invalid, _, invalid_reason = verify_citations("Kết luận [2].", docs, TaskType.LEGAL_LOOKUP)
    assert invalid is False
    assert invalid_reason == "citation_out_of_range"
    missing, _, missing_reason = verify_citations("Kết luận.", docs, TaskType.LEGAL_LOOKUP)
    assert missing is False
    assert missing_reason == "answer_has_no_citation"


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
