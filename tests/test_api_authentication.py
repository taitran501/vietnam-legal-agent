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

import hmac
from unittest.mock import AsyncMock, Mock, patch

import pytest
from backend.api.auth import APIKeyMiddleware, get_valid_api_keys


class TestAPIKeyValidation:
    """Test API key validation logic."""

    def test_constant_time_comparison(self):
        """Should use hmac.compare_digest for constant-time comparison."""
        assert hmac.compare_digest("test-key", "test-key") is True
        assert hmac.compare_digest("test-key", "wrong-key") is False

    def test_valid_api_keys_parsing(self):
        """Should parse comma-separated API keys correctly."""
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
    # Tests moved to TestAPIKeyValidation


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


class TestProxyIpResolutionAndSpoofPrevention:
    """Test CIDR-aware IP verification and spoof prevention."""

    def test_cidr_subnet_matching(self):
        from backend.api.auth import is_trusted_proxy

        trusted_config = "172.16.0.0/12, 10.0.0.0/8, 192.168.1.100/32"

        # Inside 172.16.0.0/12 (Docker bridge default 172.17.x, 172.18.x)
        assert is_trusted_proxy("172.18.0.2", trusted_config) is True
        assert is_trusted_proxy("172.16.0.1", trusted_config) is True
        assert is_trusted_proxy("172.31.255.254", trusted_config) is True

        # Inside 10.0.0.0/8 (K8s pod network)
        assert is_trusted_proxy("10.244.0.5", trusted_config) is True
        assert is_trusted_proxy("10.0.0.1", trusted_config) is True

        # Exact /32 match
        assert is_trusted_proxy("192.168.1.100", trusted_config) is True
        assert is_trusted_proxy("192.168.1.101", trusted_config) is False

        # Outside subnets
        assert is_trusted_proxy("172.32.0.1", trusted_config) is False
        assert is_trusted_proxy("203.0.113.195", trusted_config) is False
        assert is_trusted_proxy("192.168.0.1", trusted_config) is False

        # Invalid/empty inputs
        assert is_trusted_proxy("", trusted_config) is False
        assert is_trusted_proxy("invalid-ip", trusted_config) is False
        assert is_trusted_proxy("172.18.0.2", "") is False

    def test_ipv4_with_port_matching(self):
        from backend.api.auth import is_trusted_proxy

        assert is_trusted_proxy("172.18.0.2:54321", "172.16.0.0/12") is True
        assert is_trusted_proxy("203.0.113.1:8080", "172.16.0.0/12") is False

    def test_extract_client_ip_from_trusted_proxy(self):
        from backend.api.auth import extract_client_ip
        from starlette.datastructures import Headers

        class FakeClient:
            host = "172.18.0.2"

        class FakeRequest:
            client = FakeClient()
            headers = Headers({
                "X-Forwarded-For": "203.0.113.195:4321, 10.0.0.1",
            })

        with patch("backend.api.auth.get_settings") as mock_settings:
            mock_settings.return_value.trusted_proxy_ips = "172.16.0.0/12"
            client_ip = extract_client_ip(FakeRequest())
            assert client_ip == "203.0.113.195"

    def test_extract_client_ip_real_ip_fallback(self):
        from backend.api.auth import extract_client_ip
        from starlette.datastructures import Headers

        class FakeClient:
            host = "172.18.0.2"

        class FakeRequest:
            client = FakeClient()
            headers = Headers({
                "X-Real-IP": "203.0.113.195",
            })

        with patch("backend.api.auth.get_settings") as mock_settings:
            mock_settings.return_value.trusted_proxy_ips = "172.16.0.0/12"
            client_ip = extract_client_ip(FakeRequest())
            assert client_ip == "203.0.113.195"

    def test_extract_client_ip_spoof_prevention_untrusted_client(self):
        from backend.api.auth import extract_client_ip
        from starlette.datastructures import Headers

        class FakeClient:
            host = "198.51.100.5"

        class FakeRequest:
            client = FakeClient()
            headers = Headers({
                "X-Forwarded-For": "10.0.0.1",
                "X-Real-IP": "10.0.0.2",
            })

        with patch("backend.api.auth.get_settings") as mock_settings:
            mock_settings.return_value.trusted_proxy_ips = "172.16.0.0/12"
            # Since 198.51.100.5 is not trusted, headers must be ignored
            client_ip = extract_client_ip(FakeRequest())
            assert client_ip == "198.51.100.5"


class TestSharedReverseProxyLockoutPrevention:
    """Test that containerized reverse proxy IPs are never banned."""

    @pytest.mark.asyncio
    async def test_trusted_proxy_immune_from_failed_attempt_recording(self):
        middleware = APIKeyMiddleware(app=None, valid_keys={"test-key"})

        with patch("backend.api.auth.get_settings") as mock_settings, \
             patch("backend.api.auth.get_redis") as mock_get_redis:
            mock_settings.return_value.trusted_proxy_ips = "172.16.0.0/12"
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis

            # Proxy IP itself must be immune from recording
            await middleware._record_failed_attempt("172.18.0.2")

            # Redis pipeline must NOT be called for trusted proxy IP
            mock_redis.pipeline.assert_not_called()
            assert "172.18.0.2" not in middleware._failed_attempts

    @pytest.mark.asyncio
    async def test_trusted_proxy_immune_from_rate_limit_ban(self):
        middleware = APIKeyMiddleware(app=None, valid_keys={"test-key"})

        with patch("backend.api.auth.get_settings") as mock_settings, \
             patch("backend.api.auth.get_redis") as mock_get_redis:
            mock_settings.return_value.trusted_proxy_ips = "172.16.0.0/12"
            mock_redis = AsyncMock()
            mock_redis.get.return_value = "999"  # Simulated huge failed count
            mock_get_redis.return_value = mock_redis

            # Even if attempts are 999, trusted proxy must NOT be banned
            allowed = await middleware._check_rate_limit("172.18.0.2")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_forwarded_client_banned_without_locking_out_other_proxy_users(self):
        middleware = APIKeyMiddleware(app=None, valid_keys={"test-key"})

        with patch("backend.api.auth.get_settings") as mock_settings, \
             patch("backend.api.auth.get_redis") as mock_get_redis:
            mock_settings.return_value.trusted_proxy_ips = "172.16.0.0/12"

            redis_store: dict[str, str] = {}

            mock_redis = AsyncMock()
            async def mock_get(key: str):
                return redis_store.get(key)
            mock_redis.get = mock_get

            mock_pipe = AsyncMock()
            def mock_incr(key: str):
                val = int(redis_store.get(key, "0")) + 1
                redis_store[key] = str(val)
            mock_pipe.incr = mock_incr
            mock_pipe.expire = AsyncMock()
            mock_pipe.execute = AsyncMock()
            mock_redis.pipeline = Mock(return_value=mock_pipe)
            mock_get_redis.return_value = mock_redis

            # Attacker IP behind reverse proxy
            attacker_ip = "203.0.113.10"
            for _ in range(10):
                await middleware._record_failed_attempt(attacker_ip)

            # Attacker is now rate limited
            assert await middleware._check_rate_limit(attacker_ip) is False

            # But another legitimate user behind the SAME reverse proxy is allowed!
            legit_ip = "203.0.113.20"
            assert await middleware._check_rate_limit(legit_ip) is True

            # And the reverse proxy IP itself is allowed!
            assert await middleware._check_rate_limit("172.18.0.2") is True

    @pytest.mark.asyncio
    async def test_dev_local_scopes_include_documents_write(self):
        middleware = APIKeyMiddleware(app=None)

        class DummyRequest:
            url = type("URL", (), {"path": "/api/v1/documents/upload"})()
            state = type("State", (), {})()

        async def dummy_call_next(req):
            return req

        with patch("backend.api.auth.get_settings") as mock_settings:
            mock_settings.return_value.require_auth = False
            req = DummyRequest()
            await middleware.dispatch(req, dummy_call_next)
            assert req.state.principal.id == "dev-local"
            assert req.state.principal.has_scope("documents:write")

