"""Retrieval adapters that isolate LangChain/Qdrant objects from the graph."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Protocol

from epr_agent.domain.legal import LegalAnchor, explicit_anchors, parse_required_anchors
from epr_agent.domain.models import DocumentRecord
from epr_agent.domain.v4 import RetrievalRequest
from epr_agent.tools.evidence import legal_relevance_checker

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


class QdrantLegalRetrievalGateway:
    """Call the versioned hybrid retriever with universal statutory legal fallback."""

    async def legal(self, query: str | RetrievalRequest) -> list[DocumentRecord]:
        from epr_agent.config import get_settings
        from epr_agent.retrieval.retrieval import retrieve_legal_async

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

        # The official delta is a deliberately narrow preview source. Check
        # it before Qdrant so an exact instrument cannot be shadowed by a
        # nearest-neighbour result.
        if bool(getattr(settings, "enable_official_delta_retrieval", False)):
            try:
                from epr_agent.retrieval.official_delta import OfficialDeltaRetriever

                delta_retriever = OfficialDeltaRetriever(getattr(settings, "official_delta_manifest_path", None))
                delta_documents = delta_retriever.search(
                    query_text,
                    limit=request.top_k if request else 5,
                    required_anchors=typed_required_anchors,
                )
                if delta_documents:
                    return delta_documents
                if delta_retriever.covers_instrument(
                    query_text,
                    required_anchors=typed_required_anchors,
                ):
                    return []
            except (OSError, TypeError, ValueError) as exc:
                logger.warning("Official delta retrieval skipped: %s", exc)

        documents = []
        try:
            documents = await retrieve_legal_async(
                query_text,
                required_anchors=request.required_anchors if request else None,
                metadata_filters=request.metadata_filters if request else None,
                top_k=request.top_k if request else 10,
            )
        except Exception as exc:  # noqa: BLE001 - fallback to Universal Legal Retriever
            logger.debug("Primary Qdrant legal retrieval unavailable (%s), falling back to universal legal corpus", exc)

        records = [_to_record(document, source="legal", index=i) for i, document in enumerate(documents)]
        for record in records:
            record.metadata.setdefault("source", str(getattr(settings, "law_citation_label", "Vietnamese legal corpus")))
            record.metadata.setdefault("Corpus_Version", str(getattr(settings, "corpus_version", "epr-corpus-v1")))
            record.metadata.setdefault("document_id", record.document_id)
            if request is not None:
                record.metadata.setdefault("v4_issue_id", request.issue_id)
                record.metadata.setdefault("v4_required_anchors", request.required_anchors)

        has_typed_anchors = bool(request and request.required_anchors)
        if (
            records
            and bool(getattr(settings, "enable_relevance_gate", True))
            and not has_typed_anchors
            and not explicit_anchors(query_text)
        ):
            checker = legal_relevance_checker(
                min_rerank_score=getattr(settings, "min_legal_rerank_score", 0.40)
            )
            records = [record for record in records if checker(query_text, [record])]

        # Universal Corpus (84,900+ provisions): Search and augment when Qdrant has insufficient records
        if bool(getattr(settings, "enable_universal_retrieval", True)) and len(records) < 5:
            try:
                from epr_agent.retrieval.universal_retriever import universal_retriever
                if universal_retriever.is_available:
                    needed = (request.top_k if request else 8) - len(records)
                    u_docs = universal_retriever.search(retrieval_query(query), limit=needed)
                    for i, u_doc in enumerate(u_docs):
                        u_meta = dict(u_doc.get("metadata", {}))
                        records.append(DocumentRecord(
                            content=u_doc["page_content"],
                            metadata=u_meta,
                            document_id=u_doc.get("document_id", f"univ-{i+1}"),
                            score=u_doc.get("score", 0.85),
                            source=str(u_meta.get("source") or "Pháp điển & Luật Quốc gia"),
                        ))
            except (sqlite3.Error, OSError, ImportError) as exc:
                logger.debug("Universal retriever augmentation skipped: %s", exc)

        return records


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
