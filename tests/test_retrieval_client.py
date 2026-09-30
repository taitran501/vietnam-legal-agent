from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

import vietnam_legal_agent.config
import vietnam_legal_agent.retrieval.retrieval
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.retrieval import universal_retriever as universal_module
from vietnam_legal_agent.tools.retrieval import (
    StaticRetrievalGateway,
    UniversalLegalRetrievalGateway,
)


def _settings(*, qdrant: bool, universal: bool) -> SimpleNamespace:
    return SimpleNamespace(
        enable_qdrant_retrieval=qdrant,
        enable_universal_retrieval=universal,
        enable_official_delta_retrieval=False,
        enable_relevance_gate=True,
        min_legal_rerank_score=0.40,
        law_citation_label="Vietnamese legal corpus",
        corpus_version="multi-domain-test",
    )


@pytest.mark.asyncio
async def test_legal_gateway_has_no_faq_surface() -> None:
    gateway = StaticRetrievalGateway(
        legal_documents=[
            DocumentRecord(
                content="Điều 25 quy định thời gian thử việc.",
                metadata={"Dieu": "Điều 25"},
                document_id="labor-25",
                source="legal",
            )
        ]
    )

    documents = await gateway.legal("Điều 25 quy định gì?")

    assert [document.document_id for document in documents] == ["labor-25"]
    assert gateway.calls == [("legal", "Điều 25 quy định gì?")]
    assert not hasattr(gateway, "faq")


@pytest.mark.asyncio
async def test_universal_retrieval_is_not_an_implicit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        vietnam_legal_agent.config,
        "get_settings",
        lambda: _settings(qdrant=False, universal=False),
    )

    async def _empty_retrieval(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        vietnam_legal_agent.retrieval.retrieval,
        "retrieve_legal_async",
        _empty_retrieval,
    )

    class _UniversalPreview:
        is_available = True

        def search(self, *_args, **_kwargs):
            return [{"page_content": "unselected preview source", "document_id": "univ-1", "metadata": {}}]

    monkeypatch.setattr(universal_module, "universal_retriever", _UniversalPreview())

    documents = await UniversalLegalRetrievalGateway().legal(
        "Luật đất đai quy định gì?"
    )

    assert documents == []


@pytest.mark.asyncio
async def test_qdrant_relevance_gate_removes_cross_domain_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vietnam_legal_agent.config,
        "get_settings",
        lambda: _settings(qdrant=True, universal=False),
    )

    async def _retrieval(*_args, **_kwargs):
        return [
            Document(
                page_content="Điều 25 quy định thời gian thử việc tối đa theo từng nhóm công việc.",
                metadata={
                    "Dieu": "Điều 25",
                    "Document_Number": "45/2019/QH14",
                    "source_title": "Bộ luật Lao động 2019",
                    "Corpus_Version": "test",
                    "Corpus_SHA256": "test-sha",
                    "Embedding_Profile": "test",
                    "rerank_score": 0.95,
                },
            ),
            Document(
                page_content="Điều 111 quy định công ty cổ phần phải có tối thiểu ba cổ đông.",
                metadata={
                    "Dieu": "Điều 111",
                    "Document_Number": "59/2020/QH14",
                    "source_title": "Luật Doanh nghiệp 2020",
                    "Corpus_Version": "test",
                    "Corpus_SHA256": "test-sha",
                    "Embedding_Profile": "test",
                    "rerank_score": 0.95,
                },
            ),
        ]

    monkeypatch.setattr(
        vietnam_legal_agent.retrieval.retrieval,
        "retrieve_legal_async",
        _retrieval,
    )

    documents = await UniversalLegalRetrievalGateway().legal(
        "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông theo quy định?"
    )

    assert [document.metadata["Document_Number"] for document in documents] == [
        "59/2020/QH14"
    ]


@pytest.mark.asyncio
async def test_named_instrument_anchor_filters_a_different_law_with_same_article_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vietnam_legal_agent.config,
        "get_settings",
        lambda: _settings(qdrant=True, universal=False),
    )

    async def _retrieval(*_args, **_kwargs):
        return [
            Document(
                page_content="Điều 41 của Luật Doanh nghiệp quy định nội dung điều lệ công ty.",
                metadata={
                    "Dieu": "Điều 41",
                    "Document_Number": "59/2020/QH14",
                    "source_title": "Luật Doanh nghiệp 2020",
                    "Corpus_Version": "test",
                    "Corpus_SHA256": "test-sha",
                    "Embedding_Profile": "test",
                    "rerank_score": 0.95,
                },
            )
        ]

    monkeypatch.setattr(
        vietnam_legal_agent.retrieval.retrieval,
        "retrieve_legal_async",
        _retrieval,
    )

    documents = await UniversalLegalRetrievalGateway().legal(
        "Điều 41 Bộ luật Lao động 2019 quy định gì?"
    )

    assert documents == []


@pytest.mark.asyncio
async def test_named_instrument_query_uses_the_matching_universal_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vietnam_legal_agent.config,
        "get_settings",
        lambda: _settings(qdrant=True, universal=True),
    )

    async def _wrong_qdrant_result(*_args, **_kwargs):
        return [
            Document(
                page_content="Điều 41 của Luật Doanh nghiệp quy định nội dung điều lệ công ty.",
                metadata={
                    "Dieu": "Điều 41",
                    "Document_Number": "59/2020/QH14",
                    "source_title": "Luật Doanh nghiệp 2020",
                    "rerank_score": 0.95,
                },
            )
        ]

    class _UniversalPreview:
        is_available = True

        def search(self, query, *, limit, required_anchors):
            assert "Bộ luật Lao động" in query
            assert required_anchors[0].document_title == "Bộ luật Lao động 2019"
            return [
                {
                    "document_id": "labor-code-41",
                    "page_content": "Điều 41 Bộ luật Lao động quy định nghĩa vụ khi chấm dứt hợp đồng trái pháp luật.",
                    "metadata": {
                        "Dieu": "Điều 41",
                        "legal_anchor": "Điều 41",
                        "Document_Number": "45/2019/QH14",
                        "source_title": "Bộ luật Lao động 2019",
                        "law_ref": "Điều 41 Bộ luật Lao động 2019",
                        "source_kind": "legal_corpus",
                    },
                }
            ]

    monkeypatch.setattr(
        vietnam_legal_agent.retrieval.retrieval,
        "retrieve_legal_async",
        _wrong_qdrant_result,
    )
    monkeypatch.setattr(universal_module, "universal_retriever", _UniversalPreview())

    documents = await UniversalLegalRetrievalGateway().legal(
        "Điều 41 Bộ luật Lao động 2019 quy định gì?"
    )

    assert len(documents) == 1
    assert documents[0].document_id == "labor-code-41"
    assert documents[0].metadata["Document_Number"] == "45/2019/QH14"
    assert documents[0].source == "legal"
    assert documents[0].score is None
