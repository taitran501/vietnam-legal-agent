"""Temporal Law Validity & Effective-Date Guardrails."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from epr_agent.domain.models import DocumentRecord

logger = logging.getLogger(__name__)


def is_document_superseded(doc: DocumentRecord, reference_date: date | None = None) -> bool:
    """Check whether a document record is legally superseded, expired, or non-current."""
    if doc.source != "legal":
        return False

    meta = doc.metadata or {}
    ref_date = reference_date or datetime.now(tz=UTC).date()

    # 1. Explicit Current_Law_Support flag (from corpus indexing / Qdrant payload)
    current_support = doc.current_law_support
    if current_support is None:
        raw_val = meta.get("Current_Law_Support") or meta.get("current_law_support")
        if raw_val is not None:
            current_support = str(raw_val).strip().casefold() not in {"false", "0", "no", "pending", "unresolved"}

    if current_support is False:
        return True

    # 2. Effective Status string check
    status = (doc.effective_status or meta.get("Effective_Status") or meta.get("effective_status") or "").strip().lower()
    if status in {"superseded", "expired", "invalid", "het_hieu_luc", "bi_bai_bo", "het_hieu_luc_mot_phan"}:
        return True

    # 3. Date comparison on effective_to (Hết hiệu lực)
    effective_to = (doc.effective_to or meta.get("Effective_To") or meta.get("effective_to") or "").strip()
    if effective_to:
        try:
            # Expected format YYYY-MM-DD
            exp_date = date.fromisoformat(effective_to[:10])
            if exp_date < ref_date:
                return True
        except ValueError:
            pass

    # 4. Date comparison on effective_from (Chưa có hiệu lực)
    effective_from = (doc.effective_from or meta.get("Effective_From") or meta.get("effective_from") or "").strip()
    if effective_from:
        try:
            eff_date = date.fromisoformat(effective_from[:10])
            if eff_date > ref_date:
                return True
        except ValueError:
            pass

    return False


def get_temporal_warning(doc: DocumentRecord) -> str | None:
    """Generate a precise Vietnamese warning if the document is superseded or amended."""
    if not is_document_superseded(doc):
        # Check if active but has amendment relationship
        amends = doc.amendment_relationship or (doc.metadata or {}).get("Amendment_Relationship") or []
        if amends:
            doc_id = doc.document_id or doc.metadata.get("source_title", "văn bản")
            amend_str = ", ".join(str(a) for a in amends)
            return f"Văn bản '{doc_id}' có quan hệ sửa đổi/bổ sung liên quan đến [{amend_str}]."
        return None

    meta = doc.metadata or {}
    source_title = doc.metadata.get("source_title") or doc.document_id or "Văn bản"
    amends = doc.amendment_relationship or meta.get("Amendment_Relationship") or []

    if amends:
        amend_str = ", ".join(str(a) for a in amends)
        return f"Văn bản '{source_title}' có thể đã bị sửa đổi/bãi bỏ hoặc thay thế bởi [{amend_str}]."

    effective_to = doc.effective_to or meta.get("Effective_To")
    if effective_to:
        return f"Văn bản '{source_title}' đã hết hiệu lực từ ngày {effective_to}."

    return f"Văn bản '{source_title}' nằm trong diện cần đối chiếu bản hợp nhất mới nhất (trạng thái: {doc.effective_status or 'cần cập nhật'})."


def filter_and_rank_by_validity(
    docs: list[DocumentRecord],
    *,
    allow_superseded: bool = True,
) -> tuple[list[DocumentRecord], list[str]]:
    """Rank active current legal documents before superseded ones and collect temporal warnings."""
    active_docs: list[DocumentRecord] = []
    superseded_docs: list[DocumentRecord] = []
    warnings: list[str] = []

    for doc in docs:
        if is_document_superseded(doc):
            warning = get_temporal_warning(doc)
            if warning and warning not in warnings:
                warnings.append(warning)
            superseded_docs.append(doc)
        else:
            # Also check if it has amendments
            warning = get_temporal_warning(doc)
            if warning and warning not in warnings:
                warnings.append(warning)
            active_docs.append(doc)

    if not allow_superseded and active_docs:
        return active_docs, warnings

    # Place active docs first, superseded at the tail
    return active_docs + superseded_docs, warnings
