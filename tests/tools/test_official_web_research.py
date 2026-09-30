from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import ClassVar

import pytest

from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway


class _FakeTavilyClient:
    results: ClassVar[list[dict[str, str]]] = []
    calls: ClassVar[list[dict[str, object]]] = []

    def __init__(self, *, api_key: str) -> None:
        assert api_key == "test-token"

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": list(self.results)}


@pytest.mark.asyncio
async def test_web_research_keeps_only_official_anchor_matching_results(monkeypatch) -> None:
    async def no_page_text(*_args, **_kwargs) -> str:
        return ""

    settings = SimpleNamespace(
        tavily_api_key="test-token",
        web_official_domains="vanban.chinhphu.vn,vbpl.vn",
        web_excerpt_max_chars=220,
    )
    monkeypatch.setattr("vietnam_legal_agent.config.get_settings", lambda: settings)
    monkeypatch.setitem(sys.modules, "tavily", SimpleNamespace(TavilyClient=_FakeTavilyClient))
    monkeypatch.setattr("vietnam_legal_agent.tools.generation._fetch_official_page_text", no_page_text)
    _FakeTavilyClient.calls.clear()
    _FakeTavilyClient.results = [
        {
            "title": "Điều 25 Bộ luật Lao động 2019",
            "url": "http://vanban.chinhphu.vn/?docid=205092&utm_source=test#fragment",
            "content": "Điều 25 quy định thời gian thử việc tối đa đối với từng nhóm công việc. " * 8,
        },
        {
            "title": "Điều 25 từ blog",
            "url": "https://example.com/labor-law",
            "content": "Điều 25 nhưng đây không phải nguồn chính thức.",
        },
        {
            "title": "Nội dung chính thức nhưng sai điều",
            "url": "https://vbpl.vn/noidung.aspx?id=1",
            "content": "Điều 24 quy định một nội dung khác trong Bộ luật Lao động.",
        },
    ]

    answer, documents = await EvidenceGenerationGateway().web("Điều 25 Bộ luật Lao động quy định gì?")

    assert len(documents) == 1
    document = documents[0]
    assert document.metadata["authority"] == "official"
    assert document.metadata["source_kind"] == "official_web"
    assert document.metadata["official_url"] == "https://vanban.chinhphu.vn/?docid=205092"
    assert document.metadata["content_origin"] == "search_result_snippet"
    assert len(document.content) == 220
    assert "Nguồn chính thức ngoài corpus" in answer
    call = _FakeTavilyClient.calls[0]
    assert call["include_domains"] == ["vanban.chinhphu.vn", "vbpl.vn"]
    assert "Việt Nam văn bản pháp luật chính thức" in str(call["query"])
    assert "Điều 25" in str(call["query"])


@pytest.mark.asyncio
async def test_web_research_safe_empty_when_instrument_does_not_match(monkeypatch) -> None:
    settings = SimpleNamespace(
        tavily_api_key="test-token",
        web_official_domains="vanban.chinhphu.vn,vbpl.vn",
        web_excerpt_max_chars=1200,
    )
    monkeypatch.setattr("vietnam_legal_agent.config.get_settings", lambda: settings)
    monkeypatch.setitem(sys.modules, "tavily", SimpleNamespace(TavilyClient=_FakeTavilyClient))
    _FakeTavilyClient.results = [
        {
            "title": "Nghị định 05/2025/NĐ-CP",
            "url": "https://vanban.chinhphu.vn/?docid=other",
            "content": "Văn bản pháp luật về giao kết hợp đồng lao động. " * 5,
        }
    ]

    answer, documents = await EvidenceGenerationGateway().web(
        "Tìm Nghị định 48/2026/NĐ-CP về xử phạt giao thông"
    )

    assert answer == ""
    assert documents == []


@pytest.mark.asyncio
async def test_web_research_free_fallback(monkeypatch) -> None:
    settings = SimpleNamespace(
        tavily_api_key="",
        web_official_domains="vanban.chinhphu.vn,vbpl.vn",
        web_excerpt_max_chars=300,
    )
    monkeypatch.setattr("vietnam_legal_agent.config.get_settings", lambda: settings)

    fake_results = [
        {
            "title": "Nghị định số 100/2019/NĐ-CP quy định xử phạt vi phạm hành chính giao thông",
            "url": "https://vanban.chinhphu.vn/?docid=198826",
            "content": "Nghị định số 100/2019/NĐ-CP của Chính phủ quy định về xử phạt vi phạm hành chính trong lĩnh vực giao thông đường bộ và đường sắt.",
        }
    ]
    monkeypatch.setattr("vietnam_legal_agent.tools.generation._search_duckduckgo_free", lambda query, domains: fake_results)

    answer, documents = await EvidenceGenerationGateway().web("Nghị định 100/2019/NĐ-CP xử phạt giao thông")

    assert len(documents) == 1
    assert documents[0].metadata["source_kind"] == "official_web"
    assert documents[0].metadata["authority"] == "official"
    assert "https://vanban.chinhphu.vn/?docid=198826" in answer

