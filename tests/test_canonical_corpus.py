from __future__ import annotations

from scripts import build_index
from scripts.canonical_corpus import canonical_articles, canonical_chunks, corpus_sha256, explicit_anchors


def test_canonical_articles_exclude_untraceable_appendix_summaries():
    articles, audit = canonical_articles()

    assert articles
    assert audit.excluded_records > 0
    assert all(article["Pages"] for article in articles)
    assert all(article["Source_File"] == "data/08_2022_ND-CP_479457.doc" for article in articles)


def test_canonical_chunks_keep_offsets_and_deterministic_retrieval_text():
    articles, _ = canonical_articles()
    normalized, _ = build_index.normalise_articles(articles[:2])
    chunked, _, _ = build_index.chunk_articles(normalized, [""] * len(normalized))
    chunks, audit = canonical_chunks(chunked)

    assert chunks
    assert audit.invalid_offsets == 0
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all("Văn bản:" in chunk.retrieval_text for chunk in chunks)
    assert all("Tóm tắt:" not in chunk.retrieval_text for chunk in chunks)
    assert all(chunk.lexical_text for chunk in chunks)


def test_corpus_hash_and_multi_article_parser_are_stable():
    assert corpus_sha256() == corpus_sha256()
    anchors = explicit_anchors("So sánh Điều 77 Khoản 2 Điểm a, Điều 78 và điều 77.")
    assert [item.article for item in anchors] == ["Điều 77", "Điều 78"]
    assert anchors[0].clause == "Khoản 2"
    assert anchors[0].point == "Điểm a"
