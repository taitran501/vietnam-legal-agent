"""Contract tests for the generated universal legal corpus artifact."""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pytest

from vietnam_legal_agent.domain.legal import explicit_anchors
from vietnam_legal_agent.retrieval.universal_retriever import DEFAULT_DB_PATH, UniversalLegalRetriever

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data" / "universal_corpus_manifest.json"


def _load_lock() -> dict[str, object]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def test_universal_corpus_lock_has_content_hashes_and_reproducible_output() -> None:
    lock = _load_lock()
    source = lock["source"]
    inputs = lock["inputs"]
    output = lock["output"]

    assert lock["schema_version"] == "universal-legal-corpus-lock-v1"
    assert lock["corpus_id"] == "universal-vietnamese-legal"
    assert source["dataset"] == "tmquan/phapdien-moj-gov-vn"
    assert source["content_lock"] == "sha256"
    assert source["license"] == "CC-BY-4.0"
    assert len(inputs) == 8

    downloaded_inputs = [item for item in inputs if "download_uri" in item]
    tracked_inputs = [item for item in inputs if item.get("source") == "tracked-repository-input"]
    assert len(downloaded_inputs) == 8
    assert tracked_inputs == []
    assert sum(int(item["rows"]) for item in inputs) == 66273
    for item in inputs:
        assert len(item["sha256"]) == 64
        assert int(item["size_bytes"]) > 0
        assert int(item["rows"]) > 0

    assert output["path"] == "data/corpus/universal_legal/universal_legal.db"
    assert output["expected_tables"] == ["legal_articles", "legal_articles_fts"]
    assert output["expected_rows"] == 84308


def test_universal_retriever_default_path_is_repository_root_relative(monkeypatch) -> None:
    monkeypatch.delenv("UNIVERSAL_CORPUS_DB_PATH", raising=False)

    retriever = UniversalLegalRetriever()

    assert DEFAULT_DB_PATH == ROOT / "data" / "corpus" / "universal_legal" / "universal_legal.db"
    assert retriever.db_path == DEFAULT_DB_PATH


def test_universal_retriever_marks_an_empty_database_unavailable(tmp_path: Path) -> None:
    db_path = tmp_path / "empty-universal.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE legal_articles (id TEXT PRIMARY KEY)")
        connection.execute("CREATE VIRTUAL TABLE legal_articles_fts USING fts5(id)")

    retriever = UniversalLegalRetriever(db_path)
    assert retriever.is_available is False

    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO legal_articles (id) VALUES ('article-1')")

    assert retriever.is_available is True


def test_universal_index_builder_is_importable_without_running_the_cli() -> None:
    builder = importlib.import_module("scripts.build_universal_index")

    assert callable(builder.main)
    assert builder.DB_PATH == ROOT / "data" / "corpus" / "universal_legal" / "universal_legal.db"


def test_universal_index_builder_splits_once_at_each_article_heading() -> None:
    builder = importlib.import_module("scripts.build_universal_index")

    articles = builder._split_legal_articles(
        "Luật thử nghiệm\nĐiều 1. Phạm vi\nNội dung thứ nhất.\nĐiều 2. Áp dụng\nNội dung thứ hai."
    )

    assert len(articles) == 3
    assert articles[1].startswith("Điều 1. Phạm vi")
    assert articles[2].startswith("Điều 2. Áp dụng")


def test_universal_retriever_does_not_return_arbitrary_articles_for_year_discovery() -> None:
    retriever = UniversalLegalRetriever()

    assert retriever.search("2026 có luật gì mới không?", limit=5) == []


def test_universal_retriever_prefers_the_corporate_minimum_shareholder_provision() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    results = retriever.search(
        "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông theo quy định?",
        limit=5,
    )

    assert results
    assert any(
        "Điều 111" in str(item.get("metadata", {}).get("legal_anchor"))
        and "59/2020/QH14" in str(item.get("metadata", {}).get("instrument_number"))
        for item in results
    )


def test_universal_retriever_uses_named_article_anchor_to_find_the_exact_law() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    query = "Điều 41 Bộ luật Lao động 2019 quy định gì?"
    results = retriever.search(query, limit=5, required_anchors=explicit_anchors(query))

    assert len(results) == 1
    metadata = results[0]["metadata"]
    assert metadata["source_article"] == "Điều 41"
    assert metadata["Document_Number"] == "45/2019/QH14"
    assert "Nghĩa vụ của người sử dụng lao động" in metadata["Dieu"]


def test_universal_retriever_scopes_natural_trial_query_to_the_requested_article() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    results = retriever.search(
        "Người lao động có trình độ cao đẳng được thử việc tối đa bao lâu?",
        limit=5,
    )

    assert results
    assert results[0]["metadata"]["source_article"] == "Điều 25"
    assert all(item["metadata"]["topic"] == "Lao động" for item in results)


def test_universal_retriever_scopes_unpaid_wage_query_to_labor_sources() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    results = retriever.search("Người lao động bị nợ lương thì làm gì?", limit=5)

    assert results
    assert all(item["metadata"]["topic"] == "Lao động" for item in results)
    assert any(item["metadata"]["source_article"] in {"Điều 94", "Điều 97"} for item in results)


def test_universal_retriever_targets_employer_duty_for_illegal_termination() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    results = retriever.search(
        "Người sử dụng lao động đơn phương chấm dứt hợp đồng trái pháp luật phải làm gì?",
        limit=5,
    )

    assert results
    assert results[0]["metadata"]["source_article"] == "Điều 41"


def test_universal_retriever_scopes_natural_labor_query_to_relevant_statute() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    results = retriever.search(
        "Người lao động có trình độ cao đẳng được thử việc tối đa bao lâu?",
        limit=5,
    )

    assert results
    assert results[0]["metadata"]["Dieu"].startswith("Điều 25")
    assert all(item["metadata"].get("topic") == "Lao động" for item in results)


def test_universal_retriever_keeps_rare_event_and_outcome_terms_under_query_cap() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    query = "quyền đổi trả hoặc hoàn tiền khi hàng giao bị vỡ hoặc có khuyết tật trong giao dịch từ xa"
    connection = sqlite3.connect(retriever.db_path)
    try:
        terms = retriever._extract_search_terms(query, connection.cursor())
    finally:
        connection.close()

    assert len(terms) <= 12
    assert "vỡ" in terms
    assert "hoàn" in terms or "tiền" in terms
    assert "khuyết" in terms or "tật" in terms


def test_universal_retriever_finds_general_consumer_quality_provision() -> None:
    retriever = UniversalLegalRetriever()
    if not retriever.is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    results = retriever.search(
        "nghĩa vụ bảo đảm chất lượng và xử lý hàng hóa không đúng chất lượng trong giao dịch mua bán hàng hóa",
        limit=10,
    )

    assert any(item["document_id"] == "19/2023/QH15-art-14" for item in results)
