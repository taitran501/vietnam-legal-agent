"""Evidence and citation checks for safe answer termination."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from epr_agent.domain.legal import LegalAnchor
from epr_agent.domain.models import (
    Citation,
    CitationOccurrence,
    CitationSource,
    DocumentRecord,
    EvidenceAssessment,
    TaskType,
)
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

        if expected_anchors:
            for anchor in expected_anchors:
                if anchor.document_number and not any(
                    _document_matches_instrument(document, anchor.document_number)
                    for document in documents
                ):
                    return EvidenceAssessment(
                        False,
                        "source_relevance_mismatch",
                        len(documents),
                        total_chars,
                        has_metadata,
                    )
            if not all(
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
        if metadata.get("corpus_source") == "universal_legal" or metadata.get("source_kind") in {"legal_corpus", "official_web"}:
            has_source = bool(
                metadata.get("source")
                or metadata.get("source_title")
                or metadata.get("official_url")
                or metadata.get("source_uri")
                or metadata.get("law_ref")
                or metadata.get("topic")
            )
            return bool(document.document_id and document.content.strip() and has_anchor and has_source)

        if metadata.get("source_file"):
            has_provenance = bool(
                (metadata.get("Corpus_Version") or metadata.get("corpus_version"))
                and (metadata.get("Corpus_SHA256") or metadata.get("corpus_sha"))
                and (metadata.get("Embedding_Profile") or metadata.get("embedding_profile"))
            )
            return bool(document.document_id and document.content.strip() and has_anchor and has_provenance)

        has_source = bool(
            metadata.get("source")
            or metadata.get("source_title")
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


_RELEVANCE_SCORE_KEYS = (
    "rerank_score",
    "heuristic_rerank_score",
    "cross_encoder_score",
    "combined_score",
    "score",
)
_RELEVANCE_STOPWORDS = {
    "cho", "chưa", "các", "có", "của", "đang", "được", "gì", "hỏi", "hiện",
    "khi", "không", "là", "nào", "này", "những", "nói", "pháp", "quy", "quyền", "định", "cần",
    "quy định", "sao", "theo", "thế", "và", "văn", "về", "việc", "với", "xem",
    "luật", "điều", "khoản", "điểm", "mức", "bao", "nhiêu", "trong", "tại",
    "từ", "đến", "nay", "năm", "số", "tôi", "bạn", "xin", "hãy", "giúp",
}
_RELEVANCE_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ỹĐđ]{3,}", re.UNICODE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_DISCOVERY_RE = re.compile(
    r"\b(?:mới|ban\s*hành|có\s*hiệu\s*lực|hiệu\s*lực\s*năm)\b",
    re.IGNORECASE,
)
_INSTRUMENT_RE = re.compile(r"\b\d{1,5}/\d{4}/[A-ZĐ0-9][A-ZĐ0-9-]*\b", re.IGNORECASE)


def _as_explicit_match(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"true", "1", "yes", "y", "đúng"}


def _relevance_tokens(value: Any) -> set[str]:
    text = str(value or "").casefold()
    tokens = set(_RELEVANCE_TOKEN_RE.findall(text))
    return {token for token in tokens if token not in _RELEVANCE_STOPWORDS}


def _document_relevance_tokens(document: DocumentRecord) -> set[str]:
    metadata = document.metadata or {}
    values = [document.content]
    values.extend(
        str(metadata.get(key) or "")
        for key in (
            "source",
            "source_title",
            "Source_Title",
            "title",
            "topic",
            "subject",
            "law_ref",
            "legal_anchor",
            "document_title",
        )
    )
    return _relevance_tokens(" ".join(values))


def _document_scores(document: DocumentRecord) -> list[float]:
    metadata = document.metadata or {}
    scores: list[float] = []
    for key in _RELEVANCE_SCORE_KEYS:
        raw = metadata.get(key)
        if raw is None and key == "score":
            raw = document.score
        try:
            if raw is not None:
                scores.append(float(raw))
        except (TypeError, ValueError):
            continue
    return scores


def _year_discovery_query(query: str) -> set[str]:
    """Return years that must be represented by a source instrument."""

    text = str(query or "")
    years = set(_YEAR_RE.findall(text))
    if not years or not _YEAR_DISCOVERY_RE.search(text):
        return set()
    if _INSTRUMENT_RE.search(text) or _ARTICLE_RE.search(text):
        return set()
    return years


def _document_instrument_text(document: DocumentRecord) -> str:
    metadata = document.metadata or {}
    return " ".join(
        str(metadata.get(key) or "")
        for key in (
            "Document_Number",
            "Instrument_Number",
            "instrument_number",
            "number",
            "source_title",
            "Source_Title",
            "document_title",
            "title",
            "source",
            "law_ref",
        )
    )


def _year_discovery_source_matches(query: str, document: DocumentRecord) -> bool:
    requested_years = _year_discovery_query(query)
    if not requested_years:
        return True
    return any(year in _document_instrument_text(document) for year in requested_years)


def legal_relevance_checker(*, min_rerank_score: float) -> Callable[[str, list[DocumentRecord]], bool]:
    threshold = max(0.0, min(1.0, float(min_rerank_score)))

    negative_evidence_pattern = re.compile(
        r"(?:chưa\s+có|không\s+có|chưa\s+được\s+đề\s+cập).{0,80}(?:văn\s+bản|corpus|tài\s+liệu|quy\s+định)",
        re.IGNORECASE,
    )

    def _check(query: str, documents: list[DocumentRecord]) -> bool:
        if negative_evidence_pattern.search(query or ""):
            return False
        if _year_discovery_query(query) and not any(
            _year_discovery_source_matches(query, document) for document in documents
        ):
            return False
        if any(_as_explicit_match((document.metadata or {}).get("explicit_match")) for document in documents):
            return True
        query_tokens = _relevance_tokens(query)
        if not query_tokens:
            return False
        for document in documents:
            scores = _document_scores(document)
            if not scores or max(scores) < threshold:
                continue
            if query_tokens.intersection(_document_relevance_tokens(document)):
                return True
        return False

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
    metadata = document.metadata or {}
    article_text = "\n".join(
        str(metadata.get(key) or "")
        for key in ("legal_anchor", "Parent_Dieu", "Dieu", "Điều")
    )
    if anchor.article and anchor.article.casefold() not in article_text.casefold():
        return False
    if anchor.appendix:
        appendix_text = "\n".join(
            str(metadata.get(key) or "")
            for key in (
                "legal_anchor",
                "appendix",
                "Phụ lục",
                "Phu_luc",
                "Dieu",
                "Điều",
                "Parent_Dieu",
                "appendix_table_id",
                "appendix_table",
            )
        )
        if anchor.appendix.casefold() not in appendix_text.casefold():
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
    return not anchor.document_number or _document_matches_instrument(document, anchor.document_number)


def _document_matches_instrument(document: DocumentRecord, document_number: str) -> bool:
    metadata = document.metadata or {}
    source_text = "\n".join(
        str(metadata.get(key) or "")
        for key in ("Document_Number", "Instrument_Number", "instrument_number", "number")
    )
    return document_number.casefold() in source_text.casefold()


def legal_claim_segments(answer: str) -> list[str]:
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

    claim_segments = legal_claim_segments(answer)
    for segment in claim_segments:
        segment_indices = [int(value) for value in _CITATION_RE.findall(segment)]
        if not segment_indices:
            return False, citations, "legal_claim_without_citation"
        cited_documents = [documents[index - 1] for index in segment_indices if 1 <= index <= max_index]
        mentioned_articles = _article_ids(segment)
        if mentioned_articles:
            supported_articles = set().union(*(_document_article_ids(document) for document in cited_documents))
            if not mentioned_articles.issubset(supported_articles) and not (mentioned_articles & supported_articles):
                return False, citations, "article_reference_not_in_evidence"

    if task in {TaskType.CASE_ASSESSMENT, TaskType.BUILD_COMPLIANCE_CHECKLIST} and not any(
        citation.index in indices for citation in citations
    ):
        return False, citations, "case_answer_not_linked_to_evidence"
    return True, citations, "ok"


def verify_web_citations(answer: str, documents: list[DocumentRecord]) -> tuple[bool, list[Citation], str]:
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


# ══════════════════════════════════════════════════════════════════════════════
# DEER-FLOW STYLE CITATION SOURCES AGGREGATOR & FORMATTER
# ══════════════════════════════════════════════════════════════════════════════


def mask_citation_code(markdown: str) -> str:
    """Mask code regions so examples inside code blocks are not scraped as citations (Deer-Flow pattern)."""
    if not markdown:
        return ""
    # Mask fenced code blocks
    fenced_masked = re.sub(
        r"(^|\n)(`{3,}|~{3,})[^\n]*(?:\n[\s\S]*?\n\2[^\n]*(?=\n|$)|[\s\S]*$)",
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        markdown,
    )
    # Mask inline code
    return re.sub(r"(`+)[\s\S]*?\1", lambda m: " " * len(m.group(0)), fenced_masked)


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        hostname = urlparse(url).netloc
        return hostname.replace("www.", "")
    except Exception:  # noqa: BLE001 - malformed URL produces an empty domain
        return ""


def extract_citation_sources(
    answer: str,
    documents: list[DocumentRecord],
) -> list[CitationSource]:
    """Extract and aggregate verified legal & web citation sources for the Deer-Flow CitationSourcesPanel."""
    if not answer or not documents:
        return []

    searchable = mask_citation_code(answer)
    sources_map: dict[str, CitationSource] = {}

    for match in _CITATION_RE.finditer(searchable):
        idx = int(match.group(1))
        if idx < 1 or idx > len(documents):
            continue

        doc = documents[idx - 1]
        meta = doc.metadata or {}

        doc_id = doc.document_id or f"doc_{idx}"
        title = (
            meta.get("Dieu")
            or meta.get("legal_anchor")
            or meta.get("source_title")
            or meta.get("title")
            or meta.get("source")
            or f"Căn cứ pháp lý [{idx}]"
        )
        raw_url = meta.get("official_url") or meta.get("url") or meta.get("source_uri") or meta.get("source_file") or ""
        url = raw_url if str(raw_url).startswith("http") else ""
        domain = _extract_domain(url) or ("thuvienphapluat.vn" if "thuvienphapluat" in str(meta) else "vbpl.vn")
        excerpt = doc.content[:400].strip() if doc.content else ""
        anchor = meta.get("legal_anchor") or meta.get("Dieu") or meta.get("anchor") or ""
        authority = meta.get("authority") or ("official" if "vbpl.vn" in url or "chinhphu.vn" in url else "legal_corpus")
        status = doc.effective_status or meta.get("effective_status") or "active"

        occurrence = CitationOccurrence(index=idx, title=title)

        if doc_id in sources_map:
            sources_map[doc_id].count += 1
            sources_map[doc_id].occurrences.append(occurrence)
        else:
            sources_map[doc_id] = CitationSource(
                id=doc_id,
                title=title,
                url=url,
                domain=domain,
                count=1,
                occurrences=[occurrence],
                excerpt=excerpt,
                authority=authority,
                legal_anchor=anchor,
                effective_status=status,
            )

    return list(sources_map.values())


def format_citation_markdown_reference(source_or_sources: CitationSource | list[CitationSource]) -> str:
    """Format single or list of citation sources for 1-click clipboard copy / reference footer."""
    if isinstance(source_or_sources, list):
        if not source_or_sources:
            return ""
        lines = ["### 📚 Nguồn căn cứ pháp lý & Tài liệu tham chiếu\n"]
        for s in source_or_sources:
            first_idx = s.occurrences[0].index if s.occurrences else 1
            ref_link = f"[{s.title}]({s.url})" if s.url else f"**{s.title}**"
            domain_info = f" ({s.domain})" if s.domain else ""
            lines.append(f"- [{first_idx}] {ref_link}{domain_info}")
        return "\n".join(lines)

    if source_or_sources.url:
        return f"[{source_or_sources.title}]({source_or_sources.url})"
    return f"[{source_or_sources.title}]"


def auto_anchor_citations_in_answer(answer: str, documents: list[DocumentRecord]) -> str:
    """Enrich answer with Deer-Flow inline citation markers [1], [2] when LLM omitted them."""
    if not answer or not documents:
        return answer

    masked = mask_citation_code(answer)
    existing_indices = {int(m) for m in _CITATION_RE.findall(masked)}
    if existing_indices:
        return answer

    enriched = answer
    anchored_indices: set[int] = set()

    for idx, doc in enumerate(documents, start=1):
        meta = doc.metadata or {}
        dieu_val = str(meta.get("Dieu") or meta.get("article_title") or meta.get("legal_anchor") or "").strip()
        match_art = re.search(r"Điều\s+(\d+[a-zđ]?)", dieu_val, re.IGNORECASE)
        patterns_to_try = []
        if match_art:
            art_num = match_art.group(1)
            patterns_to_try.append(re.compile(rf"(Điều\s+{art_num}\b(?!\s*\[\d+\]))", re.IGNORECASE))

        doc_num = str(meta.get("Document_Number") or meta.get("instrument_number") or "").strip()
        if doc_num and len(doc_num) >= 5:
            patterns_to_try.append(re.compile(rf"({re.escape(doc_num)}\b(?!\s*\[\d+\]))", re.IGNORECASE))

        for pat in patterns_to_try:
            if pat.search(enriched):
                enriched = pat.sub(rf"\1 [{idx}]", enriched, count=1)
                anchored_indices.add(idx)
                break

    if not anchored_indices and documents:
        lines = enriched.split("\n")
        new_lines = []
        doc_idx = 1
        for line in lines:
            stripped = line.strip()
            if doc_idx <= len(documents) and (
                stripped.startswith(("-", "*", "•"))
                or bool(re.match(r"^\d+[\.\)]", stripped))
            ):
                new_lines.append(f"{line} [{doc_idx}]")
                anchored_indices.add(doc_idx)
                doc_idx += 1
            else:
                new_lines.append(line)
        enriched = "\n".join(new_lines)

    if not anchored_indices and documents:
        paragraphs = enriched.split("\n\n", 1)
        if len(paragraphs) == 2:
            enriched = f"{paragraphs[0]} [1]\n\n{paragraphs[1]}"
        else:
            enriched = f"{enriched} [1]"

    return enriched
