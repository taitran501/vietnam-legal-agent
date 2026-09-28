"""Task-scoped answer cache policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from epr_agent.domain.models import TaskType
from epr_agent.domain.verification import VerificationStatus

_CACHE_SCHEMA_VERSION = 4
_VERIFICATION_POLICY_VERSION = "legal-verification-v1"


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
    corpus_sha: str = ""
    verification_policy_version: str = _VERIFICATION_POLICY_VERSION
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    schema_version: int = _CACHE_SCHEMA_VERSION
    legal_readiness_sha: str = ""

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
        if not isinstance(value, dict) or value.get("schema_version") != _CACHE_SCHEMA_VERSION:
            return None
        if not all(
            field in value
            for field in (
                "corpus_sha",
                "legal_readiness_sha",
                "verification_policy_version",
                "verification_status",
            )
        ):
            return None
        answer = str(value.get("answer") or "").strip()
        evidence = value.get("evidence")
        citations = value.get("citations")
        source = str(value.get("source") or "")
        try:
            verification_status = VerificationStatus(str(value.get("verification_status") or ""))
        except ValueError:
            return None
        if verification_status is not VerificationStatus.VERIFIED:
            return None
        verification_policy_version = str(value.get("verification_policy_version") or "")
        if not verification_policy_version:
            return None
        if not answer or not isinstance(evidence, list) or not evidence or not isinstance(citations, list):
            return None
        if not all(isinstance(item, dict) for item in evidence) or not all(isinstance(item, dict) for item in citations):
            return None
        return cls(
            answer=answer,
            evidence=[dict(item) for item in evidence],
            citations=[dict(item) for item in citations],
            source=source,
            corpus_id=str(value.get("corpus_id") or "epr"),
            corpus_sha=str(value.get("corpus_sha") or ""),
            verification_policy_version=verification_policy_version,
            verification_status=verification_status,
            legal_readiness_sha=str(value.get("legal_readiness_sha") or ""),
        )


class RedisExactAnswerCache:
    """V3 answer cache with an exact, corpus-scoped Redis key.

    A former generic semantic cache could treat questions about ``Điều 77``
    and ``Điều 78`` as equivalent despite their different evidence. V3 uses
    only the exact normalized-query digest and corpus identity; Redis is the
    durable TTL store.
    """

    async def lookup(self, key: str) -> str | None:
        from epr_agent.infra.session_store import get_redis

        try:
            value = await (await get_redis()).get(key)
        except Exception:  # noqa: BLE001 - cache degradation is always a miss
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value) if value is not None else None

    async def store(self, key: str, answer: str) -> None:
        from epr_agent.config import get_settings
        from epr_agent.infra.session_store import get_redis

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
        policy_version: str = _VERIFICATION_POLICY_VERSION,
        legal_readiness_sha: str = "",
    ) -> None:
        self.backend = backend
        self.corpus_id = corpus_id
        self.corpus_version = corpus_version
        self.corpus_sha = corpus_sha
        self.embedding_profile = embedding_profile
        self.policy_version = policy_version
        self.legal_readiness_sha = legal_readiness_sha

    def update_legal_readiness_sha(self, legal_readiness_sha: str) -> None:
        """Refresh the readiness snapshot used by subsequent cache keys.

        The manifest is an independently mutable review artifact. Production
        processes may stay alive while that artifact is replaced, so keeping
        the value captured at process construction would allow a cache lookup
        to use an obsolete readiness snapshot. Callers refresh this value
        immediately before legal cache access.
        """

        self.legal_readiness_sha = legal_readiness_sha

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
            f"legal:answer:v4:{self.policy_version}:{self.corpus_id}:{self.corpus_version}:"
            f"{self.corpus_sha}:{self.legal_readiness_sha}:{self.embedding_profile}:{route}:{task}:{digest}"
        )

    async def lookup(
        self, task_type: str | TaskType, standalone_query: str, *, route: str = "legal_lookup"
    ) -> tuple[CachedAnswer | None, str]:
        key = self.build_key(task_type, standalone_query, route=route)
        if not self.is_cacheable(task_type, route=route):
            return None, key
        value = CachedAnswer.parse(await self.backend.lookup(key))
        if value is not None and (
            value.source != "legal"
            or value.corpus_id != self.corpus_id
            or value.corpus_sha != self.corpus_sha
            or value.verification_policy_version != self.policy_version
            or value.verification_status is not VerificationStatus.VERIFIED
            or value.legal_readiness_sha != self.legal_readiness_sha
        ):
            return None, key
        return value, key

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
            corpus_sha=self.corpus_sha,
            verification_policy_version=self.policy_version,
            verification_status=VerificationStatus.VERIFIED,
            legal_readiness_sha=self.legal_readiness_sha,
        )
        await self.backend.store(self.build_key(task_type, standalone_query, route=route), payload.serialise())
