"""Task-scoped answer cache policy."""

from __future__ import annotations

import hashlib
from typing import Protocol

from epr_agent.domain.models import TaskType


class AnswerCache(Protocol):
    async def lookup(self, key: str) -> str | None: ...

    async def store(self, key: str, answer: str) -> None: ...


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
        return f"epr:answer:{task}:{self.corpus_version}:{digest}"

    async def lookup(self, task_type: str | TaskType, standalone_query: str) -> tuple[str | None, str]:
        key = self.build_key(task_type, standalone_query)
        if not self.is_cacheable(task_type):
            return None, key
        return await self.backend.lookup(key), key

    async def store(self, task_type: str | TaskType, standalone_query: str, answer: str) -> None:
        if not answer or not self.is_cacheable(task_type):
            return
        await self.backend.store(self.build_key(task_type, standalone_query), answer)
