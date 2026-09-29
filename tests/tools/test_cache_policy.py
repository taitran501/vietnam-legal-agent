import pytest

import epr_agent.tools.cache as cache_module
from epr_agent.domain.models import TaskType
from epr_agent.domain.verification import VerificationStatus
from epr_agent.tools.cache import CachedAnswer, InMemoryAnswerCache, ScopedAnswerCache


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
    value, key = await cache.lookup(TaskType.CASE_ASSESSMENT, "case")
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


@pytest.mark.asyncio
async def test_cache_rejects_old_readiness_or_verification_metadata():
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(
        backend,
        corpus_sha="corpus-current",
        legal_readiness_sha="manifest-current",
    )
    key = cache.build_key(TaskType.LEGAL_LOOKUP, "EPR")

    old_readiness = CachedAnswer(
        answer="Theo Điều 77 [1].",
        evidence=[{"content": "Điều 77", "document_id": "law-77"}],
        citations=[{"index": 1}],
        source="legal",
        corpus_sha="corpus-current",
        legal_readiness_sha="manifest-old",
    )
    await backend.store(key, old_readiness.serialise())
    value, _ = await cache.lookup(TaskType.LEGAL_LOOKUP, "EPR")
    assert value is None

    unverifiable = CachedAnswer(
        answer="Theo Điều 77 [1].",
        evidence=[{"content": "Điều 77", "document_id": "law-77"}],
        citations=[{"index": 1}],
        source="legal",
        corpus_sha="corpus-current",
        legal_readiness_sha="manifest-current",
        verification_status=VerificationStatus.UNSUPPORTED_CLAIM,
    )
    await backend.store(key, unverifiable.serialise())
    value, _ = await cache.lookup(TaskType.LEGAL_LOOKUP, "EPR")
    assert value is None


@pytest.mark.asyncio
async def test_cache_key_refresh_makes_previous_readiness_snapshot_a_miss():
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(
        backend,
        corpus_sha="corpus-current",
        legal_readiness_sha="manifest-current",
    )
    await cache.store(
        TaskType.LEGAL_LOOKUP,
        "EPR",
        "Theo Điều 77 [1].",
        evidence=[{"content": "Điều 77", "document_id": "law-77"}],
        citations=[{"index": 1}],
        source="legal",
    )

    cache.update_legal_readiness_sha("manifest-replaced")
    value, new_key = await cache.lookup(TaskType.LEGAL_LOOKUP, "EPR")

    assert value is None
    assert "manifest-replaced" in new_key


@pytest.mark.asyncio
async def test_unavailable_redis_answer_cache_times_out_and_temporarily_fails_open(
    monkeypatch: pytest.MonkeyPatch,
):
    import asyncio

    import epr_agent.infra.session_store

    calls = 0

    async def slow_redis():
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    monkeypatch.setattr(epr_agent.infra.session_store, "get_redis", slow_redis)
    monkeypatch.setattr(cache_module, "_REDIS_CACHE_OPERATION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(cache_module, "_redis_cache_retry_at", 0.0)

    assert await cache_module.RedisExactAnswerCache().lookup("legal:answer:test") is None
    assert calls == 1
    assert cache_module._redis_cache_retry_at > 0

    # The open circuit avoids paying the timeout again on the next cache miss.
    assert await cache_module.RedisExactAnswerCache().lookup("legal:answer:test") is None
    assert calls == 1
