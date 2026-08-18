"""Unit tests for Temporal Law Validity & Effective-Date Guardrails."""

from __future__ import annotations

from datetime import date

from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.temporal_guard import (
    filter_and_rank_by_validity,
    get_temporal_warning,
    is_document_superseded,
)


def test_is_document_superseded_by_flag() -> None:
    # Explicit False flag
    doc_false = DocumentRecord(
        content="Điều 1 Luật cũ",
        current_law_support=False,
    )
    assert is_document_superseded(doc_false) is True

    # Metadata flag
    doc_meta = DocumentRecord(
        content="Điều 2 Luật cũ",
        metadata={"Current_Law_Support": "false"},
    )
    assert is_document_superseded(doc_meta) is True

    # Active doc
    doc_active = DocumentRecord(
        content="Điều 3 Luật mới",
        current_law_support=True,
    )
    assert is_document_superseded(doc_active) is False


def test_is_document_superseded_by_status() -> None:
    doc_superseded = DocumentRecord(
        content="Điều 77 NĐ 08/2022",
        effective_status="superseded",
    )
    assert is_document_superseded(doc_superseded) is True

    doc_expired = DocumentRecord(
        content="Nghị định hết hiệu lực",
        metadata={"Effective_Status": "het_hieu_luc"},
    )
    assert is_document_superseded(doc_expired) is True


def test_is_document_superseded_by_date() -> None:
    ref_date = date(2026, 8, 18)

    # Expired in the past
    doc_past = DocumentRecord(
        content="Văn bản hết hạn 2024",
        effective_to="2024-12-31",
    )
    assert is_document_superseded(doc_past, reference_date=ref_date) is True

    # Still active until 2030
    doc_future = DocumentRecord(
        content="Văn bản còn hiệu lực",
        effective_to="2030-01-01",
    )
    assert is_document_superseded(doc_future, reference_date=ref_date) is False

    # Not yet effective (starts in 2027)
    doc_not_yet = DocumentRecord(
        content="Văn bản chưa có hiệu lực",
        effective_from="2027-01-01",
    )
    assert is_document_superseded(doc_not_yet, reference_date=ref_date) is True


def test_get_temporal_warning_amendments() -> None:
    doc = DocumentRecord(
        content="Nghị định 08/2022/NĐ-CP",
        document_id="nd-08-2022",
        effective_status="superseded",
        amendment_relationship=["nd-05-2025-nd-cp"],
    )
    warning = get_temporal_warning(doc)
    assert warning is not None
    assert "nd-05-2025-nd-cp" in warning


def test_filter_and_rank_by_validity() -> None:
    doc_active = DocumentRecord(content="Điều 1 active", document_id="active-1", current_law_support=True)
    doc_old = DocumentRecord(content="Điều 1 old", document_id="old-1", current_law_support=False)

    # Place active first
    ranked, warnings = filter_and_rank_by_validity([doc_old, doc_active])
    assert ranked[0].document_id == "active-1"
    assert ranked[1].document_id == "old-1"
    assert len(warnings) > 0


def test_evidence_evaluator_catches_superseded() -> None:
    evaluator = EvidenceEvaluator(min_docs=1, min_chars=10)
    doc_old = DocumentRecord(
        content="Nội dung điều luật đã bị bãi bỏ hoàn toàn.",
        document_id="old-doc",
        metadata={"legal_anchor": "Điều 1", "source": "Luật cũ", "Current_Law_Support": "false"},
    )
    assessment = evaluator.evaluate("Tìm hiểu luật", [doc_old], task_type="legal_lookup")
    assert assessment.sufficient is False
    assert assessment.has_superseded_sources is True
    assert assessment.reason == "superseded_or_unresolved_source"
