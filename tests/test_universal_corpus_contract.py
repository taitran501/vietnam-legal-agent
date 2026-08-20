"""Contract tests for the generated universal legal corpus artifact."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from epr_agent.retrieval.universal_retriever import DEFAULT_DB_PATH, UniversalLegalRetriever

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
    assert len(downloaded_inputs) == 7
    assert len(tracked_inputs) == 1
    assert sum(int(item["rows"]) for item in inputs) == 66285
    for item in inputs:
        assert len(item["sha256"]) == 64
        assert int(item["size_bytes"]) > 0
        assert int(item["rows"]) > 0

    assert output["path"] == "data/corpus/universal_legal/universal_legal.db"
    assert output["expected_tables"] == ["legal_articles", "legal_articles_fts"]
    assert output["expected_rows"] == 84938


def test_universal_retriever_default_path_is_repository_root_relative(monkeypatch) -> None:
    monkeypatch.delenv("UNIVERSAL_CORPUS_DB_PATH", raising=False)

    retriever = UniversalLegalRetriever()

    assert DEFAULT_DB_PATH == ROOT / "data" / "corpus" / "universal_legal" / "universal_legal.db"
    assert retriever.db_path == DEFAULT_DB_PATH


def test_universal_index_builder_is_importable_without_running_the_cli() -> None:
    builder = importlib.import_module("scripts.build_universal_index")

    assert callable(builder.main)
    assert builder.DB_PATH == ROOT / "data" / "corpus" / "universal_legal" / "universal_legal.db"
