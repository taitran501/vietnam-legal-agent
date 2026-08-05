"""Evidence and citation checks for safe answer termination."""

from __future__ import annotations

import re
from collections.abc import Callable

from epr_agent.domain.models import Citation, DocumentRecord, EvidenceAssessment, TaskType


class EvidenceEvaluator:
    def __init__(self, *, min_docs: int = 1, min_chars: int = 160, relevance_checker: Callable[[str, list[DocumentRecord]], bool] | None = None) -> None:
        self.min_docs = max(1, min_docs)
        self.min_chars = max(1, min_chars)
        self.relevance_checker = relevance_checker

    def evaluate(self, query: str, documents: list[DocumentRecord], task_type: str | TaskType) -> EvidenceAssessment:
        if len(documents) < self.min_docs:
            return EvidenceAssessment(False, "not_enough_docs", len(documents), 0, False)

        total_chars = sum(len((doc.content or "").strip()) for doc in documents[:3])
        if total_chars < self.min_chars:
            return EvidenceAssessment(False, "content_too_short", len(documents), total_chars, False)

        has_metadata = any(self._has_source_metadata(doc) for doc in documents[:3])
        if not has_metadata:
            return EvidenceAssessment(False, "missing_source_metadata", len(documents), total_chars, False)

        if self.relevance_checker is not None:
            try:
                relevant = bool(self.relevance_checker(query, documents[:3]))
            except Exception:  # noqa: BLE001 - a failed optional checker is a failed evidence check
                relevant = False
            if not relevant:
                return EvidenceAssessment(False, "relevance_check_failed", len(documents), total_chars, has_metadata, True)

        # For an assessment/checklist, evidence is still necessary but the
        # decision is made from explicit facts, never from a document score alone.
        return EvidenceAssessment(True, "ok", len(documents), total_chars, has_metadata, self.relevance_checker is not None)

    @staticmethod
    def _has_source_metadata(document: DocumentRecord) -> bool:
        metadata = document.metadata or {}
        if document.source in {"faq", "web"}:
            return bool(document.content.strip())
        return bool(
            metadata.get("Dieu")
            or metadata.get("Chuong")
            or metadata.get("Muc")
            or metadata.get("source")
            or metadata.get("document_id")
        )


_CITATION_RE = re.compile(r"\[(\d+)\]")


def build_citations(documents: list[DocumentRecord]) -> list[Citation]:
    citations: list[Citation] = []
    for index, document in enumerate(documents, start=1):
        metadata = document.metadata or {}
        labels = [
            str(metadata[key])
            for key in ("Dieu", "Chuong", "Muc", "Câu_hỏi", "title", "source")
            if metadata.get(key)
        ]
        label = " — ".join(labels) or document.document_id or f"Nguồn {index}"
        citations.append(Citation(index=index, document_id=document.document_id, label=label))
    return citations


def verify_citations(
    answer: str,
    documents: list[DocumentRecord],
    task_type: str | TaskType,
) -> tuple[bool, list[Citation], str]:
    """Verify that every numbered citation points to returned evidence."""

    task = TaskType(task_type)
    citations = build_citations(documents)
    indices = [int(value) for value in _CITATION_RE.findall(answer or "")]
    if not documents:
        return False, citations, "no_evidence"
    if not indices:
        return False, citations, "answer_has_no_citation"
    max_index = len(documents)
    if any(index < 1 or index > max_index for index in indices):
        return False, citations, "citation_out_of_range"
    if task in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST} and not any(
        citation.index in indices for citation in citations
    ):
        return False, citations, "case_answer_not_linked_to_evidence"
    return True, citations, "ok"
