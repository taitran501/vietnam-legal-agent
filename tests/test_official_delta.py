from __future__ import annotations

from types import SimpleNamespace

import pytest

import epr_agent.config
import epr_agent.retrieval.retrieval
from epr_agent.domain.legal import explicit_anchors
from epr_agent.retrieval.official_delta import DEFAULT_MANIFEST_PATH, OfficialDeltaRetriever
from epr_agent.tools.retrieval import QdrantLegalRetrievalGateway
from epr_agent.tools.source_provenance import canonical_source_snapshots


def test_official_delta_matches_exact_instrument_and_effective_date() -> None:
    retriever = OfficialDeltaRetriever(DEFAULT_MANIFEST_PATH)

    records = retriever.search("Luật số 08/2026/QH16 có hiệu lực từ ngày nào?")

    assert len(records) == 1
    record = records[0]
    assert record.document_id == "law-08-2026-qh16-metadata"
    assert record.metadata["Document_Number"] == "08/2026/QH16"
    assert record.metadata["effective_from"] == "2026-07-01"
    assert record.metadata["official_url"].startswith("https://vanban.chinhphu.vn/")
    assert record.metadata["authority"] == "official"
    assert record.metadata["source_kind"] == "official_delta"
    assert record.metadata["retrieved_at_utc"]


def test_official_delta_matches_article_and_clause() -> None:
    retriever = OfficialDeltaRetriever(DEFAULT_MANIFEST_PATH)

    records = retriever.search(
        "Luật số 08/2026/QH16 Điều 2 Khoản 1 có hiệu lực từ ngày nào?"
    )

    assert [record.document_id for record in records] == ["law-08-2026-qh16-dieu-2-khoan-1"]
    assert explicit_anchors("Luật số 08/2026/QH16 Điều 2 Khoản 1")[0].document_number == "08/2026/QH16"
    assert records[0].metadata["legal_anchor"] == "Điều 2"


def test_official_delta_supports_unaccented_metadata_query() -> None:
    retriever = OfficialDeltaRetriever(DEFAULT_MANIFEST_PATH)

    records = retriever.search("Luat so 08/2026/QH16 co hieu luc tu ngay nao?")

    assert [record.document_id for record in records] == ["law-08-2026-qh16-metadata"]


def test_official_delta_exposes_canonical_source_drawer_record() -> None:
    retriever = OfficialDeltaRetriever(DEFAULT_MANIFEST_PATH)
    record = retriever.search("Luật số 08/2026/QH16 có hiệu lực từ ngày nào?")[0]

    snapshots = canonical_source_snapshots([record.to_dict()])

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["source_id"] == "official:08/2026/QH16"
    assert snapshot["title"].startswith("Luật sửa đổi")
    assert snapshot["instrument_number"] == "08/2026/QH16"
    assert snapshot["official_url"].startswith("https://vanban.chinhphu.vn/")
    assert snapshot["excerpt"].startswith("Luật số 08/2026/QH16")
    assert "||" not in snapshot["excerpt"]


@pytest.mark.parametrize(
    "query",
    [
        "Luật số 09/2026/QH16 có hiệu lực từ ngày nào?",
        "Luật số 08/2026/QH16 quy định chi tiết toàn bộ nội dung gì?",
        "2026 có luật gì mới không?",
        "công ty cổ phần cần bao nhiêu cổ đông?",
    ],
)
def test_official_delta_fails_closed_for_unknown_or_unsupported_queries(query: str) -> None:
    retriever = OfficialDeltaRetriever(DEFAULT_MANIFEST_PATH)

    assert retriever.search(query) == []


@pytest.mark.asyncio
async def test_gateway_uses_exact_official_delta_before_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_official_delta_retrieval=True,
            official_delta_manifest_path=DEFAULT_MANIFEST_PATH,
            enable_relevance_gate=True,
            min_legal_rerank_score=0.40,
            enable_universal_retrieval=False,
            law_citation_label="Vietnamese legal corpus",
            corpus_version="test-corpus",
        ),
    )

    async def _must_not_call_qdrant(*_args, **_kwargs):
        raise AssertionError("exact official delta should be checked before Qdrant")

    monkeypatch.setattr(epr_agent.retrieval.retrieval, "retrieve_legal_async", _must_not_call_qdrant)

    records = await QdrantLegalRetrievalGateway().legal(
        "Luật số 08/2026/QH16 có hiệu lực từ ngày nào?"
    )

    assert len(records) == 1
    assert records[0].metadata["Document_Number"] == "08/2026/QH16"


@pytest.mark.asyncio
async def test_gateway_fails_closed_for_covered_but_unsupported_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_official_delta_retrieval=True,
            official_delta_manifest_path=DEFAULT_MANIFEST_PATH,
            enable_relevance_gate=True,
            min_legal_rerank_score=0.40,
            enable_universal_retrieval=False,
            law_citation_label="Vietnamese legal corpus",
            corpus_version="test-corpus",
        ),
    )

    async def _must_not_call_qdrant(*_args, **_kwargs):
        raise AssertionError("covered unsupported query must not fall through to Qdrant")

    monkeypatch.setattr(epr_agent.retrieval.retrieval, "retrieve_legal_async", _must_not_call_qdrant)

    records = await QdrantLegalRetrievalGateway().legal(
        "Luật số 08/2026/QH16 quy định chi tiết toàn bộ nội dung gì?"
    )

    assert records == []
