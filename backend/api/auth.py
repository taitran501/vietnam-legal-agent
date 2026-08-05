"""
Authentication middleware for API key validation.

Supports:
- Multiple API keys via comma-separated API_KEYS env var
- Optional auth for development (REQUIRE_AUTH=false)
- Public endpoints (health, metrics) that don't require auth
- Constant-time comparison to prevent timing attacks
- Rate limiting on failed auth attempts
"""

from __future__ import annotations

import hmac
import logging
import time
from typing import Set

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.config import get_settings
from backend.memory.session_store import get_redis

logger = logging.getLogger(__name__)

# Public endpoints that don't require authentication
PUBLIC_ENDPOINTS = {
    "/api/v1/health",
    "/metrics",
    "/",
}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates API keys on incoming requests with constant-time comparison."""

    def __init__(self, app, valid_keys: Set[str] = None):
        super().__init__(app)
        self.valid_keys = valid_keys or set()
        self._failed_attempts = {}  # In-memory rate limiting for failed auths
        self._max_failed_attempts = 10
        self._ban_window = 300  # 5 minutes

    def _is_valid_key(self, api_key: str) -> bool:
        """Validate API key using constant-time comparison to prevent timing attacks.
        
        CRITICAL FIX: Uses hmac.compare_digest() instead of == operator
        to prevent timing-based side-channel attacks.
        """
        for valid_key in self.valid_keys:
            if hmac.compare_digest(api_key, valid_key):
                return True
        return False

    async def _check_rate_limit(self, client_ip: str) -> bool:
        """Check if client has exceeded failed auth attempts."""
        try:
            # Use Redis for distributed rate limiting on failed auths
            redis_client = await get_redis()
            key = f"auth:failed:{client_ip}"
            attempts = await redis_client.get(key)
            attempts = int(attempts) if attempts else 0
            
            if attempts >= self._max_failed_attempts:
                return False  # Rate limited
            
            return True
        except Exception:
            # Fall back to in-memory tracking
            now = time.time()
            if client_ip in self._failed_attempts:
                count, timestamp = self._failed_attempts[client_ip]
                if now - timestamp > self._ban_window:
                    del self._failed_attempts[client_ip]
                elif count >= self._max_failed_attempts:
                    return False
            
            return True

    async def _record_failed_attempt(self, client_ip: str):
        """Record failed authentication attempt."""
        try:
            redis_client = await get_redis()
            key = f"auth:failed:{client_ip}"
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, self._ban_window)
            await pipe.execute()
        except Exception:
            # Fall back to in-memory
            now = time.time()
            if client_ip in self._failed_attempts:
                count, timestamp = self._failed_attempts[client_ip]
                if now - timestamp > self._ban_window:
                    self._failed_attempts[client_ip] = (1, now)
                else:
                    self._failed_attempts[client_ip] = (count + 1, now)
            else:
                self._failed_attempts[client_ip] = (1, now)

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # Skip auth if disabled (for development)
        if not settings.require_auth:
            return await call_next(request)

        # Skip public endpoints
        if request.url.path in PUBLIC_ENDPOINTS:
            return await call_next(request)
        
        # CRITICAL FIX: Disable Swagger/OpenAPI in production
        # These expose full API spec to attackers
        if request.url.path in ["/docs", "/openapi.json", "/redoc"]:
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"},
            )

        # Check rate limiting on failed auths
        client_ip = request.client.host
        if not await self._check_rate_limit(client_ip):
            logger.warning("Auth rate limit exceeded from %s", client_ip)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many failed authentication attempts. Try again later."},
                headers={"Retry-After": str(self._ban_window)},
            )

        # Extract API key from header
        api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")

        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required. Provide X-API-Key header.",
                    "documentation": "Contact administrator to obtain an API key.",
                },
                headers={"WWW-Authenticate": "ApiKey"},
            )

        # CRITICAL FIX: Use constant-time comparison
        if not self._is_valid_key(api_key):
            logger.warning("Invalid API key attempt from %s", client_ip)
            await self._record_failed_attempt(client_ip)
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Invalid API key.",
                },
                headers={"X-RateLimit-Remaining": "0"},
            )

        # Add API key to request state for logging/auditing
        request.state.api_key = api_key
        # Store hash instead of raw key for audit logs
        request.state.api_key_hash = hmac.new(b"audit", api_key.encode(), "sha256").hexdigest()

        return await call_next(request)


def get_valid_api_keys() -> Set[str]:
    """Get set of valid API keys from settings."""
    settings = get_settings()
    if not settings.api_keys:
        return set()
    return {key.strip() for key in settings.api_keys.split(",") if key.strip()}
