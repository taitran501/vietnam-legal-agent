from __future__ import annotations

import json

from scripts import build_index


def test_summarise_articles_uses_versioned_cache_without_llm(tmp_path, monkeypatch):
    article = {"Điều": "Điều 1", "Text": "Nội dung quy định đã được chuẩn hóa."}
    cache_path = tmp_path / "summaries.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": build_index._SUMMARY_CACHE_VERSION,
                "entries": {build_index._summary_cache_key(article): "Tóm tắt đã lưu."},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))
    monkeypatch.delenv("SUMMARY_SOURCE_COLLECTION", raising=False)
    monkeypatch.setattr(
        build_index,
        "get_llm_fast",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not run on a full cache hit")),
    )

    assert build_index.summarise_articles([article]) == ["Tóm tắt đã lưu."]


def test_summary_cache_key_changes_with_source_text():
    first = {"Điều": "Điều 1", "Text": "Nội dung thứ nhất."}
    second = {"Điều": "Điều 1", "Text": "Nội dung thứ hai."}

    assert build_index._summary_cache_key(first) != build_index._summary_cache_key(second)
