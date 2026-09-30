"""Retrieval adapters that isolate corpus and provider objects from the graph."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from typing import Any, Protocol

from vietnam_legal_agent.domain.legal import LegalAnchor, explicit_anchors, parse_required_anchors
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.domain.v4 import RetrievalRequest
from vietnam_legal_agent.tools.evidence import (
    document_matches_anchor,
    filter_universal_retrieval_neighbors,
    legal_relevance_checker,
)

logger = logging.getLogger(__name__)


class RetrievalGateway(Protocol):
    async def legal(self, query: str | RetrievalRequest) -> list[DocumentRecord]: ...


class RequiredAnchorParseError(ValueError):
    """A required wire anchor could not be converted to a typed anchor."""

    def __init__(self, invalid_anchors: list[str]) -> None:
        self.invalid_anchors = tuple(invalid_anchors)
        super().__init__("required_anchor_parse_failed")


def retrieval_query(value: str | RetrievalRequest) -> str:
    """Keep the V3 retriever compatible while V4 sends typed requests."""

    return value if isinstance(value, str) else value.query


def _to_record(document: Any, *, source: str, index: int) -> DocumentRecord:
    metadata = dict(getattr(document, "metadata", {}) or {})
    raw_score = metadata.get("score", metadata.get("rerank_score"))
    try:
        score = float(raw_score) if raw_score is not None else None
    except (TypeError, ValueError):
        score = None
    document_id = str(
        metadata.get("source_document_id")
        or metadata.get("document_id")
        or metadata.get("_id")
        or metadata.get("chunk_id")
        or metadata.get("id")
        or f"{source}-{index + 1}"
    )
    return DocumentRecord(
        content=str(getattr(document, "page_content", "") or ""),
        metadata=metadata,
        document_id=document_id,
        score=score,
        source=source,
    )


class UniversalLegalRetrievalGateway:
    """Use the versioned multi-domain corpus as the standard legal source."""

    async def legal(self, query: str | RetrievalRequest) -> list[DocumentRecord]:
        from vietnam_legal_agent.config import get_settings
        from vietnam_legal_agent.retrieval.retrieval import retrieve_legal_async

        request = query if isinstance(query, RetrievalRequest) else None
        settings = get_settings()
        query_text = retrieval_query(query)
        typed_required_anchors: list[LegalAnchor] | None = None
        if request is not None and request.required_anchors:
            typed_required_anchors, invalid_anchors = parse_required_anchors(request.required_anchors)
            if invalid_anchors:
                # Keep the raw request on the V4 state/trace and make the
                # typed adapter reject the whole request. Dropping one
                # required anchor would make a partial answer look complete.
                raise RequiredAnchorParseError(invalid_anchors)

        query_anchors = typed_required_anchors or explicit_anchors(query_text)

        # The official delta is a deliberately narrow preview source. Check
        # it before Qdrant so an exact instrument cannot be shadowed by a
        # nearest-neighbour result.
        if bool(getattr(settings, "enable_official_delta_retrieval", False)):
            try:
                from vietnam_legal_agent.retrieval.official_delta import OfficialDeltaRetriever

                delta_retriever = OfficialDeltaRetriever(getattr(settings, "official_delta_manifest_path", None))
                delta_documents = delta_retriever.search(
                    query_text,
                    limit=request.top_k if request else 5,
                    required_anchors=query_anchors or None,
                )
                if delta_documents:
                    return delta_documents
                if delta_retriever.covers_instrument(
                    query_text,
                    required_anchors=query_anchors or None,
                ):
                    return []
            except (OSError, TypeError, ValueError) as exc:
                logger.warning("Official delta retrieval skipped: %s", exc)

        limit = request.top_k if request else 8
        # A Qdrant collection is only used when the operator explicitly opts
        # in to a general legal collection. The universal corpus is the normal
        # retrieval source.
        include_qdrant = bool(getattr(settings, "enable_qdrant_retrieval", False))
        documents = []
        if include_qdrant:
            try:
                documents = await retrieve_legal_async(
                    query_text,
                    required_anchors=request.required_anchors if request else None,
                    metadata_filters=request.metadata_filters if request else None,
                    top_k=limit,
                )
            except Exception as exc:  # noqa: BLE001 - independent sources can still succeed
                logger.debug("Primary legal retrieval unavailable (%s); checking the universal corpus", exc)

        records = [_to_record(document, source="legal", index=i) for i, document in enumerate(documents)]
        for record in records:
            record.metadata.setdefault("source", str(getattr(settings, "law_citation_label", "Vietnamese legal corpus")))
            record.metadata.setdefault("Corpus_Version", str(getattr(settings, "corpus_version", "vietnamese-law-v1")))
            record.metadata.setdefault("document_id", record.document_id)
            if request is not None:
                record.metadata.setdefault("v4_issue_id", request.issue_id)
                record.metadata.setdefault("v4_required_anchors", request.required_anchors)

        if query_anchors:
            records = [
                record
                for record in records
                if any(document_matches_anchor(record, anchor) for anchor in query_anchors)
            ]

        has_typed_anchors = bool(request and request.required_anchors)
        has_unscoped_article_anchor = any(
            anchor.article and not (anchor.document_number or anchor.document_title)
            for anchor in query_anchors
        )
        can_check_relevance = (
            bool(getattr(settings, "enable_relevance_gate", True))
            and (
                has_unscoped_article_anchor
                or (not has_typed_anchors and not explicit_anchors(query_text))
            )
        )
        if records and can_check_relevance:
            checker = legal_relevance_checker(
                min_rerank_score=getattr(settings, "min_legal_rerank_score", 0.40)
            )
            # Check candidates individually. An aggregate "any match" check
            # kept every cross-domain neighbor whenever just one result was
            # relevant, then let those unrelated records enter generation.
            records = [record for record in records if checker(query_text, [record])]

        universal_records: list[DocumentRecord] = []
        # Search the universal corpus for every legal request when enabled.
        # Use the selected multi-domain source for every legal topic.
        if bool(getattr(settings, "enable_universal_retrieval", False)):
            try:
                from vietnam_legal_agent.retrieval.universal_retriever import universal_retriever
                if universal_retriever.is_available:
                    u_docs = universal_retriever.search(
                        retrieval_query(query),
                        limit=limit,
                        required_anchors=query_anchors or None,
                    )
                    for i, u_doc in enumerate(u_docs):
                        u_meta = dict(u_doc.get("metadata", {}))
                        u_meta.setdefault(
                            "Corpus_ID",
                            getattr(universal_retriever, "corpus_id", "universal-vietnamese-legal"),
                        )
                        u_meta.setdefault(
                            "Corpus_Version",
                            getattr(universal_retriever, "corpus_version", "content-locked"),
                        )
                        if u_doc.get("bm25_rank") is not None:
                            u_meta["bm25_rank"] = u_doc["bm25_rank"]
                        universal_source = (
                            u_meta.get("corpus_source") == "universal_legal"
                            or u_meta.get("source_kind") == "legal_corpus"
                        )
                        record = DocumentRecord(
                            content=u_doc["page_content"],
                            metadata=u_meta,
                            document_id=u_doc.get("document_id", f"univ-{i+1}"),
                            score=None if universal_source else u_doc.get("score"),
                            # `DocumentRecord.source` is a source kind, not the
                            # display label stored in metadata['source'].
                            source="legal",
                        )
                        if not query_anchors or any(
                            document_matches_anchor(record, anchor) for anchor in query_anchors
                        ):
                            universal_records.append(record)
            except (sqlite3.Error, OSError, ImportError) as exc:
                logger.debug("Universal legal retrieval skipped: %s", exc)

        if universal_records and can_check_relevance:
            checker = legal_relevance_checker(
                min_rerank_score=getattr(settings, "min_legal_rerank_score", 0.40)
            )
            universal_records = [record for record in universal_records if checker(query_text, [record])]
            universal_records = filter_universal_retrieval_neighbors(query_text, universal_records)

        # Reciprocal-rank fusion compares order rather than incompatible
        # vector, reranker, and BM25 score scales.
        fused: dict[str, tuple[DocumentRecord, float, list[str]]] = {}
        for source_name, ranked_records in (("qdrant_supplement", records), ("universal_corpus", universal_records)):
            for rank, record in enumerate(ranked_records, start=1):
                digest = hashlib.sha256(record.content.strip().encode("utf-8")).hexdigest()
                key = str(record.metadata.get("source_document_id") or record.document_id or digest)
                current = fused.get(key)
                score = 1.0 / (60 + rank)
                if current is None:
                    fused[key] = (record, score, [source_name])
                else:
                    prior_record, prior_score, sources = current
                    if digest != hashlib.sha256(prior_record.content.strip().encode("utf-8")).hexdigest():
                        key = f"{key}:{digest}"
                        fused[key] = (record, score, [source_name])
                    else:
                        fused[key] = (prior_record, prior_score + score, [*sources, source_name])

        ranked = sorted(fused.values(), key=lambda item: item[1], reverse=True)[:limit]
        for record, score, sources in ranked:
            record.metadata["retrieval_fusion_score"] = score
            record.metadata["retrieval_sources"] = list(dict.fromkeys(sources))

        return [record for record, _score, _sources in ranked]


class StaticRetrievalGateway:
    """Simple injected retrieval gateway useful for local demos and tests."""

    def __init__(self, *, legal_documents: list[DocumentRecord] | None = None) -> None:
        self.legal_documents = legal_documents or []
        self.calls: list[tuple[str, str]] = []
        self.requests: list[RetrievalRequest] = []

    async def legal(self, query: str | RetrievalRequest) -> list[DocumentRecord]:
        if isinstance(query, RetrievalRequest):
            self.requests.append(query)
            if query.required_anchors:
                _, invalid_anchors = parse_required_anchors(query.required_anchors)
                if invalid_anchors:
                    raise RequiredAnchorParseError(invalid_anchors)
        self.calls.append(("legal", retrieval_query(query)))
        if isinstance(query, RetrievalRequest) and query.required_anchors:
            selected = [
                document
                for document in self.legal_documents
                if any(
                    anchor.casefold() in (
                        str(document.metadata.get("legal_anchor") or "")
                        + " " + str(document.metadata.get("Dieu") or "")
                        + " " + str(document.metadata.get("source_title") or "")
                        + " " + document.content
                    ).casefold()
                    for anchor in query.required_anchors
                )
            ]
            return list(selected)
        return list(self.legal_documents)
