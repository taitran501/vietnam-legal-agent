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


@pytest.mark.asyncio
async def test_qdrant_gateway_filters_universal_cross_domain_neighbors_before_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_relevance_gate=True,
            min_legal_rerank_score=0.40,
            enable_universal_retrieval=True,
            enable_official_delta_retrieval=False,
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
            return [
                {
                    "document_id": "fee",
                    "page_content": "Phí thẩm định phương án cải tạo, phục hồi môi trường do cơ quan trung ương thực hiện.",
                    "metadata": {
                        "source_title": "Thông tư về phí thẩm định môi trường",
                        "source": "Thông tư về phí thẩm định môi trường",
                        "source_kind": "legal_corpus",
                        "corpus_source": "universal_legal",
                        "topic": "Thuế, phí, lệ phí",
                        "subject": "Phí và lệ phí",
                    },
                    "bm25_rank": -25.6,
                },
                {
                    "document_id": "insurance",
                    "page_content": "Điều 32. Đối tượng bảo hiểm theo quy định về kinh doanh bảo hiểm.",
                    "metadata": {
                        "source_title": "Nghị định về kinh doanh bảo hiểm",
                        "source": "Nghị định về kinh doanh bảo hiểm",
                        "source_kind": "legal_corpus",
                        "corpus_source": "universal_legal",
                        "topic": "Bảo hiểm",
                        "subject": "Kinh doanh bảo hiểm",
                    },
                    "bm25_rank": -23.8,
                },
                {
                    "document_id": "environment-54",
                    "page_content": (
                        "Điều 54. Tổ chức, cá nhân sản xuất, nhập khẩu sản phẩm, bao bì có giá trị "
                        "tái chế phải thực hiện tái chế theo tỷ lệ và quy cách bắt buộc."
                    ),
                    "metadata": {
                        "Dieu": "Điều 54. Trách nhiệm tái chế",
                        "legal_anchor": "Điều 54. Trách nhiệm tái chế",
                        "source_title": "Luật Bảo vệ môi trường",
                        "source": "Luật Bảo vệ môi trường",
                        "source_kind": "legal_corpus",
                        "corpus_source": "universal_legal",
                        "topic": "Luật Quốc gia",
                        "subject": "Luật Bảo vệ môi trường",
                    },
                    "bm25_rank": -104.8,
                },
            ]

    monkeypatch.setattr(universal_module, "universal_retriever", _UniversalPreview())

    documents = await QdrantLegalRetrievalGateway().legal(
        "Công ty sản xuất nước đóng chai dùng bao bì nhựa có nghĩa vụ gì theo EPR?"
    )

    assert [document.document_id for document in documents] == ["environment-54"]


@pytest.mark.asyncio
async def test_named_instrument_anchor_filters_an_epr_article_number_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_relevance_gate=True,
            min_legal_rerank_score=0.40,
            enable_universal_retrieval=False,
            enable_official_delta_retrieval=False,
            law_citation_label="Vietnamese legal corpus",
            corpus_version="epr-test-corpus",
        ),
    )

    async def _epr_article_41(*_args, **_kwargs):
        return [
            Document(
                page_content="Điều 41 của Nghị định 08/2022/NĐ-CP quy định thẩm quyền môi trường.",
                metadata={
                    "Dieu": "Điều 41",
                    "Document_Number": "08/2022/NĐ-CP",
                    "source_title": "Nghị định số 08/2022/NĐ-CP quy định chi tiết Luật Bảo vệ môi trường",
                    "topic": "Môi trường",
                    "source_file": "epr.doc",
                    "Corpus_Version": "test",
                    "Corpus_SHA256": "test-sha",
                    "Embedding_Profile": "test",
                    "rerank_score": 0.95,
                },
            )
        ]

    monkeypatch.setattr(epr_agent.retrieval.retrieval, "retrieve_legal_async", _epr_article_41)

    documents = await QdrantLegalRetrievalGateway().legal(
        "Điều 41 Bộ luật Lao động 2019 quy định gì?"
    )

    assert documents == []


@pytest.mark.asyncio
async def test_named_instrument_query_falls_back_to_the_exact_universal_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_relevance_gate=True,
            min_legal_rerank_score=0.40,
            enable_universal_retrieval=True,
            enable_official_delta_retrieval=False,
            law_citation_label="Vietnamese legal corpus",
            corpus_version="epr-test-corpus",
        ),
    )

    async def _epr_article_41(*_args, **_kwargs):
        return [
            Document(
                page_content="Điều 41 của Nghị định 08/2022/NĐ-CP quy định thẩm quyền môi trường.",
                metadata={
                    "Dieu": "Điều 41",
                    "Document_Number": "08/2022/NĐ-CP",
                    "source_title": "Nghị định số 08/2022/NĐ-CP quy định chi tiết Luật Bảo vệ môi trường",
                    "topic": "Môi trường",
                    "source_file": "epr.doc",
                    "Corpus_Version": "test",
                    "Corpus_SHA256": "test-sha",
                    "Embedding_Profile": "test",
                    "rerank_score": 0.95,
                },
            )
        ]

    class _UniversalPreview:
        is_available = True

        def search(self, query, *, limit, required_anchors):
            assert "Bộ luật Lao động 2019" in query
            assert required_anchors[0].document_title == "Bộ luật Lao động 2019"
            return [
                {
                    "document_id": "labor-code-41",
                    "page_content": "Điều 41 Bộ luật số 45/2019/QH14 quy định nghĩa vụ của người sử dụng lao động.",
                    "score": 0.95,
                    "metadata": {
                        "Dieu": "Điều 41",
                        "source_article": "Điều 41",
                        "legal_anchor": "Điều 41",
                        "Document_Number": "45/2019/QH14",
                        "source_title": "Điều 41 Bộ luật số 45/2019/QH14",
                        "law_ref": "Điều 41 Bộ luật số 45/2019/QH14",
                        "topic": "Lao động",
                        "source_kind": "legal_corpus",
                    },
                }
            ]

    monkeypatch.setattr(epr_agent.retrieval.retrieval, "retrieve_legal_async", _epr_article_41)
    monkeypatch.setattr(universal_module, "universal_retriever", _UniversalPreview())

    documents = await QdrantLegalRetrievalGateway().legal(
        "Điều 41 Bộ luật Lao động 2019 quy định gì?"
    )

    assert len(documents) == 1
    assert documents[0].document_id == "labor-code-41"
    assert documents[0].metadata["Document_Number"] == "45/2019/QH14"
    assert documents[0].source == "legal"
    assert documents[0].score is None


@pytest.mark.asyncio
async def test_bare_article_query_does_not_accept_cross_domain_universal_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_relevance_gate=True,
            min_legal_rerank_score=0.40,
            enable_universal_retrieval=True,
            enable_official_delta_retrieval=False,
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
            return [
                {
                    "document_id": "auction-77",
                    "page_content": "Điều 77. Trách nhiệm của Chính phủ trong công tác quản lý nhà nước về đấu giá tài sản.",
                    "metadata": {
                        "Dieu": "Điều 77. Trách nhiệm về đấu giá tài sản",
                        "legal_anchor": "Điều 77. Trách nhiệm về đấu giá tài sản",
                        "source_title": "Luật Đấu giá tài sản",
                        "source": "Luật Đấu giá tài sản",
                        "source_kind": "legal_corpus",
                        "corpus_source": "universal_legal",
                        "topic": "Đấu giá tài sản",
                    },
                }
            ]

    monkeypatch.setattr(universal_module, "universal_retriever", _UniversalPreview())

    documents = await QdrantLegalRetrievalGateway().legal(
        "Điều 77 về trách nhiệm tái chế bao bì EPR quy định gì?"
    )

    assert documents == []
