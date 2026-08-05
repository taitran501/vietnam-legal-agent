import pytest

from epr_agent.domain.models import TaskType
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache


@pytest.mark.asyncio
async def test_cache_key_contains_task_query_and_corpus_version():
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(backend, corpus_version="law-v2")
    key = cache.build_key(TaskType.LEGAL_LOOKUP, "  EPR là gì? ")
    assert "legal_lookup" in key
    assert "law-v2" in key
    await backend.store(key, "answer")
    value, _ = await cache.lookup(TaskType.LEGAL_LOOKUP, "EPR là gì?")
    assert value == "answer"


@pytest.mark.asyncio
async def test_case_tasks_never_read_or_write_answer_cache():
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(backend)
    value, key = await cache.lookup(TaskType.ASSESS_EPR_OBLIGATION, "case")
    await cache.store(TaskType.BUILD_COMPLIANCE_CHECKLIST, "case", "should not persist")
    assert value is None
    assert backend.values == {}
    assert "assess_epr_obligation" in key
