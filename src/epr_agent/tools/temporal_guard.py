"""Temporal Law Validity & Effective-Date Guardrails."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from epr_agent.domain.models import DocumentRecord

logger = logging.getLogger(__name__)


def is_current_law_support_unresolved(doc: DocumentRecord) -> bool:
    """Return whether corpus metadata leaves current-law support unverified.

    This is a provision-level coverage signal. It does not establish that the
    whole instrument has been superseded.
    """
    if doc.source != "legal":
        return False

    current_support = doc.current_law_support
    if current_support is None:
        meta = doc.metadata or {}
        current_support = meta.get("Current_Law_Support")
        if current_support is None:
            current_support = meta.get("current_law_support")

    if isinstance(current_support, bool):
        return not current_support
    return str(current_support or "").strip().casefold() in {"false", "0", "no", "pending", "unresolved"}


def is_document_superseded(doc: DocumentRecord, reference_date: date | None = None) -> bool:
    """Check explicit instrument status and effective dates for supersession.

    ``Current_Law_Support`` records whether the corpus can support a current
    provision. A false value is not proof that the instrument itself is
    superseded, expired, or repealed.
    """
    if doc.source != "legal":
        return False

    meta = doc.metadata or {}
    ref_date = reference_date or datetime.now(tz=UTC).date()

    status = (doc.effective_status or meta.get("Effective_Status") or meta.get("effective_status") or "").strip().lower()
    if status in {"superseded", "expired", "invalid", "het_hieu_luc", "bi_bai_bo", "het_hieu_luc_mot_phan"}:
        return True

    effective_to = (doc.effective_to or meta.get("Effective_To") or meta.get("effective_to") or "").strip()
    if effective_to:
        try:
            # Expected format YYYY-MM-DD
            exp_date = date.fromisoformat(effective_to[:10])
            if exp_date < ref_date:
                return True
        except ValueError:
            pass

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
    """Generate a warning that distinguishes unresolved coverage from supersession."""
    if not is_document_superseded(doc):
        if is_current_law_support_unresolved(doc):
            meta = doc.metadata or {}
            source_title = meta.get("source_title") or doc.document_id or "Văn bản"
            amendments = doc.amendment_relationship or meta.get("Amendment_Relationship") or []
            if isinstance(amendments, str):
                amendments = [amendments]
            if amendments:
                amendment_text = ", ".join(str(item) for item in amendments)
                return (
                    f"Dữ liệu chưa xác nhận nội dung hiện hành của điều khoản trong nguồn '{source_title}'; "
                    f"cần đối chiếu các văn bản liên quan [{amendment_text}]."
                )
            return f"Dữ liệu chưa xác nhận nội dung hiện hành của điều khoản trong nguồn '{source_title}'."

        meta = doc.metadata or {}
        amendments = doc.amendment_relationship or meta.get("Amendment_Relationship") or []
        if amendments:
            if isinstance(amendments, str):
                amendments = [amendments]
            source_title = doc.document_id or meta.get("source_title") or "văn bản"
            amendment_text = ", ".join(str(item) for item in amendments)
            return f"Văn bản '{source_title}' có quan hệ với các văn bản sửa đổi/bổ sung [{amendment_text}]."
        return None

    meta = doc.metadata or {}
    source_title = meta.get("source_title") or doc.document_id or "Văn bản"
    amendments = doc.amendment_relationship or meta.get("Amendment_Relationship") or []
    if isinstance(amendments, str):
        amendments = [amendments]

    if amendments:
        amendment_text = ", ".join(str(item) for item in amendments)
        return f"Văn bản '{source_title}' có thể đã bị sửa đổi/bãi bỏ hoặc thay thế bởi [{amendment_text}]."

    effective_to = doc.effective_to or meta.get("Effective_To")
    if effective_to:
        return f"Văn bản '{source_title}' đã hết hiệu lực từ ngày {effective_to}."

    return f"Văn bản '{source_title}' nằm trong diện cần đối chiếu bản hợp nhất mới nhất (trạng thái: {doc.effective_status or 'cần cập nhật'})."


def filter_and_rank_by_validity(
    docs: list[DocumentRecord],
    *,
    allow_superseded: bool = True,
) -> tuple[list[DocumentRecord], list[str]]:
    """Prefer verified provisions, then unresolved coverage, then stale instruments."""
    active_docs: list[DocumentRecord] = []
    unresolved_docs: list[DocumentRecord] = []
    superseded_docs: list[DocumentRecord] = []
    warnings: list[str] = []

    for doc in docs:
        if is_document_superseded(doc):
            superseded_docs.append(doc)
        elif is_current_law_support_unresolved(doc):
            unresolved_docs.append(doc)
        else:
            active_docs.append(doc)

        warning = get_temporal_warning(doc)
        if warning and warning not in warnings:
            warnings.append(warning)

    if not allow_superseded:
        # Keep unresolved material only when no provision with verified-current
        # support exists, so the evidence gate can return a precise status stop.
        if active_docs:
            return active_docs, warnings
        if unresolved_docs:
            return unresolved_docs, warnings

    return active_docs + unresolved_docs + superseded_docs, warnings
