"""Authentication middleware for OIDC principals and service credentials.

Legacy API keys remain available only as a short compatibility bridge for
existing non-browser callers and tests.  Routes receive a typed principal and
never use a raw credential as an owner or rate-limit identifier.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import time
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.api.principal import (
    AuthenticationError,
    Principal,
    principal_from_legacy_api_key,
    principal_from_service_token,
    validate_oidc_token,
)
from vietnam_legal_agent.config import get_settings
from vietnam_legal_agent.infra.session_store import get_redis

logger = logging.getLogger(__name__)

PUBLIC_ENDPOINTS = {
    "/api/v1/health",
    "/api/v1/ready",
    "/",
}


def _parse_network(item: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    cleaned = item.strip()
    if not cleaned:
        return None
    try:
        return ipaddress.ip_network(cleaned, strict=False)
    except ValueError:
        return None


def is_trusted_proxy(client_host: str, trusted_proxies_config: Any = None) -> bool:
    """Check whether client_host matches any IP or CIDR subnet in trusted_proxies_config."""
    if not client_host:
        return False
    if trusted_proxies_config is None:
        trusted_proxies_config = getattr(get_settings(), "trusted_proxy_ips", "") or ""
    if not trusted_proxies_config:
        return False

    cleaned_host = client_host.strip()
    if cleaned_host.count(":") == 1:
        # Strip port from IPv4 host:port
        cleaned_host = cleaned_host.split(":")[0].strip()

    try:
        client_ip_obj = ipaddress.ip_address(cleaned_host)
    except ValueError:
        return False

    if isinstance(trusted_proxies_config, (list, tuple, set, frozenset)):
        raw_items = list(trusted_proxies_config)
    elif isinstance(trusted_proxies_config, str):
        raw_items = trusted_proxies_config.split(",")
    else:
        raw_items = [str(trusted_proxies_config)]

    for raw in raw_items:
        net = _parse_network(str(raw))
        if net is not None and client_ip_obj.version == net.version and client_ip_obj in net:
            return True
    return False


def extract_client_ip(request: Request, settings: Any = None) -> str:
    """Extract real client IP, honoring X-Forwarded-For or X-Real-IP only if proxy is trusted.

    Prevents IP spoofing when request does not come from a trusted proxy.
    """
    if settings is None:
        settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    if client_host != "unknown" and client_host.count(":") == 1:
        client_host = client_host.split(":")[0].strip()

    trusted_config = getattr(settings, "trusted_proxy_ips", "") or ""

    if is_trusted_proxy(client_host, trusted_config):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            first_ip = forwarded.split(",")[0].strip()
            if first_ip.count(":") == 1:
                first_ip = first_ip.split(":")[0].strip()
            if first_ip:
                return first_ip
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            if real_ip.count(":") == 1:
                real_ip = real_ip.split(":")[0].strip()
            if real_ip:
                return real_ip

    return client_host


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Resolve OIDC, service-token, and legacy test principals."""

    def __init__(self, app, valid_keys: set[str] | None = None):
        super().__init__(app)
        self.valid_keys = valid_keys or set()
        self._failed_attempts: dict[str, tuple[int, float]] = {}
        self._max_failed_attempts = 10
        self._ban_window = 300

    def _is_valid_key(self, api_key: str) -> bool:
        return any(hmac.compare_digest(api_key, valid_key) for valid_key in self.valid_keys)

    async def _check_rate_limit(self, client_ip: str) -> bool:
        settings = get_settings()
        if is_trusted_proxy(client_ip, getattr(settings, "trusted_proxy_ips", "")):
            return True
        try:
            redis_client = await get_redis()
            attempts = await redis_client.get(f"auth:failed:{client_ip}")
            return (int(attempts) if attempts else 0) < self._max_failed_attempts
        except Exception:  # noqa: BLE001 - auth keeps a local fallback
            now = time.time()
            current = self._failed_attempts.get(client_ip)
            if current:
                count, timestamp = current
                if now - timestamp <= self._ban_window and count >= self._max_failed_attempts:
                    return False
                if now - timestamp > self._ban_window:
                    self._failed_attempts.pop(client_ip, None)
            return True

    async def _record_failed_attempt(self, client_ip: str) -> None:
        settings = get_settings()
        if is_trusted_proxy(client_ip, getattr(settings, "trusted_proxy_ips", "")):
            return
        try:
            redis_client = await get_redis()
            pipe = redis_client.pipeline()
            pipe.incr(f"auth:failed:{client_ip}")
            pipe.expire(f"auth:failed:{client_ip}", self._ban_window)
            await pipe.execute()
        except Exception:  # noqa: BLE001 - auth keeps a local fallback
            now = time.time()
            count, timestamp = self._failed_attempts.get(client_ip, (0, now))
            self._failed_attempts[client_ip] = (count + 1 if now - timestamp <= self._ban_window else 1, now)

    @staticmethod
    def _client_ip(request: Request, settings: Any = None) -> str:
        return extract_client_ip(request, settings)

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not settings.require_auth:
            request.state.principal = Principal(
                id="dev-local",
                type="local",
                scopes=frozenset({"chat", "feedback", "quality_admin", "ops", "documents:write"}),
            )
            request.state.api_key_hash = "dev-local"
            return await call_next(request)

        if request.url.path in PUBLIC_ENDPOINTS:
            return await call_next(request)
        if request.url.path in {"/docs", "/openapi.json", "/redoc"}:
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        client_ip = self._client_ip(request, settings)
        if not await self._check_rate_limit(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many failed authentication attempts. Try again later."},
                headers={"Retry-After": str(self._ban_window)},
            )

        service_token = request.headers.get("X-Service-Token", "")
        authorization = request.headers.get("Authorization", "")
        bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        api_key = request.headers.get("X-API-Key", "")
        principal: Principal | None = None

        if service_token:
            principal = principal_from_service_token(service_token)
        elif bearer and settings.oidc_issuer:
            try:
                principal = await validate_oidc_token(bearer)
            except AuthenticationError as exc:
                logger.info("OIDC authentication failed from %s: %s", client_ip, exc)
        elif api_key or bearer:
            # Compatibility only.  Browser clients are configured for OIDC and
            # do not ship VITE_API_KEY anymore.
            candidate = api_key or bearer
            if self._is_valid_key(candidate):
                principal = principal_from_legacy_api_key(candidate)

        if principal is None:
            await self._record_failed_attempt(client_ip)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required or credential is invalid."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        if service_token and not principal.scopes:
            return JSONResponse(status_code=403, content={"detail": "Service token has no configured scope."})

        request.state.principal = principal
        request.state.api_key_hash = principal.id
        request.state.api_key = None
        return await call_next(request)


def get_valid_api_keys() -> set[str]:
    """Return legacy compatibility keys from settings."""

    settings = get_settings()
    return {key.strip() for key in settings.api_keys.split(",") if key.strip()}
