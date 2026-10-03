"""Retrieval adapters that isolate corpus and provider objects from the graph."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from functools import lru_cache
from typing import Any, Protocol

from vietnam_legal_agent.domain.legal import LegalAnchor, explicit_anchors, parse_required_anchors
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.domain.v4 import RetrievalRequest
from vietnam_legal_agent.tools.evidence import (
    document_matches_anchor,
    legal_relevance_checker,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_universal_cross_encoder(model_name: str) -> Any:
    """Return one lazy cross-encoder instance shared by universal retrieval."""

    from vietnam_legal_agent.retrieval.ensemble_retrieval import CrossEncoderReranker

    return CrossEncoderReranker(model_name)


def _heuristic_rerank_universal_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Use the local relevance scorer when the optional model cannot rank."""

    if not candidates:
        return []
    try:
        from langchain_core.documents import Document

        from vietnam_legal_agent.retrieval.ensemble_retrieval import HeuristicReranker

        documents = []
        for candidate_index, candidate in enumerate(candidates):
            metadata = dict(candidate.get("metadata") or {})
            metadata["Dieu"] = metadata.get("Dieu") or metadata.get("legal_anchor") or ""
            metadata["_universal_candidate_index"] = candidate_index
            documents.append(
                Document(
                    page_content=str(candidate.get("page_content") or ""),
                    metadata=metadata,
                )
            )

        ranked_documents = HeuristicReranker().rerank(query, documents, len(documents))
        ranked_candidates: list[dict[str, Any]] = []
        for document in ranked_documents:
            ranked_candidate_index = document.metadata.get("_universal_candidate_index")
            if not isinstance(ranked_candidate_index, int) or not 0 <= ranked_candidate_index < len(candidates):
                continue
            candidate = dict(candidates[ranked_candidate_index])
            candidate_metadata = dict(candidate.get("metadata") or {})
            candidate_metadata["rerank_score"] = document.metadata.get("rerank_score")
            candidate_metadata["heuristic_rerank_score"] = document.metadata.get(
                "heuristic_rerank_score"
            )
            candidate_metadata["rerank_fallback"] = "heuristic"
            candidate["metadata"] = candidate_metadata
            candidate["score"] = document.metadata.get("rerank_score")
            ranked_candidates.append(candidate)
        return ranked_candidates[:top_k] or candidates[:top_k]
    except Exception:
        logger.debug("Universal legal heuristic fallback failed", exc_info=True)
        return candidates[:top_k]


def _universal_rerank_mode(settings: Any, query: str) -> tuple[bool, bool]:
    """Return whether to score candidates and whether scores may change user order."""

    if not bool(getattr(settings, "enable_cross_encoder_rerank", False)):
        return False, False
    if bool(getattr(settings, "cross_encoder_shadow_mode", False)):
        return True, False

    rollout = max(0, min(100, int(getattr(settings, "cross_encoder_rollout_percent", 0))))
    if rollout <= 0:
        return False, False
    if rollout >= 100:
        return True, True

    bucket = int(hashlib.sha256(query.casefold().strip().encode("utf-8")).hexdigest()[:8], 16) % 100
    apply_ranking = bucket < rollout
    return apply_ranking, apply_ranking


async def _rerank_universal_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    model_name: str,
    top_k: int,
    timeout_ms: int,
    apply_ranking: bool = True,
) -> list[dict[str, Any]]:
    """Score candidates and apply ranking only when the configured rollout allows it."""

    if not candidates:
        return []

    try:
        from langchain_core.documents import Document

        reranker = _get_universal_cross_encoder(model_name)
        if getattr(reranker, "unavailable_reason", None):
            return (
                _heuristic_rerank_universal_candidates(query, candidates, top_k)
                if apply_ranking
                else candidates[:top_k]
            )
        rerank_documents = []
        for index, candidate in enumerate(candidates):
            metadata = dict(candidate.get("metadata") or {})
            metadata["Dieu"] = metadata.get("Dieu") or metadata.get("legal_anchor") or ""
            metadata["_universal_candidate_index"] = index
            rerank_documents.append(
                Document(
                    page_content=str(candidate.get("page_content") or ""),
                    metadata=metadata,
                )
            )

        ranked_documents = await asyncio.wait_for(
            asyncio.to_thread(reranker.rerank, query, rerank_documents, len(rerank_documents)),
            timeout=max(0.01, timeout_ms / 1000),
        )
        cross_ranks: dict[int, int] = {}
        cross_scores: dict[int, float] = {}
        for rank, document in enumerate(ranked_documents, start=1):
            index = document.metadata.get("_universal_candidate_index")
            if not isinstance(index, int) or not 0 <= index < len(candidates):
                continue
            cross_ranks[index] = rank
            try:
                cross_scores[index] = float(document.metadata.get("cross_encoder_score"))
            except (TypeError, ValueError):
                pass

        # A shadow run may collect scores, but it must never alter the results
        # shown to users. In an active rollout, reciprocal-rank fusion keeps
        # BM25 recall while allowing the cross-encoder to refine ordering.
        ranked_indices = (
            sorted(cross_ranks)
            if not apply_ranking
            else sorted(
                cross_ranks,
                key=lambda index: (
                    1 / (60 + index + 1) + 1 / (60 + cross_ranks[index]),
                    -index,
                ),
                reverse=True,
            )
        )
        ranked_candidates: list[dict[str, Any]] = []
        for index in ranked_indices:
            candidate = dict(candidates[index])
            candidate_metadata = dict(candidate.get("metadata") or {})
            candidate_metadata["cross_encoder_rank"] = cross_ranks[index]
            candidate_metadata["cross_encoder_shadow"] = not apply_ranking
            if index in cross_scores:
                candidate_metadata["cross_encoder_score"] = round(cross_scores[index], 6)
            candidate["metadata"] = candidate_metadata
            candidate["score"] = cross_scores.get(index)
            ranked_candidates.append(candidate)
        return ranked_candidates[:top_k] or candidates[:top_k]
    except TimeoutError:
        logger.warning("Universal legal cross-encoder timed out; using local heuristic ranking")
    except Exception as exc:  # noqa: BLE001 - optional reranker must not block legal retrieval
        logger.warning("Universal legal cross-encoder unavailable; using local heuristic ranking: %s", exc)
    return (
        _heuristic_rerank_universal_candidates(query, candidates, top_k)
        if apply_ranking
        else candidates[:top_k]
    )


def warmup_universal_cross_encoder() -> None:
    """Load the optional reranker before the first legal lookup when enabled."""

    from vietnam_legal_agent.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "enable_cross_encoder_rerank", False)):
        return
    model_name = str(getattr(settings, "cross_encoder_model_name", ""))
    if not model_name:
        return
    try:
        _get_universal_cross_encoder(model_name)._ensure_model()
    except Exception as exc:  # noqa: BLE001 - BM25 remains available on warmup failure
        logger.warning("Universal legal cross-encoder warmup unavailable: %s", exc)


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
        run_cross_encoder, apply_cross_encoder = _universal_rerank_mode(settings, query_text)
        universal_limit = limit
        if run_cross_encoder:
            universal_limit = max(limit, int(getattr(settings, "rerank_top_n", limit)))
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
                        limit=universal_limit,
                        required_anchors=query_anchors or None,
                    )
                    if (
                        u_docs
                        and not query_anchors
                        and run_cross_encoder
                    ):
                        u_docs = await _rerank_universal_candidates(
                            query_text,
                            u_docs,
                            model_name=str(getattr(settings, "cross_encoder_model_name", "")),
                            top_k=limit,
                            timeout_ms=int(getattr(settings, "rerank_timeout_ms", 1200)),
                            apply_ranking=apply_cross_encoder,
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
            # BM25 already ranks universal-corpus results against the full
            # query. A second lexical gate and neighbor filter dropped valid
            # paraphrases before answer generation could inspect their text.
            # Keep them ranked; explicit source/article mismatches are still
            # filtered above, and generated claims remain independently
            # checked against these documents before delivery.
            unranked_records = [
                record for record in universal_records
                if record.metadata.get("bm25_rank") is None
            ]
            if unranked_records:
                checker = legal_relevance_checker(
                    min_rerank_score=getattr(settings, "min_legal_rerank_score", 0.40)
                )
                accepted_ids = {
                    id(record)
                    for record in unranked_records
                    if checker(query_text, [record])
                }
                universal_records = [
                    record
                    for record in universal_records
                    if record.metadata.get("bm25_rank") is not None or id(record) in accepted_ids
                ]

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
