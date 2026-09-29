from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import ClassVar

import pytest

from epr_agent.tools.generation import EvidenceGenerationGateway


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
    monkeypatch.setattr("epr_agent.config.get_settings", lambda: settings)
    monkeypatch.setitem(sys.modules, "tavily", SimpleNamespace(TavilyClient=_FakeTavilyClient))
    monkeypatch.setattr("epr_agent.tools.generation._fetch_official_page_text", no_page_text)
    _FakeTavilyClient.calls.clear()
    _FakeTavilyClient.results = [
        {
            "title": "Điều 78 Nghị định 08/2022/NĐ-CP",
            "url": "http://vanban.chinhphu.vn/?docid=205092&utm_source=test#fragment",
            "content": "Điều 78 quy định trách nhiệm tái chế sản phẩm, bao bì theo pháp luật EPR Việt Nam. " * 8,
        },
        {
            "title": "Điều 78 từ blog",
            "url": "https://example.com/epr",
            "content": "Điều 78 và EPR nhưng đây không phải nguồn chính thức.",
        },
        {
            "title": "Nội dung chính thức nhưng sai điều",
            "url": "https://vbpl.vn/noidung.aspx?id=1",
            "content": "Điều 77 quy định trách nhiệm tái chế EPR.",
        },
    ]

    answer, documents = await EvidenceGenerationGateway().web("Điều 78 quy định gì?")

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
    assert "EPR" not in str(call["query"])


@pytest.mark.asyncio
async def test_web_research_safe_empty_when_instrument_does_not_match(monkeypatch) -> None:
    settings = SimpleNamespace(
        tavily_api_key="test-token",
        web_official_domains="vanban.chinhphu.vn,vbpl.vn",
        web_excerpt_max_chars=1200,
    )
    monkeypatch.setattr("epr_agent.config.get_settings", lambda: settings)
    monkeypatch.setitem(sys.modules, "tavily", SimpleNamespace(TavilyClient=_FakeTavilyClient))
    _FakeTavilyClient.results = [
        {
            "title": "Nghị định 05/2025/NĐ-CP",
            "url": "https://vanban.chinhphu.vn/?docid=other",
            "content": "Văn bản pháp luật về tái chế EPR và bảo vệ môi trường. " * 5,
        }
    ]

    answer, documents = await EvidenceGenerationGateway().web(
        "Tìm Nghị định 48/2026/NĐ-CP về EPR"
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
    monkeypatch.setattr("epr_agent.config.get_settings", lambda: settings)

    fake_results = [
        {
            "title": "Nghị định số 100/2019/NĐ-CP quy định xử phạt vi phạm hành chính giao thông",
            "url": "https://vanban.chinhphu.vn/?docid=198826",
            "content": "Nghị định số 100/2019/NĐ-CP của Chính phủ quy định về xử phạt vi phạm hành chính trong lĩnh vực giao thông đường bộ và đường sắt.",
        }
    ]
    monkeypatch.setattr("epr_agent.tools.generation._search_duckduckgo_free", lambda query, domains: fake_results)

    answer, documents = await EvidenceGenerationGateway().web("Nghị định 100/2019/NĐ-CP xử phạt giao thông")

    assert len(documents) == 1
    assert documents[0].metadata["source_kind"] == "official_web"
    assert documents[0].metadata["authority"] == "official"
    assert "https://vanban.chinhphu.vn/?docid=198826" in answer

