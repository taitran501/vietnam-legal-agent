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
    await cache.store(
        TaskType.LEGAL_LOOKUP,
        "EPR là gì?",
        "Câu trả lời có nguồn [1].",
        evidence=[{"content": "Điều luật", "metadata": {"Dieu": "Điều 77"}, "document_id": "law-77"}],
        citations=[{"index": 1, "document_id": "law-77", "label": "Điều 77"}],
        source="legal",
    )
    value, _ = await cache.lookup(TaskType.LEGAL_LOOKUP, "EPR là gì?")
    assert value is not None
    assert value.answer == "Câu trả lời có nguồn [1]."
    assert value.evidence[0]["document_id"] == "law-77"


@pytest.mark.asyncio
async def test_case_tasks_never_read_or_write_answer_cache():
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(backend)
    value, key = await cache.lookup(TaskType.ASSESS_EPR_OBLIGATION, "case")
    await cache.store(
        TaskType.BUILD_COMPLIANCE_CHECKLIST,
        "case",
        "should not persist",
        evidence=[{"content": "source"}],
        citations=[{"index": 1}],
        source="legal",
    )
    assert value is None
    assert backend.values == {}
    assert "assess_epr_obligation" in key


@pytest.mark.asyncio
async def test_answer_only_legacy_cache_entry_is_ignored():
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(backend)
    key = cache.build_key(TaskType.LEGAL_LOOKUP, "EPR")
    await backend.store(key, "legacy answer without evidence")
    value, _ = await cache.lookup(TaskType.LEGAL_LOOKUP, "EPR")
    assert value is None
