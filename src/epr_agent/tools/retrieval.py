"""Retrieval adapters that isolate LangChain/Qdrant objects from the graph."""

from __future__ import annotations

from typing import Any, Protocol

from epr_agent.domain.models import DocumentRecord


class RetrievalGateway(Protocol):
    async def faq(self, query: str, score_threshold: float) -> list[DocumentRecord]: ...

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


class LegacyRetrievalGateway:
    """Call the current FAQ and hybrid legal retrieval without leaking it upward."""

    async def faq(self, query: str, score_threshold: float) -> list[DocumentRecord]:
        from backend.core.retrieval import retrieve_faq_async

        documents = await retrieve_faq_async(query, score_threshold)
        return [_to_record(document, source="faq", index=i) for i, document in enumerate(documents)]

    async def legal(self, query: str) -> list[DocumentRecord]:
        from backend.core.retrieval import retrieve_legal_async

        documents = await retrieve_legal_async(query)
        return [_to_record(document, source="legal", index=i) for i, document in enumerate(documents)]


class StaticRetrievalGateway:
    """Simple injected retrieval gateway useful for local demos and tests."""

    def __init__(self, *, faq_documents: list[DocumentRecord] | None = None, legal_documents: list[DocumentRecord] | None = None) -> None:
        self.faq_documents = faq_documents or []
        self.legal_documents = legal_documents or []
        self.calls: list[tuple[str, str]] = []

    async def faq(self, query: str, score_threshold: float) -> list[DocumentRecord]:
        self.calls.append(("faq", query))
        return list(self.faq_documents)

    async def legal(self, query: str) -> list[DocumentRecord]:
        self.calls.append(("legal", query))
        return list(self.legal_documents)
