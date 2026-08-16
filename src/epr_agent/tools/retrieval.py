"""Retrieval adapters that isolate LangChain/Qdrant objects from the graph."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Protocol

from epr_agent.domain.models import DocumentRecord
from epr_agent.domain.v4 import RetrievalRequest

logger = logging.getLogger(__name__)


class RetrievalGateway(Protocol):
    async def legal(self, query: str | RetrievalRequest) -> list[DocumentRecord]: ...


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
        metadata.get("document_id")
        or metadata.get("id")
        or metadata.get("source")
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
    """Call the versioned V3 hybrid retriever without leaking Qdrant objects upward."""

    async def legal(self, query: str | RetrievalRequest) -> list[DocumentRecord]:
        from backend.config import get_settings
        from backend.core.retrieval import retrieve_legal_async

        request = query if isinstance(query, RetrievalRequest) else None
        documents = await retrieve_legal_async(
            retrieval_query(query),
            required_anchors=request.required_anchors if request else None,
            metadata_filters=request.metadata_filters if request else None,
            top_k=request.top_k if request else 10,
        )
        settings = get_settings()
        records = [_to_record(document, source="legal", index=i) for i, document in enumerate(documents)]
        for record in records:
            record.metadata.setdefault("source", str(getattr(settings, "law_citation_label", "EPR legal corpus")))
            record.metadata.setdefault("Corpus_Version", str(getattr(settings, "corpus_version", "epr-corpus-v1")))
            record.metadata.setdefault("document_id", record.document_id)
            if request is not None:
                record.metadata.setdefault("v4_issue_id", request.issue_id)
                record.metadata.setdefault("v4_required_anchors", request.required_anchors)

        # Augment with Universal Legal Retriever (84,900+ articles covering Land, Labor, Tax, Corporate, Civil, etc.)
        if len(records) < 5:
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
