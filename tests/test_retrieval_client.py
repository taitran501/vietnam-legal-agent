from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

import epr_agent.config
import epr_agent.retrieval.retrieval
from epr_agent.domain.models import DocumentRecord
from epr_agent.retrieval import universal_retriever as universal_module
from epr_agent.tools.retrieval import QdrantLegalRetrievalGateway, StaticRetrievalGateway


@pytest.mark.asyncio
async def test_legal_gateway_has_no_faq_surface() -> None:
    gateway = StaticRetrievalGateway(
        legal_documents=[DocumentRecord(content="Điều 77", metadata={"Dieu": "Điều 77"}, document_id="77", source="legal")]
    )

    documents = await gateway.legal("Điều 77 quy định gì?")

    assert [document.document_id for document in documents] == ["77"]
    assert gateway.calls == [("legal", "Điều 77 quy định gì?")]
    assert not hasattr(gateway, "faq")


@pytest.mark.asyncio
async def test_universal_retrieval_is_not_an_implicit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_universal_retrieval=False,
            law_citation_label="Vietnamese legal corpus",
            corpus_version="test-corpus",
        ),
    )

    async def _empty_retrieval(*_args, **_kwargs):
        return []

    monkeypatch.setattr(epr_agent.retrieval.retrieval, "retrieve_legal_async", _empty_retrieval)

    class _UniversalPreview:
        is_available = True

        def search(self, *_args, **_kwargs):
            return [{"page_content": "unapproved preview source", "document_id": "univ-1", "metadata": {}}]

    monkeypatch.setattr(universal_module, "universal_retriever", _UniversalPreview())

    documents = await QdrantLegalRetrievalGateway().legal("Luật đất đai quy định gì?")

    assert documents == []


@pytest.mark.asyncio
async def test_qdrant_gateway_filters_cross_domain_neighbours_before_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_relevance_gate=True,
            min_legal_rerank_score=0.40,
            enable_universal_retrieval=False,
            law_citation_label="Vietnamese legal corpus",
            corpus_version="test-corpus",
        ),
    )

    async def _retrieval(*_args, **_kwargs):
        return [
            Document(
                page_content="Điều 77 quy định trách nhiệm tái chế bao bì và sản phẩm.",
                metadata={
                    "Dieu": "Điều 77",
                    "Document_Number": "08/2022/NĐ-CP",
                    "source_title": "Nghị định 08/2022/NĐ-CP",
                    "source_file": "epr.doc",
                    "Corpus_Version": "test",
                    "Corpus_SHA256": "test-sha",
                    "Embedding_Profile": "test",
                    "rerank_score": 0.95,
                },
            ),
            Document(
                page_content="Điều 111 quy định công ty cổ phần có tối thiểu 03 cổ đông.",
                metadata={
                    "Dieu": "Điều 111",
                    "Document_Number": "59/2020/QH14",
                    "source_title": "Luật Doanh nghiệp 2020",
                    "source_file": "corporate.doc",
                    "Corpus_Version": "test",
                    "Corpus_SHA256": "test-sha",
                    "Embedding_Profile": "test",
                    "rerank_score": 0.95,
                },
            ),
        ]

    monkeypatch.setattr(epr_agent.retrieval.retrieval, "retrieve_legal_async", _retrieval)

    documents = await QdrantLegalRetrievalGateway().legal(
        "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông theo quy định?"
    )

    assert [document.metadata["Document_Number"] for document in documents] == ["59/2020/QH14"]
