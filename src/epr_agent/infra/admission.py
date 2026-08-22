"""Redis-backed admission leases shared by every backend worker."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

from epr_agent.infra.session_store import get_redis

_ACQUIRE_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[4])
redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[5]) * 2))
return 1
"""

_REFRESH_SCRIPT = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) == false then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[3]) * 2))
return 1
"""


class AdmissionUnavailable(RuntimeError):
    """Raised when Redis cannot make a safe capacity decision."""


@dataclass(frozen=True, slots=True)
class AdmissionLease:
    scope: str
    token: str
    ttl_seconds: float


class RedisAdmissionController:
    """Bound in-flight work with expiring leases and atomic Redis decisions."""

    def __init__(self, *, key_prefix: str = "admission") -> None:
        self.key_prefix = key_prefix

    def _key(self, scope: str) -> str:
        return f"{self.key_prefix}:{scope}"

    async def acquire(
        self,
        scope: str,
        *,
        limit: int,
        wait_seconds: float,
        lease_ttl_seconds: float,
    ) -> AdmissionLease | None:
        if limit < 1 or lease_ttl_seconds <= 0 or wait_seconds < 0:
            raise ValueError("Admission limits and lease TTL must be positive")
        token = str(uuid.uuid4())
        deadline = time.monotonic() + wait_seconds
        try:
            redis = await get_redis()
        except Exception as exc:
            raise AdmissionUnavailable("Redis admission control is unavailable") from exc
        while True:
            now = time.time()
            expires_at = now + lease_ttl_seconds
            try:
                acquired = await cast(
                    Awaitable[Any],
                    redis.eval(
                        _ACQUIRE_SCRIPT,
                        1,
                        self._key(scope),
                        str(now),
                        str(expires_at),
                        str(limit),
                        token,
                        str(lease_ttl_seconds),
                    ),
                )
            except Exception as exc:
                raise AdmissionUnavailable("Redis admission control is unavailable") from exc
            if int(acquired or 0) == 1:
                return AdmissionLease(scope=scope, token=token, ttl_seconds=lease_ttl_seconds)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.05, remaining))

    async def refresh(self, lease: AdmissionLease) -> bool:
        try:
            redis = await get_redis()
            refreshed = await cast(
                Awaitable[Any],
                redis.eval(
                    _REFRESH_SCRIPT,
                    1,
                    self._key(lease.scope),
                    lease.token,
                    str(time.time() + lease.ttl_seconds),
                    str(lease.ttl_seconds),
                ),
            )
        except Exception as exc:
            raise AdmissionUnavailable("Redis admission lease refresh failed") from exc
        return int(refreshed or 0) == 1

    async def release(self, lease: AdmissionLease) -> None:
        try:
            redis = await get_redis()
            await redis.zrem(self._key(lease.scope), lease.token)
        except Exception as exc:
            raise AdmissionUnavailable("Redis admission lease release failed") from exc

    async def heartbeat(self, lease: AdmissionLease, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("Heartbeat interval must be positive")
        while True:
            await asyncio.sleep(interval_seconds)
            if not await self.refresh(lease):
                raise AdmissionUnavailable("Admission lease expired before refresh")


@lru_cache(maxsize=1)
def get_admission_controller() -> RedisAdmissionController:
    return RedisAdmissionController()
