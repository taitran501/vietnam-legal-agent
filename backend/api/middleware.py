"""
Rate limiting middleware for FastAPI.

Implements distributed rate limiting using Redis for multi-worker support.
Supports:
- Per-client rate limiting (by API key or IP)
- Configurable requests per minute/hour
- Graceful degradation when Redis is unavailable
- Distributed token bucket algorithm
"""

from __future__ import annotations

import hashlib
import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.config import get_settings
from backend.memory.session_store import get_redis

logger = logging.getLogger(__name__)


class RateLimiter:
    """Distributed rate limiter using Redis."""
    
    def __init__(
        self,
        rpm: int = 60,        # Requests per minute
        rph: int = 1000,      # Requests per hour
        burst: int = 10,      # Burst allowance
    ):
        self.rpm = rpm
        self.rph = rph
        self.burst = burst
    
    async def is_allowed(self, client_id: str) -> tuple[bool, dict[str, str]]:
        """
        Check if request is allowed for the given client using Redis.
        
        Uses atomic Redis INCR with EXPIRE for distributed counting.
        Works correctly across multiple workers/processes.
        
        Returns:
            (is_allowed, headers_dict)
        """
        try:
            import redis.asyncio as aioredis
            redis_client: aioredis.Redis = await get_redis()
            now = time.time()
            
            # Minute window key
            minute_window = int(now) // 60
            minute_key = f"ratelimit:{client_id}:m:{minute_window}"
            
            # Hour window key  
            hour_window = int(now) // 3600
            hour_key = f"ratelimit:{client_id}:h:{hour_window}"
            
            # Use Redis pipeline for atomic operations
            pipe = redis_client.pipeline()
            pipe.incr(minute_key)
            pipe.expire(minute_key, 120)  # Keep for 2 minutes
            pipe.incr(hour_key)
            pipe.expire(hour_key, 7200)   # Keep for 2 hours
            results = await pipe.execute()
            
            minute_count = results[0]
            hour_count = results[2]
            
            # Calculate headers
            headers = {
                "X-RateLimit-Limit": str(self.rpm),
                "X-RateLimit-Remaining": str(max(0, self.rpm + self.burst - minute_count)),
                "X-RateLimit-Reset": str((minute_window + 1) * 60),
            }
            
            # Check limits (with burst allowance for minute)
            if minute_count > self.rpm + self.burst:
                headers["Retry-After"] = str(60 - (int(now) % 60))
                return False, headers
            
            if hour_count > self.rph:
                headers["Retry-After"] = str(3600 - (int(now) % 3600))
                return False, headers
            
            return True, headers
            
        except Exception as exc:  # noqa: BLE001 - rate limiting deliberately fails open during Redis outages
            logger.warning("Rate limiter check failed: %s", exc)
            # Fail-open: allow request if Redis is unavailable
            return True, {}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces distributed rate limits."""
    
    def __init__(self, app, limiter: RateLimiter | None = None):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health checks and public endpoints
        if request.url.path in ["/api/v1/health", "/api/v1/ready", "/internal/metrics", "/docs", "/openapi.json", "/redoc", "/"]:
            return await call_next(request)
        
        # Extract client identifier (prefer API key, fall back to IP)
        client_id = self._get_client_id(request)
        
        # Check rate limit
        allowed, headers = await self.limiter.is_allowed(client_id)
        
        if not allowed:
            from starlette.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
                headers=headers,
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers to response
        for key, value in headers.items():
            response.headers[key] = value
        
        return response
    
    @staticmethod
    def _get_client_id(request: Request) -> str:
        """Extract unique client identifier for rate limiting."""
        principal = getattr(request.state, "principal", None)
        if principal is not None and getattr(principal, "id", None):
            return f"principal:{principal.id}"

        # Before authentication runs, use only a digest of a presented
        # credential.  Raw API keys must never enter Redis keys or logs.
        credential = (
            request.headers.get("X-Service-Token")
            or request.headers.get("X-API-Key")
            or request.headers.get("Authorization")
        )
        if credential:
            return f"credential:{hashlib.sha256(credential.encode('utf-8')).hexdigest()}"

        settings = get_settings()
        client_host = request.client.host if request.client else "unknown"
        trusted = {
            value.strip()
            for value in str(getattr(settings, "trusted_proxy_ips", "") or "").split(",")
            if value.strip()
        }
        if client_host in trusted:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return f"ip:{forwarded.split(',')[0].strip()}"
        return f"ip:{client_host}"
