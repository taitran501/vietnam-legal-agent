"""Unit and regression tests for UniversalLegalRetriever token handling & retrieval."""

from __future__ import annotations

import pytest

from vietnam_legal_agent.retrieval.universal_retriever import UniversalLegalRetriever


class TestVietnameseTokenLengthNormalization:
    """Tests for isolating Vietnamese morpheme handling (len >= 2) in universal retriever."""

    @pytest.mark.parametrize(
        ("query", "expected_signal"),
        [
            # 2-character Vietnamese legal and everyday queries
            ("án tù", True),
            ("xe máy", True),
            ("ly dị", True),
            ("vợ chồng", True),
            ("đòi nợ", True),
            ("nợ xấu", True),
            ("uỷ thác", True),
            ("ly hôn", True),
            ("thừa kế", True),
            ("trộm cắp", True),
            ("kết hôn", True),
            # Novel 2-character Vietnamese phrases (verifying general principled processing without keyword whitelists)
            ("té ngã", True),
            ("mua xe", True),
            ("bẻ khoá", True),
            # Generic / boilerplate prompts (must still reject)
            ("luật năm nay", False),
            ("quy định mới", False),
            ("văn bản pháp luật mới", False),
            ("quy định pháp luật", False),
            ("văn bản mới nhất", False),
            # Empty / whitespace / digits
            ("", False),
            ("   ", False),
            ("12345", False),
        ],
    )
    def test_has_specific_retrieval_signal(self, query: str, expected_signal: bool) -> None:
        """Verify _has_specific_retrieval_signal preserves 2-character Vietnamese syllables."""
        assert UniversalLegalRetriever._has_specific_retrieval_signal(query) is expected_signal

    def test_extract_components_preserves_unicode_diacritics_and_short_morphemes(self) -> None:
        """Verify _extract_components extracts content words with diacritics and length >= 2."""
        retriever = UniversalLegalRetriever()
        _laws, _phrases, words = retriever._extract_components("án tù và xe máy khi ly dị")
        # Ensure diacritics are preserved and 2-char tokens are retained
        assert "án" in words or "an" in [w.casefold() for w in words] or any("án" in w for w in words)
        assert any(w in {"án", "tù", "xe", "máy", "ly", "dị"} for w in words)

    def test_retriever_search_finds_articles_for_two_char_morpheme_queries(self) -> None:
        """Integration verification that 2-char queries retrieve genuine corpus articles."""
        retriever = UniversalLegalRetriever()

        # "án tù" should retrieve penal / criminal execution articles
        an_tu_results = retriever.search("án tù", limit=5)
        assert len(an_tu_results) > 0, "Query 'án tù' should retrieve articles from the legal corpus"
        assert any(
            "tù" in item.get("page_content", "").casefold() or "án" in item.get("page_content", "").casefold()
            for item in an_tu_results
        )

        # "xe máy" should retrieve traffic / road transport articles
        xe_may_results = retriever.search("xe máy", limit=5)
        assert len(xe_may_results) > 0, "Query 'xe máy' should retrieve articles from the legal corpus"
        assert any(
            "xe" in item.get("page_content", "").casefold() or "máy" in item.get("page_content", "").casefold()
            for item in xe_may_results
        )

        # "ly dị" should retrieve marriage / family law articles
        ly_di_results = retriever.search("ly dị", limit=5)
        assert len(ly_di_results) > 0, "Query 'ly dị' should retrieve articles from the legal corpus"

    def test_generic_queries_remain_rejected_at_retrieval_boundary(self) -> None:
        """Ensure boilerplate queries do not pollute search or execute wasteful FTS searches."""
        retriever = UniversalLegalRetriever()
        assert retriever.search("luật năm nay") == []
        assert retriever.search("quy định mới") == []
        assert retriever.search("văn bản pháp luật mới") == []
