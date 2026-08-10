"""Retrieval adapters that isolate LangChain/Qdrant objects from the graph."""

from __future__ import annotations

from typing import Any, Protocol

from epr_agent.domain.models import DocumentRecord


class RetrievalGateway(Protocol):
    async def legal(self, query: str) -> list[DocumentRecord]: ...


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

    async def legal(self, query: str) -> list[DocumentRecord]:
        from backend.config import get_settings
        from backend.core.retrieval import retrieve_legal_async

        documents = await retrieve_legal_async(query)
        settings = get_settings()
        records = [_to_record(document, source="legal", index=i) for i, document in enumerate(documents)]
        for record in records:
            record.metadata.setdefault("source", str(getattr(settings, "law_citation_label", "EPR legal corpus")))
            record.metadata.setdefault("Corpus_Version", str(getattr(settings, "corpus_version", "epr-corpus-v1")))
            record.metadata.setdefault("document_id", record.document_id)
        return records


class StaticRetrievalGateway:
    """Simple injected retrieval gateway useful for local demos and tests."""

    def __init__(self, *, legal_documents: list[DocumentRecord] | None = None) -> None:
        self.legal_documents = legal_documents or []
        self.calls: list[tuple[str, str]] = []

    async def legal(self, query: str) -> list[DocumentRecord]:
        self.calls.append(("legal", query))
        return list(self.legal_documents)
