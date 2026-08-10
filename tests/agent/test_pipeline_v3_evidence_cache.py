from __future__ import annotations

import pytest

from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator


def _legal_document(article: str = "Điều 77") -> DocumentRecord:
    return DocumentRecord(
        content=f"{article} quy định trách nhiệm tái chế và các nội dung có liên quan. " * 8,
        document_id=f"law-{article.split()[-1]}",
        source="legal",
        metadata={
            "Dieu": article,
            "legal_anchor": article,
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "epr-law-structure-v3",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
        },
    )


def test_evidence_gate_requires_full_citation_provenance_and_multi_anchor_coverage() -> None:
    evaluator = EvidenceEvaluator(min_chars=20)
    incomplete = _legal_document()
    incomplete.metadata.pop("Corpus_SHA256")

    assert not evaluator.evaluate("Điều 77", [incomplete], "legal_lookup").sufficient
    assert not evaluator.evaluate(
        "So sánh Điều 77 và Điều 78",
        [_legal_document("Điều 77")],
        "legal_lookup",
        expected_articles={"77", "78"},
    ).sufficient
    assert evaluator.evaluate(
        "So sánh Điều 77 và Điều 78",
        [_legal_document("Điều 77"), _legal_document("Điều 78")],
        "legal_lookup",
        expected_articles={"77", "78"},
    ).sufficient


@pytest.mark.asyncio
async def test_cache_key_is_invalidated_by_corpus_identity_and_route_policy() -> None:
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(
        backend,
        corpus_version="epr-law-structure-v3",
        corpus_sha="a" * 64,
        embedding_profile="openai-text-embedding-3-small-v1",
    )
    await cache.store(
        "legal_lookup", "Điều 77 quy định gì?", "Theo Điều 77 [1].",
        evidence=[_legal_document().to_dict()], citations=[{"index": 1}], source="legal", route="legal_lookup",
    )

    hit, _ = await cache.lookup("legal_lookup", "Điều 77 quy định gì?", route="legal_lookup")
    explain, _ = await cache.lookup("legal_lookup", "Điều 77 quy định gì?", route="legal_explain_compare")
    changed = ScopedAnswerCache(backend, corpus_version="epr-law-structure-v3", corpus_sha="b" * 64)
    changed_hit, _ = await changed.lookup("legal_lookup", "Điều 77 quy định gì?", route="legal_lookup")

    assert hit is not None
    assert explain is None
    assert changed_hit is None


@pytest.mark.asyncio
async def test_exact_legal_cache_never_reuses_another_article_answer() -> None:
    backend = InMemoryAnswerCache()
    cache = ScopedAnswerCache(backend, corpus_version="epr-law-structure-v3", corpus_sha="a" * 64)
    await cache.store(
        "legal_lookup",
        "Điều 77 quy định gì?",
        "Theo Điều 77 [1].",
        evidence=[_legal_document("Điều 77").to_dict()],
        citations=[{"index": 1}],
        source="legal",
    )

    article_77, _ = await cache.lookup("legal_lookup", "Điều 77 quy định gì?")
    article_78, _ = await cache.lookup("legal_lookup", "Điều 78 quy định gì?")

    assert article_77 is not None
    assert article_78 is None
