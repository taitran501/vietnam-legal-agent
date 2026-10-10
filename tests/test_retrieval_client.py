from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

import vietnam_legal_agent.config
import vietnam_legal_agent.retrieval.retrieval
import vietnam_legal_agent.tools.retrieval as retrieval_module
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
        enable_cross_encoder_rerank=False,
        cross_encoder_shadow_mode=True,
        cross_encoder_rollout_percent=0,
        rerank_top_n=20,
        rerank_timeout_ms=1200,
        cross_encoder_model_name="cross-encoder/test",
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


@pytest.mark.asyncio
async def test_universal_retrieval_reranks_a_wider_generic_candidate_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(qdrant=False, universal=True)
    settings.enable_cross_encoder_rerank = True
    settings.cross_encoder_shadow_mode = False
    settings.cross_encoder_rollout_percent = 100
    settings.rerank_top_n = 10
    monkeypatch.setattr(vietnam_legal_agent.config, "get_settings", lambda: settings)

    class _UniversalPreview:
        is_available = True

        def __init__(self) -> None:
            self.requested_limit: int | None = None

        def search(self, _query, *, limit, required_anchors):
            self.requested_limit = limit
            assert required_anchors is None
            return [
                {
                    "document_id": f"law-{index}",
                    "page_content": f"Nội dung pháp luật số {index}.",
                    "metadata": {
                        "source_kind": "legal_corpus",
                        "corpus_source": "universal_legal",
                        "bm25_rank": float(index),
                        "legal_anchor": f"Điều {index + 1}",
                    },
                }
                for index in range(10)
            ]

    preview = _UniversalPreview()
    monkeypatch.setattr(universal_module, "universal_retriever", preview)
    rerank_calls: list[tuple[str, int, int]] = []

    async def _rank(query, candidates, *, model_name, top_k, timeout_ms, apply_ranking):
        rerank_calls.append((query, len(candidates), top_k))
        assert apply_ranking is True
        assert model_name == "cross-encoder/test"
        assert timeout_ms == 1200
        return list(reversed(candidates[:top_k]))

    monkeypatch.setattr(retrieval_module, "_rerank_universal_candidates", _rank)

    documents = await UniversalLegalRetrievalGateway().legal("What rights does the law provide?")

    assert preview.requested_limit == 10
    assert rerank_calls == [("What rights does the law provide?", 10, 8)]
    assert [document.document_id for document in documents] == [f"law-{index}" for index in range(7, -1, -1)]


@pytest.mark.asyncio
async def test_universal_shadow_rerank_records_scores_without_changing_bm25_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ShadowReranker:
        unavailable_reason = None

        def rerank(self, _query, documents, top_k):
            for rank, document in enumerate(documents, start=1):
                document.metadata["cross_encoder_score"] = float(rank)
            return list(reversed(documents[:top_k]))

    monkeypatch.setattr(
        retrieval_module,
        "_get_universal_cross_encoder",
        lambda _name: _ShadowReranker(),
    )
    candidates = [
        {"document_id": f"bm25-{i}", "page_content": f"Result {i}", "metadata": {"bm25_rank": -i}}
        for i in range(1, 4)
    ]

    ranked = await retrieval_module._rerank_universal_candidates(
        "legal question",
        candidates,
        model_name="cross-encoder/test",
        top_k=3,
        timeout_ms=1000,
        apply_ranking=False,
    )

    assert [document["document_id"] for document in ranked] == ["bm25-1", "bm25-2", "bm25-3"]
    assert [document["metadata"]["cross_encoder_rank"] for document in ranked] == [3, 2, 1]
    assert all(document["metadata"]["cross_encoder_shadow"] is True for document in ranked)


@pytest.mark.asyncio
async def test_universal_reranker_failure_preserves_bm25_order(monkeypatch: pytest.MonkeyPatch) -> None:
    class _UnavailableReranker:
        def rerank(self, *_args, **_kwargs):
            raise RuntimeError("optional model unavailable")

    monkeypatch.setattr(
        retrieval_module,
        "_get_universal_cross_encoder",
        lambda _name: _UnavailableReranker(),
    )
    candidates = [
        {"document_id": "bm25-1", "page_content": "First result", "metadata": {}},
        {"document_id": "bm25-2", "page_content": "Second result", "metadata": {}},
    ]

    ranked = await retrieval_module._rerank_universal_candidates(
        "general legal question",
        candidates,
        model_name="cross-encoder/test",
        top_k=2,
        timeout_ms=1000,
    )

    assert [document["document_id"] for document in ranked] == ["bm25-1", "bm25-2"]


@pytest.mark.asyncio
async def test_cross_encoder_refines_bm25_order_without_discarding_its_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NearTieReranker:
        unavailable_reason = None

        def rerank(self, _query, documents, top_k):
            assert top_k == len(documents)
            return [documents[1], documents[0], *documents[2:]]

    monkeypatch.setattr(
        retrieval_module,
        "_get_universal_cross_encoder",
        lambda _name: _NearTieReranker(),
    )
    candidates = [
        {"document_id": "bm25-1", "page_content": "First result", "metadata": {"bm25_rank": -5}},
        {"document_id": "bm25-2", "page_content": "Second result", "metadata": {"bm25_rank": -4}},
    ]

    ranked = await retrieval_module._rerank_universal_candidates(
        "general legal question",
        candidates,
        model_name="cross-encoder/test",
        top_k=2,
        timeout_ms=1000,
    )

    assert [document["document_id"] for document in ranked] == ["bm25-1", "bm25-2"]
