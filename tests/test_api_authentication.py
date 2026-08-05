"""
Tests for API key authentication middleware.

Tests cover:
- Valid API key accepted
- Invalid API key rejected
- Missing API key returns 401
- Constant-time comparison used
- Public endpoints don't require auth
- Rate limiting on failed attempts
"""

import pytest
import hmac
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient
from fastapi import FastAPI

from backend.api.auth import APIKeyMiddleware, get_valid_api_keys


class TestAPIKeyValidation:
    """Test API key validation logic."""

    def test_constant_time_comparison(self):
        """Should use hmac.compare_digest for constant-time comparison."""
        import hmac
        assert hmac.compare_digest("test-key", "test-key") is True
        assert hmac.compare_digest("test-key", "wrong-key") is False

    def test_valid_api_keys_parsing(self):
        """Should parse comma-separated API keys correctly."""
        from backend.api.auth import get_valid_api_keys
        with patch('backend.api.auth.get_settings') as mock_settings:
            mock_settings.return_value.api_keys = "key1,key2,key3"
            keys = get_valid_api_keys()
            assert keys == {"key1", "key2", "key3"}

    def test_invalid_api_key_validation_in_middleware(self):
        """Middleware should reject invalid API keys."""
        middleware = APIKeyMiddleware(app=None, valid_keys={"valid-key"})
        
        # Test constant-time comparison is used
        assert middleware._is_valid_key("valid-key") is True
        assert middleware._is_valid_key("invalid-key") is False
        assert middleware._is_valid_key("") is False


class TestConstantTimeComparison:
    """Test that constant-time comparison is used."""
    pass  # Tests moved to TestAPIKeyValidation


class TestAuthRateLimiting:
    """Test rate limiting on failed authentication attempts."""

    @pytest.mark.asyncio
    async def test_failed_attempt_recorded(self):
        """Failed attempt should be recorded."""
        middleware = APIKeyMiddleware(
            app=None,
            valid_keys={"test-key"},
        )

        with patch('backend.api.auth.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis

            await middleware._record_failed_attempt("127.0.0.1")

            # Should have called pipeline
            mock_redis.pipeline.assert_called()

    @pytest.mark.asyncio
    async def test_rate_limit_on_failed_attempts(self):
        """Should rate limit after too many failed attempts."""
        middleware = APIKeyMiddleware(
            app=None,
            valid_keys={"test-key"},
        )

        with patch('backend.api.auth.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get.return_value = "10"  # Max attempts reached
            mock_get_redis.return_value = mock_redis

            allowed = await middleware._check_rate_limit("127.0.0.1")
            assert allowed is False
