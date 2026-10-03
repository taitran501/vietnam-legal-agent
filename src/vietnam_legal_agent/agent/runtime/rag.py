"""Standard LangChain two-step RAG for legal lookup routes."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from langchain.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.retrieval import RetrievalGateway

logger = logging.getLogger(__name__)


class LegalCorpusRetriever(BaseRetriever):
    """Adapt the configured legal corpus gateway to LangChain's retriever API."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    gateway: Any
    k: int = 8

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._retrieve(query))
        raise RuntimeError("Use the asynchronous LangChain retriever inside an event loop")

    async def _aget_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        return await self._retrieve(query)

    async def _retrieve(self, query: str) -> list[Document]:
        records = await self.gateway.legal(query)
        documents: list[Document] = []
        for record in records[: self.k]:
            metadata = dict(record.metadata or {})
            metadata.setdefault("document_id", record.document_id)
            metadata.setdefault("document_source", record.source)
            metadata.setdefault("legal_anchor", metadata.get("Dieu") or metadata.get("Parent_Dieu") or "")
            metadata.setdefault(
                "source_title",
                metadata.get("source") or metadata.get("law_ref") or "Văn bản pháp luật",
            )
            documents.append(Document(page_content=record.content, metadata=metadata))
        return documents


class OfficialWebRetriever(BaseRetriever):
    """Adapt the existing allowlisted official-web search to LangChain."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    gateway: Any
    k: int = 5

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._retrieve(query))
        raise RuntimeError("Use the asynchronous LangChain retriever inside an event loop")

    async def _aget_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        return await self._retrieve(query)

    async def _retrieve(self, query: str) -> list[Document]:
        try:
            _summary, records = await self.gateway.web(query)
        except Exception as exc:  # noqa: BLE001 - the corpus remains available if web search is down
            logger.warning("Official legal web retrieval unavailable: %s", type(exc).__name__)
            return []

        documents: list[Document] = []
        for record in records[: self.k]:
            metadata = dict(record.metadata or {})
            metadata.setdefault("document_id", record.document_id)
            metadata.setdefault("document_source", record.source)
            metadata.setdefault("legal_anchor", metadata.get("anchor") or metadata.get("title") or "")
            metadata.setdefault("source_title", metadata.get("title") or "Nguồn pháp luật chính thức")
            documents.append(Document(page_content=record.content, metadata=metadata))
        return documents


def build_legal_retrieval_chain(gateway: RetrievalGateway) -> Any:
    """Build the standard retrieve-then-generate chain for legal lookup.

    The existing gateway owns corpus ranking. The allowlisted official-web
    retriever adds current public sources; LangChain's EnsembleRetriever fuses
    the two ranked lists using its standard reciprocal-rank fusion.
    """

    from langchain.chains import create_retrieval_chain
    from langchain_core.runnables import RunnableLambda

    from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway

    corpus_retriever = LegalCorpusRetriever(gateway=gateway, k=8)
    official_web_retriever = OfficialWebRetriever(gateway=EvidenceGenerationGateway(), k=5)
    source_ensemble = EnsembleRetriever(
        retrievers=[corpus_retriever, official_web_retriever],
        id_key="document_id",
    )

    async def retrieve_bounded(inputs: dict[str, Any]) -> list[Document]:
        query = str(inputs.get("input") or "")
        queries = [query] if query else []
        candidates = inputs.get("retrieval_queries")
        if isinstance(candidates, list):
            for candidate in candidates[:2]:
                supplemental = " ".join(str(candidate or "").split())[:3000]
                if supplemental and supplemental.casefold() not in {item.casefold() for item in queries}:
                    queries.append(supplemental)

        corpus_lists = await asyncio.gather(*(corpus_retriever.ainvoke(item) for item in queries))
        query_ensemble = EnsembleRetriever(
            retrievers=[corpus_retriever] * len(corpus_lists),
            weights=[1.0] * len(corpus_lists),
            id_key="document_id",
        )
        corpus_documents = query_ensemble.weighted_reciprocal_rank(corpus_lists) if corpus_lists else []
        web_documents = await official_web_retriever.ainvoke(query) if query else []
        retrieved = source_ensemble.weighted_reciprocal_rank([corpus_documents, web_documents])
        unique: list[Document] = []
        seen: set[str] = set()
        for document in retrieved:
            metadata = dict(document.metadata or {})
            identity = str(metadata.get("document_id") or metadata.get("chunk_id") or "")
            identity = identity or hashlib.sha256(document.page_content.encode("utf-8")).hexdigest()
            if identity in seen:
                continue
            seen.add(identity)
            index = len(unique) + 1
            metadata["citation_index"] = index
            metadata["legal_anchor"] = str(
                metadata.get("legal_anchor") or metadata.get("Dieu") or metadata.get("Parent_Dieu") or "văn bản được truy xuất"
            )
            metadata["source_title"] = str(
                metadata.get("source_title") or metadata.get("source") or metadata.get("law_ref") or "Văn bản pháp luật"
            )
            metadata.setdefault("document_id", identity)
            unique.append(Document(page_content=document.page_content, metadata=metadata))
            if len(unique) >= 12:
                break
        return unique

    retriever = RunnableLambda(retrieve_bounded)
    return create_retrieval_chain(
        retriever,
        EvidenceGenerationGateway.legal_document_chain(),
    )


def records_from_retrieved_documents(documents: list[Document]) -> list[DocumentRecord]:
    """Convert LangChain documents back to the application's serialisable model."""

    records: list[DocumentRecord] = []
    for document in documents:
        metadata = dict(document.metadata or {})
        document_id = str(metadata.pop("document_id", metadata.get("chunk_id", "")) or "")
        source = str(metadata.pop("document_source", "legal") or "legal")
        metadata.pop("citation_index", None)
        records.append(
            DocumentRecord(
                content=document.page_content,
                metadata=metadata,
                document_id=document_id,
                source=source,
            )
        )
    return records
