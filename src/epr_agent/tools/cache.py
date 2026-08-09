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
    schema_version: int = 2

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
        if not isinstance(value, dict) or value.get("schema_version") != 2:
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
        )


class LegacySemanticAnswerCache:
    """Adapter around the existing Redis/Qdrant answer cache."""

    async def lookup(self, key: str) -> str | None:
        from backend.cache.semantic_cache import lookup

        return await lookup(key)

    async def store(self, key: str, answer: str) -> None:
        from backend.cache.semantic_cache import store

        await store(key, answer)


class InMemoryAnswerCache:
    """Small deterministic cache used by unit and trajectory tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def lookup(self, key: str) -> str | None:
        return self.values.get(key)

    async def store(self, key: str, answer: str) -> None:
        self.values[key] = answer


class ScopedAnswerCache:
    def __init__(self, backend: AnswerCache, *, corpus_version: str = "epr-corpus-v1") -> None:
        self.backend = backend
        self.corpus_version = corpus_version

    @staticmethod
    def is_cacheable(task_type: str | TaskType) -> bool:
        return TaskType(task_type) == TaskType.LEGAL_LOOKUP

    def build_key(self, task_type: str | TaskType, standalone_query: str) -> str:
        task = TaskType(task_type).value
        normalised = " ".join((standalone_query or "").lower().split())
        digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
        return f"epr:answer:v2:{task}:{self.corpus_version}:{digest}"

    async def lookup(self, task_type: str | TaskType, standalone_query: str) -> tuple[CachedAnswer | None, str]:
        key = self.build_key(task_type, standalone_query)
        if not self.is_cacheable(task_type):
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
    ) -> None:
        if (
            not answer
            or not evidence
            or not citations
            or source not in {"faq", "legal"}
            or not self.is_cacheable(task_type)
        ):
            return
        payload = CachedAnswer(
            answer=answer,
            evidence=evidence,
            citations=citations,
            source=source,
        )
        await self.backend.store(self.build_key(task_type, standalone_query), payload.serialise())
