"""Authenticated-principal contracts and OIDC/service-token validation.

The API uses one typed identity at every route boundary.  Legacy API keys are
accepted only as a compatibility bridge; they are never exposed as an owner
identifier and browser clients do not receive them from the frontend build.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from epr_agent.config import get_settings

logger = logging.getLogger(__name__)


class AuthenticationError(ValueError):
    """Raised when a presented credential cannot be trusted."""


@dataclass(frozen=True, slots=True)
class Principal:
    id: str
    type: str
    roles: frozenset[str] = field(default_factory=frozenset)
    scopes: frozenset[str] = field(default_factory=frozenset)
    issuer: str | None = None
    subject: str | None = None
    display_name: str = ""
    email: str | None = None

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def oidc_user_id(issuer: str, subject: str) -> str:
    canonical_issuer = issuer.rstrip("/")
    digest = hashlib.sha256(f"{canonical_issuer}\x00{subject}".encode()).hexdigest()
    return f"oidc:{digest}"


def credential_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalise_set(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset(item for item in value.replace(",", " ").split() if item)
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(item) for item in value if str(item))
    return frozenset()


def _service_principals() -> dict[str, Principal]:
    """Parse hashed service-token definitions without retaining raw tokens."""

    definitions = get_settings().service_token_definitions
    result: dict[str, Principal] = {}
    for raw in definitions.split(","):
        parts = [item.strip() for item in raw.split(":", 3)]
        if len(parts) != 4:
            continue
        name, token_hash, scopes_text, roles_text = parts
        if len(token_hash) != 64 or any(character not in "0123456789abcdefABCDEF" for character in token_hash):
            logger.warning("Ignoring malformed service-token hash for %s", name)
            continue
        result[token_hash.lower()] = Principal(
            id=f"service:{name}",
            type="service",
            scopes=_normalise_set(scopes_text.replace("|", " ")),
            roles=_normalise_set(roles_text.replace("|", " ")),
            display_name=name,
        )
    return result


def principal_from_service_token(token: str) -> Principal | None:
    token_hash = credential_hash(token).lower()
    for configured_hash, principal in _service_principals().items():
        if hmac.compare_digest(token_hash, configured_hash):
            return principal
    return None


def principal_from_legacy_api_key(api_key: str) -> Principal:
    settings = get_settings()
    digest = hmac.new(
        settings.legacy_hmac_key.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return Principal(id=f"legacy:{digest}", type="legacy_api_key", scopes=frozenset({"chat"}))


_metadata_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _fetch_json(url: str) -> dict[str, Any]:
    request = URLRequest(url, headers={"Accept": "application/json", "User-Agent": "vietnam-legal-agent/1.0"})
    with urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise AuthenticationError("OIDC metadata is not an object")
    return payload


async def _cached_json(cache: dict[str, tuple[float, dict[str, Any]]], url: str, ttl: int) -> dict[str, Any]:
    now = time.monotonic()
    cached = cache.get(url)
    if cached and cached[0] > now:
        return cached[1]
    payload = await asyncio.to_thread(_fetch_json, url)
    cache[url] = (now + ttl, payload)
    return payload


async def validate_oidc_token(token: str) -> Principal:
    settings = get_settings()
    if not settings.oidc_issuer or not settings.oidc_audience:
        raise AuthenticationError("OIDC is not configured")
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dependency is installed in production
        raise AuthenticationError("OIDC JWT support is not installed") from exc

    issuer = settings.oidc_issuer.rstrip("/")
    discovery = await _cached_json(
        _metadata_cache,
        f"{issuer}/.well-known/openid-configuration",
        settings.oidc_jwks_cache_seconds,
    )
    jwks_uri = str(discovery.get("jwks_uri") or "")
    if not jwks_uri:
        raise AuthenticationError("OIDC discovery did not provide jwks_uri")
    jwks = await _cached_json(_jwks_cache, jwks_uri, settings.oidc_jwks_cache_seconds)
    header = jwt.get_unverified_header(token)
    algorithm = str(header.get("alg") or "")
    allowed_algorithms = [item.strip() for item in settings.oidc_allowed_algorithms.split(",") if item.strip()]
    if algorithm not in allowed_algorithms:
        raise AuthenticationError("OIDC signing algorithm is not allowed")
    key_id = header.get("kid")
    keys = jwks.get("keys") or []
    key_payload = next((item for item in keys if not key_id or item.get("kid") == key_id), None)
    if not isinstance(key_payload, dict):
        raise AuthenticationError("OIDC signing key was not found")
    try:
        algorithm_impl = jwt.algorithms.get_default_algorithms().get(algorithm)
        if algorithm_impl is None or not hasattr(algorithm_impl, "from_jwk"):
            raise AuthenticationError("OIDC signing algorithm cannot load JWKS keys")
        signing_key = algorithm_impl.from_jwk(json.dumps(key_payload))
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=allowed_algorithms,
            audience=settings.oidc_audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except Exception as exc:
        raise AuthenticationError("OIDC token validation failed") from exc

    subject = str(claims.get("sub") or "")
    if not subject:
        raise AuthenticationError("OIDC token has no subject")
    groups = set(_normalise_set(claims.get("groups")))
    groups.update(_normalise_set(claims.get("roles")))
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        groups.update(_normalise_set(realm_access.get("roles")))
    required_group = settings.oidc_required_group
    if required_group and required_group not in groups:
        raise AuthenticationError("OIDC token is not in the required internal group")
    display_name = str(claims.get("name") or claims.get("preferred_username") or claims.get("email") or subject)
    return Principal(
        id=oidc_user_id(issuer, subject),
        type="oidc",
        roles=frozenset(groups),
        scopes=_normalise_set(claims.get("scope")),
        issuer=issuer,
        subject=subject,
        display_name=display_name,
        email=str(claims.get("email")) if claims.get("email") else None,
    )


def principal_from_request_state(request: Any) -> Principal:
    principal = getattr(getattr(request, "state", None), "principal", None)
    if isinstance(principal, Principal):
        return principal
    legacy_id = getattr(getattr(request, "state", None), "api_key_hash", None)
    if legacy_id:
        return Principal(id=str(legacy_id), type="legacy_api_key", scopes=frozenset({"chat", "feedback"}))
    # Local disabled-auth mode is intentionally explicit and isolated.
    return Principal(id="dev-local", type="local", scopes=frozenset({"chat", "feedback"}))
