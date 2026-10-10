from __future__ import annotations

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake import FakeListLLM

from vietnam_legal_agent.agent.runtime.rag import build_legal_retrieval_chain
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


@pytest.mark.asyncio
async def test_legal_lookup_uses_langchain_retrieval_and_stuff_documents_chains(monkeypatch):
    source = DocumentRecord(
        content="Người lao động có trình độ cao đẳng được thử việc tối đa 60 ngày.",
        document_id="labor-25",
        metadata={
            "Dieu": "Điều 25",
            "source_title": "Bộ luật Lao động 2019",
        },
    )
    monkeypatch.setattr(
        "vietnam_legal_agent.infra.llm_instances.get_llm_smart",
        lambda: FakeListLLM(responses=["Thời gian thử việc tối đa là 60 ngày [1]."]),
    )

    async def no_web_results(_self, _query):
        return "", []

    monkeypatch.setattr(EvidenceGenerationGateway, "web", no_web_results)

    chain = build_legal_retrieval_chain(StaticRetrievalGateway(legal_documents=[source]))
    result = await chain.ainvoke({"input": "Trình độ cao đẳng được thử việc tối đa bao lâu?"})

    assert result["answer"] == "Thời gian thử việc tối đa là 60 ngày [1]."
    assert len(result["context"]) == 1
    assert result["context"][0].metadata["citation_index"] == 1
    assert result["context"][0].metadata["legal_anchor"] == "Điều 25"
    assert isinstance(result["context"][0], Document)


@pytest.mark.asyncio
async def test_legal_lookup_preserves_the_original_query(monkeypatch):
    original_query = "Công ty trả lương làm thêm ngày lễ thế nào?"
    direct = DocumentRecord(
        content="Điều 98 quy định tiền lương làm thêm vào ngày lễ.",
        document_id="labor-98",
        metadata={"Dieu": "Điều 98", "source_title": "Bộ luật Lao động"},
    )
    class QueryAwareGateway:
        def __init__(self):
            self.calls = []

        async def legal(self, query):
            self.calls.append(query)
            return [direct]

    gateway = QueryAwareGateway()
    monkeypatch.setattr(
        "vietnam_legal_agent.infra.llm_instances.get_llm_smart",
        lambda: FakeListLLM(responses=["Tiền lương làm thêm ngày lễ theo Điều 98 [1]."]),
    )

    async def no_web_results(_self, _query):
        return "", []

    monkeypatch.setattr(EvidenceGenerationGateway, "web", no_web_results)

    chain = build_legal_retrieval_chain(gateway)
    result = await chain.ainvoke({"input": original_query})

    assert result["context"][0].metadata["document_id"] == "labor-98"
    assert [doc.metadata["document_id"] for doc in result["context"]] == ["labor-98"]
    assert gateway.calls == [original_query]


@pytest.mark.asyncio
async def test_legal_lookup_uses_existing_supplemental_queries_without_dropping_original(monkeypatch):
    original_query = "Mua hàng bị lỗi thì tôi có quyền đổi trả không?"
    supplemental_query = "Quy định về quyền đổi trả hàng hóa bị lỗi của người tiêu dùng"
    original = DocumentRecord(
        content="Quy định chung về quyền người mua.",
        document_id="general-consumer-rights",
        metadata={"source_title": "Luật Bảo vệ quyền lợi người tiêu dùng"},
    )
    supplemental = DocumentRecord(
        content="Điều 30 quy định nghĩa vụ bảo hành sản phẩm, hàng hóa.",
        document_id="consumer-warranty-30",
        metadata={"Dieu": "Điều 30", "source_title": "Luật Bảo vệ quyền lợi người tiêu dùng"},
    )

    class QueryAwareGateway:
        def __init__(self):
            self.calls = []

        async def legal(self, query):
            self.calls.append(query)
            return [supplemental] if query == supplemental_query else [original]

    gateway = QueryAwareGateway()
    monkeypatch.setattr(
        "vietnam_legal_agent.infra.llm_instances.get_llm_smart",
        lambda: FakeListLLM(responses=["Tùy trường hợp bảo hành và thỏa thuận mua bán [1]."]),
    )

    async def no_web_results(_self, _query):
        return "", []

    monkeypatch.setattr(EvidenceGenerationGateway, "web", no_web_results)

    chain = build_legal_retrieval_chain(gateway)
    result = await chain.ainvoke(
        {"input": original_query, "retrieval_queries": [supplemental_query]}
    )

    assert gateway.calls == [original_query, supplemental_query]
    assert {doc.metadata["document_id"] for doc in result["context"]} == {
        "general-consumer-rights",
        "consumer-warranty-30",
    }


@pytest.mark.asyncio
async def test_legal_lookup_fuses_corpus_and_official_web_evidence(monkeypatch):
    local_source = DocumentRecord(
        content="Điều 25 Bộ luật Lao động quy định thời hạn thử việc.",
        document_id="labor-25",
        metadata={"Dieu": "Điều 25", "source_title": "Bộ luật Lao động"},
    )
    official_source = DocumentRecord(
        content="Nghị định hướng dẫn luật mới quy định mức thuế áp dụng.",
        document_id="official-tax-law",
        source="web",
        metadata={
            "title": "Nghị định hướng dẫn Luật Thuế thu nhập cá nhân",
            "official_url": "https://vanban.chinhphu.vn/?docid=123",
            "source_kind": "official_web",
            "authority": "official",
        },
    )
    monkeypatch.setattr(
        "vietnam_legal_agent.infra.llm_instances.get_llm_smart",
        lambda: FakeListLLM(responses=["Mức thuế được quy định trong nguồn chính thức [1]."]),
    )

    async def fake_web(self, query):
        assert "thuế" in query.casefold()
        return "", [official_source]

    monkeypatch.setattr(EvidenceGenerationGateway, "web", fake_web)
    chain = build_legal_retrieval_chain(StaticRetrievalGateway(legal_documents=[local_source]))
    result = await chain.ainvoke({"input": "Thuế theo luật mới được quy định thế nào?"})

    assert any(doc.metadata.get("source_kind") == "official_web" for doc in result["context"])
    assert any(doc.metadata.get("document_id") == "labor-25" for doc in result["context"])
