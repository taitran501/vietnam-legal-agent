"""
Tests for semantic cache layer.

Tests cover:
- Query normalization
- Exact cache key generation
- Answer validation (error patterns, length)
- LRU tracking
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.cache.semantic_cache import (
    _normalise,
    _exact_key,
    _validate_answer,
    _ERROR_PATTERNS,
)


class TestQueryNormalization:
    """Test query normalization for cache lookups."""

    def test_lowercase_conversion(self):
        """Should convert to lowercase."""
        assert _normalise("Hello World") == "hello world"

    def test_whitespace_normalization(self):
        """Should normalize whitespace."""
        assert _normalise("  hello   world  ") == "hello world"

    def test_combined_normalization(self):
        """Should combine lowercase and whitespace normalization."""
        assert _normalise("  HELLO   WORLD  ") == "hello world"


class TestExactCacheKey:
    """Test exact cache key generation."""

    def test_deterministic_keys(self):
        """Same query should produce same key."""
        key1 = _exact_key("test query")
        key2 = _exact_key("test query")
        assert key1 == key2

    def test_different_keys_for_different_queries(self):
        """Different queries should produce different keys."""
        key1 = _exact_key("query one")
        key2 = _exact_key("query two")
        assert key1 != key2

    def test_case_insensitive_keys(self):
        """Queries differing only in case should produce same key."""
        key1 = _exact_key("Test Query")
        key2 = _exact_key("test query")
        assert key1 == key2

    def test_whitespace_insensitive_keys(self):
        """Queries differing only in whitespace should produce same key."""
        key1 = _exact_key("  test   query  ")
        key2 = _exact_key("test query")
        assert key1 == key2

    def test_key_prefix(self):
        """Key should start with 'cache:exact:'."""
        key = _exact_key("test")
        assert key.startswith("cache:exact:")


class TestAnswerValidation:
    """Test answer validation before caching."""

    def test_valid_answer(self):
        """Valid answer should pass validation."""
        assert _validate_answer("This is a valid answer about EPR") is True

    def test_empty_answer_rejected(self):
        """Empty answer should be rejected."""
        assert _validate_answer("") is False
        assert _validate_answer(None) is False

    def test_whitespace_only_rejected(self):
        """Whitespace-only answer should be rejected."""
        assert _validate_answer("   ") is False

    def test_too_short_answer_rejected(self):
        """Answer shorter than min_length should be rejected."""
        assert _validate_answer("Short", min_length=20) is False

    def test_error_patterns_rejected(self):
        """Answers with error patterns should be rejected."""
        error_answers = [
            "Xin lỗi, tôi không thể giúp bạn",
            "Không tìm thấy thông tin",
            "Tôi không thể trả lời câu này",
            "Có lỗi xảy ra trong quá trình xử lý",
            "Internal server error occurred",
            "⚠️ Cảnh báo: Không thể kết nối",
            "Cannot process your request",
            "Unable to find the information",
        ]

        for answer in error_answers:
            assert _validate_answer(answer) is False, f"Should reject: {answer}"

    def test_valid_answer_with_some_keywords(self):
        """Answer containing some keywords but still valid should pass."""
        # "là" is a common Vietnamese word, shouldn't trigger error
        assert _validate_answer("EPR là trách nhiệm mở rộng của nhà sản xuất") is True

    def test_custom_min_length(self):
        """Should respect custom min_length."""
        short = "12345678901234567890"  # 20 chars
        assert _validate_answer(short, min_length=21) is False
        assert _validate_answer(short, min_length=20) is True


class TestCacheIntegration:
    """Test cache integration (mocked)."""

    @pytest.mark.asyncio
    async def test_lookup_miss_returns_none(self):
        """Cache miss should return None."""
        from backend.cache import semantic_cache

        with patch.object(semantic_cache, '_exact_get', return_value=None):
            with patch.object(semantic_cache, '_semantic_get', return_value=None):
                result = await semantic_cache.lookup("nonexistent query")
                assert result is None

    @pytest.mark.asyncio
    async def test_store_valid_answer(self):
        """Valid answer should be stored."""
        from backend.cache import semantic_cache

        with patch.object(semantic_cache, '_exact_set') as mock_exact:
            with patch.object(semantic_cache, '_semantic_set') as mock_semantic:
                # Use a longer answer to pass validation (min_length=20)
                await semantic_cache.store("test query", "This is a valid answer about EPR regulations")
                mock_exact.assert_called_once()
                mock_semantic.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_invalid_answer_skipped(self):
        """Invalid answer should not be stored."""
        from backend.cache import semantic_cache

        with patch.object(semantic_cache, '_exact_set') as mock_exact:
            with patch.object(semantic_cache, '_semantic_set') as mock_semantic:
                await semantic_cache.store("test query", "xin lỗi")
                # Should not be called for invalid answers
                mock_exact.assert_not_called()
                mock_semantic.assert_not_called()
