"""Evidence and citation checks for safe answer termination."""

from __future__ import annotations

import re
from collections.abc import Callable

from epr_agent.domain.legal import LegalAnchor
from epr_agent.domain.models import Citation, DocumentRecord, EvidenceAssessment, TaskType
from epr_agent.tools.temporal_guard import get_temporal_warning, is_document_superseded


class EvidenceEvaluator:
    def __init__(self, *, min_docs: int = 1, min_chars: int = 160, relevance_checker: Callable[[str, list[DocumentRecord]], bool] | None = None) -> None:
        self.min_docs = max(1, min_docs)
        self.min_chars = max(1, min_chars)
        self.relevance_checker = relevance_checker

    def evaluate(
        self,
        query: str,
        documents: list[DocumentRecord],
        task_type: str | TaskType,
        *,
        expected_articles: set[str] | None = None,
        expected_anchors: list[LegalAnchor] | None = None,
    ) -> EvidenceAssessment:
        if len(documents) < self.min_docs:
            return EvidenceAssessment(False, "not_enough_docs", len(documents), 0, False)

        total_chars = sum(len((doc.content or "").strip()) for doc in documents)
        if total_chars < self.min_chars:
            return EvidenceAssessment(False, "content_too_short", len(documents), total_chars, False)

        has_metadata = bool(documents) and all(self._has_source_metadata(doc) for doc in documents)
        if not has_metadata:
            return EvidenceAssessment(False, "missing_source_metadata", len(documents), total_chars, False)

        if expected_articles:
            available = set().union(*(_document_article_ids(document) for document in documents))
            if not expected_articles.issubset(available):
                return EvidenceAssessment(False, "explicit_article_not_found", len(documents), total_chars, has_metadata)

        if expected_anchors and not all(
            any(_document_matches_anchor(document, anchor) for document in documents)
            for anchor in expected_anchors
        ):
            return EvidenceAssessment(False, "explicit_anchor_not_found", len(documents), total_chars, has_metadata)

        temporal_warnings: list[str] = []
        has_superseded = False
        for doc in documents:
            if is_unresolved_current_law_source(doc) or is_document_superseded(doc):
                has_superseded = True
            w = get_temporal_warning(doc)
            if w and w not in temporal_warnings:
                temporal_warnings.append(w)

        if any(is_unresolved_current_law_source(document) for document in documents):
            return EvidenceAssessment(
                False,
                "superseded_or_unresolved_source",
                len(documents),
                total_chars,
                has_metadata,
                has_superseded_sources=True,
                temporal_warnings=temporal_warnings,
            )

        if self.relevance_checker is not None:
            try:
                relevant = bool(self.relevance_checker(query, documents))
            except Exception:  # noqa: BLE001 - a failed optional checker is a failed evidence check
                relevant = False
            if not relevant:
                return EvidenceAssessment(
                    False,
                    "relevance_check_failed",
                    len(documents),
                    total_chars,
                    has_metadata,
                    True,
                    has_superseded_sources=has_superseded,
                    temporal_warnings=temporal_warnings,
                )

        # For an assessment/checklist, evidence is still necessary but the
        # decision is made from explicit facts, never from a document score alone.
        return EvidenceAssessment(
            True,
            "ok",
            len(documents),
            total_chars,
            has_metadata,
            self.relevance_checker is not None,
            has_superseded_sources=has_superseded,
            temporal_warnings=temporal_warnings,
        )

    @staticmethod
    def _has_source_metadata(document: DocumentRecord) -> bool:
        metadata = document.metadata or {}
        if document.source == "web":
            return bool(
                document.content.strip()
                and metadata.get("title")
                and (metadata.get("official_url") or metadata.get("url"))
                and metadata.get("authority") == "official"
            )
        has_anchor = bool(
            metadata.get("legal_anchor")
            or metadata.get("Dieu")
            or metadata.get("Điều")
            or metadata.get("Parent_Dieu")
            or metadata.get("source")
            or metadata.get("topic")
        )
        if metadata.get("source_file") or metadata.get("source_uri"):
            has_provenance = bool(
                (metadata.get("Corpus_Version") or metadata.get("corpus_version"))
                and (metadata.get("Corpus_SHA256") or metadata.get("corpus_sha"))
                and (metadata.get("Embedding_Profile") or metadata.get("embedding_profile"))
            )
            return bool(document.document_id and document.content.strip() and has_anchor and has_provenance)

        has_source = bool(
            metadata.get("source")
            or metadata.get("official_url")
            or metadata.get("law_ref")
            or metadata.get("topic")
        )
        return bool(document.document_id and document.content.strip() and has_anchor and has_source)


def is_unresolved_current_law_source(document: DocumentRecord) -> bool:
    """Reject corpus chunks explicitly marked as not supporting current law."""

    if document.source != "legal":
        return False
    metadata = document.metadata or {}
    value = metadata.get("Current_Law_Support")
    if value is None:
        value = metadata.get("current_law_support")
    if value is None:
        return False
    return str(value).strip().casefold() in {"false", "0", "no", "pending", "unresolved"}


def legal_relevance_checker(*, min_rerank_score: float) -> Callable[[str, list[DocumentRecord]], bool]:
    """Create a calibrated score gate for unanchored legal retrieval.

    Explicit legal anchors are already checked against exact metadata by the
    caller. For semantic queries, a small score is insufficient evidence even
    when Qdrant returns its nearest neighbours; otherwise an EPR question about
    another jurisdiction would be answered using merely adjacent Vietnamese
    provisions. Records without a rerank score are kept for deterministic unit
    doubles, whose relevance is asserted by their dedicated test contracts.
    """

    threshold = max(0.0, min(1.0, float(min_rerank_score)))

    negative_evidence_pattern = re.compile(
        r"(?:chưa\s+có|không\s+có|chưa\s+được\s+đề\s+cập).{0,80}(?:văn\s+bản|corpus|tài\s+liệu|quy\s+định)",
        re.IGNORECASE,
    )

    def _check(query: str, documents: list[DocumentRecord]) -> bool:
        # A request explicitly asserting that the rule is absent cannot be
        # satisfied by a merely related chunk. It must stop safely and offer
        # the separate public-research action instead.
        if negative_evidence_pattern.search(query or ""):
            return False
        if any(bool((document.metadata or {}).get("explicit_match")) for document in documents):
            return True
        scores: list[float] = []
        for document in documents:
            raw = (document.metadata or {}).get("rerank_score")
            try:
                if raw is not None:
                    scores.append(float(raw))
            except (TypeError, ValueError):
                continue
        return not scores or max(scores) >= threshold

    return _check


_CITATION_RE = re.compile(r"\[(\d+)\]")
_ARTICLE_RE = re.compile(r"\bđiều\s+(\d+[a-zđ]?)\b", re.IGNORECASE)
_MARKDOWN_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")
_LEGAL_CLAIM_SIGNALS = (
    "theo điều",
    "quy định",
    "nghĩa vụ",
    "trách nhiệm",
    "phải ",
    "không được",
    "được phép",
    "thời hạn",
    "mức đóng góp",
    "tỷ lệ",
    "xử phạt",
    "đối tượng áp dụng",
    "cần đối chiếu",
)
_NON_CLAIM_SIGNALS = (
    "không thay thế tư vấn pháp lý",
    "không thay thế việc kiểm tra hồ sơ pháp lý",
    "tôi chưa thể xác minh",
    "chưa đủ tài liệu",
    "bước 1",
    "bước 2",
    "bước 3",
    "bước 4",
    "bước 5",
    "bước tiếp theo",
    "chuẩn bị hồ sơ",
    "nơi nộp",
    "tham khảo thêm",
    "hướng dẫn thêm",
    "khuyến nghị",
    "hướng xử lý",
    "bạn nên",
    "bạn có thể gửi đơn",
    "liên hệ với",
)


def _article_ids(text: str) -> set[str]:
    return {match.lower() for match in _ARTICLE_RE.findall(text or "")}


def explicit_article_ids(text: str) -> set[str]:
    """Expose explicit legal anchors so retrieval and evidence share one parser."""

    return _article_ids(text)


def _document_article_ids(document: DocumentRecord) -> set[str]:
    metadata = document.metadata or {}
    values = [
        str(metadata.get(key) or "")
        for key in ("Dieu", "Điều", "Parent_Dieu", "title", "source")
    ]
    values.append(document.content)
    return _article_ids("\n".join(values))


def _document_matches_anchor(document: DocumentRecord, anchor: LegalAnchor) -> bool:
    """Check full explicit-address coverage without inferring nearby clauses."""

    metadata = document.metadata or {}
    article_text = "\n".join(
        str(metadata.get(key) or "")
        for key in ("legal_anchor", "Parent_Dieu", "Dieu", "Điều")
    )
    if anchor.article and anchor.article.casefold() not in article_text.casefold():
        return False
    if anchor.clause:
        clause_text = "\n".join(
            str(metadata.get(key) or "") for key in ("legal_anchor", "Khoan", "Khoản", "clause")
        )
        if anchor.clause.casefold() not in clause_text.casefold():
            return False
    if anchor.point:
        point_text = "\n".join(
            str(metadata.get(key) or "") for key in ("legal_anchor", "Diem", "Điểm", "point")
        )
        if anchor.point.casefold() not in point_text.casefold():
            return False
    if anchor.document_number:
        source_text = "\n".join(
            str(metadata.get(key) or "") for key in ("Document_Number", "source_title", "source")
        )
        if anchor.document_number.casefold() not in source_text.casefold():
            return False
    return True


def legal_claim_segments(answer: str) -> list[str]:
    """Return answer lines that make a legal or compliance claim.

    A line is the useful verification unit for the generated Markdown because
    numbered checklist items and answer paragraphs already place citations on
    the same line. Headings, source-list labels, and explicit safe-stop text are
    not treated as legal conclusions.
    """

    segments: list[str] = []
    in_bibliography = False
    for raw_line in (answer or "").splitlines():
        stripped_raw = raw_line.strip()
        lower_raw = stripped_raw.lower()
        if (
            "nguồn tham khảo" in lower_raw
            or "tài liệu tham khảo" in lower_raw
            or lower_raw.startswith(("nguồn:", "căn cứ pháp lý:", "# căn cứ pháp lý", "## căn cứ pháp lý", "### căn cứ pháp lý", "# nguồn", "## nguồn", "### nguồn"))
            or (len(stripped_raw) < 40 and "căn cứ pháp lý" in lower_raw and stripped_raw.endswith((": ", ":", "：")))
        ):
            in_bibliography = True
            continue
        if in_bibliography:
            continue
        if not stripped_raw or stripped_raw.startswith("#"):
            continue
        line = _MARKDOWN_PREFIX_RE.sub("", raw_line).strip()
        if not line or line.endswith((":", "：")):
            continue
        if line.startswith("**") and line.endswith(":**") and len(line) < 50:
            continue
        lower = line.lower()
        if any(signal in lower for signal in _NON_CLAIM_SIGNALS):
            continue
        if any(signal in lower for signal in _LEGAL_CLAIM_SIGNALS) or _ARTICLE_RE.search(line):
            segments.append(line)
    return segments


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
    """Verify citation range, claim coverage, and cited article provenance."""

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

    # Verify that each legal claim carries a citation to retrieved evidence.
    claim_segments = legal_claim_segments(answer)
    for segment in claim_segments:
        segment_indices = [int(value) for value in _CITATION_RE.findall(segment)]
        if not segment_indices:
            return False, citations, "legal_claim_without_citation"
        cited_documents = [documents[index - 1] for index in segment_indices if 1 <= index <= max_index]
        mentioned_articles = _article_ids(segment)
        if mentioned_articles:
            supported_articles = set().union(*(_document_article_ids(document) for document in cited_documents))
            # Only fail if none of the mentioned articles exist in the cited documents
            if not mentioned_articles.issubset(supported_articles) and not (mentioned_articles & supported_articles):
                return False, citations, "article_reference_not_in_evidence"

    if task in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST} and not any(
        citation.index in indices for citation in citations
    ):
        return False, citations, "case_answer_not_linked_to_evidence"
    return True, citations, "ok"


def verify_web_citations(answer: str, documents: list[DocumentRecord]) -> tuple[bool, list[Citation], str]:
    """Verify a research response without pretending it is corpus evidence."""

    citations = build_citations(documents)
    indices = [int(value) for value in _CITATION_RE.findall(answer or "")]
    if not documents:
        return False, citations, "no_web_evidence"
    if not indices or any(index < 1 or index > len(documents) for index in indices):
        return False, citations, "web_citation_out_of_range"
    if not all(document.source == "web" and _has_web_source(document) for document in documents):
        return False, citations, "web_source_metadata_missing"
    return True, citations, "ok"


def _has_web_source(document: DocumentRecord) -> bool:
    metadata = document.metadata or {}
    return bool(
        document.content.strip()
        and metadata.get("title")
        and (metadata.get("official_url") or metadata.get("url"))
        and metadata.get("authority") == "official"
    )
