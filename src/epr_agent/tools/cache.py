"""Task-scoped answer cache policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from epr_agent.domain.models import TaskType


class AnswerCache(Protocol):
    async def lookup(self, key: str) -> str | None: ...

    async def store(self, key: str, answer: str) -> None: ...


@dataclass(slots=True)
class CachedAnswer:
    """Verified answer bundle stored by the scoped cache.

    Keeping evidence beside the answer prevents a cache hit from returning
    legal prose with citation markers but no source documents.  Old
    answer-only cache entries are intentionally ignored after the format bump.
    """

    answer: str
    evidence: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    source: str
    corpus_id: str = "epr"
    schema_version: int = 3

    def serialise(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def parse(cls, raw: str | None) -> CachedAnswer | None:
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("schema_version") != 3:
            return None
        answer = str(value.get("answer") or "").strip()
        evidence = value.get("evidence")
        citations = value.get("citations")
        source = str(value.get("source") or "")
        if not answer or not isinstance(evidence, list) or not evidence or not isinstance(citations, list):
            return None
        return cls(
            answer=answer,
            evidence=[dict(item) for item in evidence if isinstance(item, dict)],
            citations=[dict(item) for item in citations if isinstance(item, dict)],
            source=source,
            corpus_id=str(value.get("corpus_id") or "epr"),
        )


class RedisExactAnswerCache:
    """V3 answer cache with an exact, corpus-scoped Redis key.

    The legacy semantic cache was built for generic chat answers.  Similar
    legal questions such as ``Điều 77`` and ``Điều 78`` can have highly similar
    embeddings but require different evidence, so V3 deliberately never calls
    it.  ``ScopedAnswerCache.build_key`` already includes the normalized-query
    digest and corpus identity; Redis is only the durable TTL store.
    """

    async def lookup(self, key: str) -> str | None:
        from backend.memory.session_store import get_redis

        try:
            value = await (await get_redis()).get(key)
        except Exception:  # noqa: BLE001 - cache degradation is always a miss
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value) if value is not None else None

    async def store(self, key: str, answer: str) -> None:
        from backend.config import get_settings
        from backend.memory.session_store import get_redis

        try:
            await (await get_redis()).set(key, answer, ex=get_settings().cache_ttl_seconds)
        except Exception:  # noqa: BLE001 - cache writes must never fail a run
            return


class InMemoryAnswerCache:
    """Small deterministic cache used by unit and trajectory tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def lookup(self, key: str) -> str | None:
        return self.values.get(key)

    async def store(self, key: str, answer: str) -> None:
        self.values[key] = answer


class ScopedAnswerCache:
    def __init__(
        self,
        backend: AnswerCache,
        *,
        corpus_id: str = "epr",
        corpus_version: str = "epr-corpus-v1",
        corpus_sha: str = "",
        embedding_profile: str = "openai-text-embedding-3-small-v1",
        policy_version: str = "legal-only-v3-exact",
    ) -> None:
        self.backend = backend
        self.corpus_id = corpus_id
        self.corpus_version = corpus_version
        self.corpus_sha = corpus_sha
        self.embedding_profile = embedding_profile
        self.policy_version = policy_version

    @staticmethod
    def is_cacheable(task_type: str | TaskType, *, route: str = "legal_lookup") -> bool:
        """Only independent legal lookup answers may be reused.

        The legacy task type alone is insufficient because explain, web, and
        case routes share it for API compatibility but must never share a
        cached answer.
        """

        return TaskType(task_type) == TaskType.LEGAL_LOOKUP and route == "legal_lookup"

    def build_key(self, task_type: str | TaskType, standalone_query: str, *, route: str = "legal_lookup") -> str:
        task = TaskType(task_type).value
        normalised = " ".join((standalone_query or "").lower().split())
        digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
        return (
            f"legal:answer:v3:{self.policy_version}:{self.corpus_id}:{self.corpus_version}:"
            f"{self.corpus_sha}:{self.embedding_profile}:{route}:{task}:{digest}"
        )

    async def lookup(
        self, task_type: str | TaskType, standalone_query: str, *, route: str = "legal_lookup"
    ) -> tuple[CachedAnswer | None, str]:
        key = self.build_key(task_type, standalone_query, route=route)
        if not self.is_cacheable(task_type, route=route):
            return None, key
        return CachedAnswer.parse(await self.backend.lookup(key)), key

    async def store(
        self,
        task_type: str | TaskType,
        standalone_query: str,
        answer: str,
        *,
        evidence: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        source: str,
        route: str = "legal_lookup",
    ) -> None:
        if (
            not answer
            or not evidence
            or not citations
            or source != "legal"
            or not self.is_cacheable(task_type, route=route)
        ):
            return
        payload = CachedAnswer(
            answer=answer,
            evidence=evidence,
            citations=citations,
            source=source,
            corpus_id=self.corpus_id,
        )
        await self.backend.store(self.build_key(task_type, standalone_query, route=route), payload.serialise())
