from __future__ import annotations

from collections import defaultdict

import pytest

from epr_agent.infra import admission as admission_module
from epr_agent.infra.admission import (
    AdmissionLease,
    AdmissionUnavailable,
    RedisAdmissionController,
)


class FakeRedis:
    def __init__(self) -> None:
        self.leases: dict[str, dict[str, float]] = defaultdict(dict)

    async def eval(self, script: str, _key_count: int, key: str, *args: str) -> int:
        if "ZREMRANGEBYSCORE" in script:
            now, expires_at, limit, token, _ttl = args
            active = self.leases[key]
            self.leases[key] = {
                lease_token: expiry
                for lease_token, expiry in active.items()
                if expiry > float(now)
            }
            if len(self.leases[key]) >= int(limit):
                return 0
            self.leases[key][token] = float(expires_at)
            return 1

        token, expires_at, _ttl = args
        if token not in self.leases[key]:
            return 0
        self.leases[key][token] = float(expires_at)
        return 1

    async def zrem(self, key: str, token: str) -> int:
        return int(self.leases[key].pop(token, None) is not None)


class BrokenRedis:
    async def eval(self, *_args: object) -> int:
        raise ConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_shared_controllers_enforce_one_deployment_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()

    async def fake_get_redis() -> FakeRedis:
        return redis

    monkeypatch.setattr(admission_module, "get_redis", fake_get_redis)
    first_worker = RedisAdmissionController()
    second_worker = RedisAdmissionController()

    leases = [
        await (first_worker if index % 2 else second_worker).acquire(
            "agent_turns", limit=50, wait_seconds=0, lease_ttl_seconds=300
        )
        for index in range(50)
    ]

    assert all(leases)
    assert await second_worker.acquire(
        "agent_turns", limit=50, wait_seconds=0, lease_ttl_seconds=300
    ) is None

    first_lease = leases[0]
    assert first_lease is not None
    await first_worker.release(first_lease)
    assert await second_worker.acquire(
        "agent_turns", limit=50, wait_seconds=0, lease_ttl_seconds=300
    ) is not None


@pytest.mark.asyncio
async def test_expired_lease_is_pruned_and_capacity_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    current_time = 100.0

    async def fake_get_redis() -> FakeRedis:
        return redis

    monkeypatch.setattr(admission_module, "get_redis", fake_get_redis)
    monkeypatch.setattr(admission_module.time, "time", lambda: current_time)
    controller = RedisAdmissionController()

    assert await controller.acquire(
        "agent_turns", limit=1, wait_seconds=0, lease_ttl_seconds=5
    ) is not None
    assert await controller.acquire(
        "agent_turns", limit=1, wait_seconds=0, lease_ttl_seconds=5
    ) is None

    current_time = 106.0
    assert await controller.acquire(
        "agent_turns", limit=1, wait_seconds=0, lease_ttl_seconds=5
    ) is not None


@pytest.mark.asyncio
async def test_refresh_extends_lease_and_release_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()

    async def fake_get_redis() -> FakeRedis:
        return redis

    monkeypatch.setattr(admission_module, "get_redis", fake_get_redis)
    controller = RedisAdmissionController()
    lease = await controller.acquire(
        "agent_turns", limit=1, wait_seconds=0, lease_ttl_seconds=30
    )

    assert lease is not None
    assert await controller.refresh(lease) is True
    await controller.release(lease)
    await controller.release(lease)
    assert await controller.refresh(lease) is False


@pytest.mark.asyncio
async def test_redis_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_redis() -> BrokenRedis:
        return BrokenRedis()

    monkeypatch.setattr(admission_module, "get_redis", fake_get_redis)

    with pytest.raises(AdmissionUnavailable, match="unavailable"):
        await RedisAdmissionController().acquire(
            "agent_turns", limit=50, wait_seconds=0, lease_ttl_seconds=300
        )


@pytest.mark.asyncio
async def test_redis_initialization_failure_fails_closed_for_every_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_get_redis() -> BrokenRedis:
        raise ConnectionError("redis initialization unavailable")

    monkeypatch.setattr(admission_module, "get_redis", failing_get_redis)
    controller = RedisAdmissionController()
    lease = AdmissionLease(scope="agent_turns", token="lease-1", ttl_seconds=300)

    with pytest.raises(AdmissionUnavailable, match="unavailable"):
        await controller.acquire(
            "agent_turns", limit=50, wait_seconds=0, lease_ttl_seconds=300
        )
    with pytest.raises(AdmissionUnavailable, match="refresh"):
        await controller.refresh(lease)
    with pytest.raises(AdmissionUnavailable, match="release"):
        await controller.release(lease)
