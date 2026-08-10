"""Evaluate Pipeline V3 retrieval without running answer-generation LLM calls.

The evaluator reads the 60-case V3 retrieval manifest and calls the same
versioned Qdrant dense + lexical + RRF + heuristic-rerank implementation used
by the bounded workflow. It is intentionally a local manual command: it uses
the configured OpenAI embedding profile for query vectors, but does not send
retrieved law text to a generation model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.core.retrieval import retrieve_legal_async

from epr_agent.domain.legal import explicit_anchors
from epr_agent.domain.models import DocumentRecord, TaskType
from epr_agent.evaluation.retrieval_cases import RETRIEVAL_CASES
from epr_agent.tools.evidence import EvidenceEvaluator, legal_relevance_checker

QUALITY_FLOOR = 0.9375


def _article_ids(document: Any) -> set[str]:
    metadata = dict(getattr(document, "metadata", {}) or {})
    fields = [
        str(metadata.get("Dieu") or ""),
        str(metadata.get("Parent_Dieu") or ""),
        str(metadata.get("legal_anchor") or ""),
    ]
    return {anchor.article.casefold() for anchor in explicit_anchors("\n".join(fields)) if anchor.article}


def _unique_article_ranking(documents: list[Any]) -> list[str]:
    ranked: list[str] = []
    for document in documents:
        for article in sorted(_article_ids(document)):
            if article not in ranked:
                ranked.append(article)
    return ranked


def _record(document: Any, index: int) -> DocumentRecord:
    metadata = dict(getattr(document, "metadata", {}) or {})
    document_id = str(metadata.get("document_id") or metadata.get("_id") or f"evaluation-{index}")
    return DocumentRecord(
        content=str(getattr(document, "page_content", "") or ""),
        document_id=document_id,
        source="legal",
        metadata=metadata,
    )


def _binary_ndcg(relevant: set[str], ranked: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    dcg = sum(
        (1.0 / math.log2(position + 2))
        for position, article in enumerate(ranked[:k])
        if article in relevant
    )
    ideal_count = min(k, len(relevant))
    ideal = sum(1.0 / math.log2(position + 2) for position in range(ideal_count))
    return dcg / ideal if ideal else 0.0


async def _evaluate_case(case: dict[str, object], evaluator: EvidenceEvaluator) -> dict[str, object]:
    documents = await retrieve_legal_async(str(case["query"]))
    ranked_articles = _unique_article_ranking(documents)
    expected = {str(article).casefold() for article in case.get("expected_articles", [])}
    top_1 = ranked_articles[:1]
    top_5 = ranked_articles[:5]
    if expected:
        hit_at_1 = bool(expected.intersection(top_1))
        recall_at_5 = len(expected.intersection(top_5)) / len(expected)
        passed = hit_at_1 if len(expected) == 1 else recall_at_5 == 1.0
        return {
            "id": case["id"],
            "kind": "labelled",
            "passed": passed,
            "expected_articles": sorted(expected),
            "ranked_articles": ranked_articles[:10],
            "precision_at_1": 1.0 if hit_at_1 else 0.0,
            "ndcg_at_3": _binary_ndcg(expected, ranked_articles, 3),
            "recall_at_5": recall_at_5,
        }

    records = [_record(document, index) for index, document in enumerate(documents[:3], start=1)]
    assessment = evaluator.evaluate(str(case["query"]), records, TaskType.LEGAL_LOOKUP)
    expects_no_evidence = str(case.get("expected_termination") or "") == "insufficient_evidence"
    passed = (not assessment.sufficient) if expects_no_evidence else assessment.sufficient
    return {
        "id": case["id"],
        "kind": "no_evidence" if expects_no_evidence else "unlabelled_legal",
        "passed": passed,
        "ranked_articles": ranked_articles[:10],
        "evidence_reason": assessment.reason,
        "top_rerank_score": max(
            (float((record.metadata or {}).get("rerank_score") or 0.0) for record in records),
            default=0.0,
        ),
    }


async def evaluate() -> dict[str, object]:
    settings = get_settings()
    evaluator = EvidenceEvaluator(
        min_docs=settings.min_legal_evidence_docs,
        min_chars=settings.min_legal_evidence_chars,
        relevance_checker=legal_relevance_checker(min_rerank_score=settings.min_legal_rerank_score),
    )
    results = [await _evaluate_case(case, evaluator) for case in RETRIEVAL_CASES]
    labelled = [result for result in results if result["kind"] == "labelled"]
    multi = [result for result in labelled if len(result["expected_articles"]) > 1]
    metrics = {
        "precision_at_1": sum(float(result["precision_at_1"]) for result in labelled) / len(labelled),
        "ndcg_at_3": sum(float(result["ndcg_at_3"]) for result in labelled) / len(labelled),
        "recall_at_5": sum(float(result["recall_at_5"]) for result in labelled) / len(labelled),
        "explicit_article_hit_at_1": sum(
            bool(result["passed"]) for result in labelled if len(result["expected_articles"]) == 1
        )
        / max(1, sum(1 for result in labelled if len(result["expected_articles"]) == 1)),
        "multi_anchor_coverage_at_5": sum(float(result["recall_at_5"]) for result in multi) / max(1, len(multi)),
    }
    rounded_metrics = {key: round(value, 4) for key, value in metrics.items()}
    gates = {
        "explicit_article_hit_at_1": metrics["explicit_article_hit_at_1"] == 1.0,
        "multi_anchor_coverage_at_5": metrics["multi_anchor_coverage_at_5"] == 1.0,
        "precision_at_1": metrics["precision_at_1"] >= QUALITY_FLOOR,
        "ndcg_at_3": metrics["ndcg_at_3"] >= QUALITY_FLOOR,
        "recall_at_5": metrics["recall_at_5"] >= QUALITY_FLOOR,
        "all_cases": all(bool(result["passed"]) for result in results),
    }
    return {
        "suite": "pipeline-v3-retrieval",
        "cases": len(results),
        "embedding_profile": settings.embedding_profile,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "metrics": rounded_metrics,
        "gates": gates,
        "failed": [result for result in results if not result["passed"]],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(evaluate())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"results", "failed"}}, ensure_ascii=False, indent=2))
    return 0 if all(bool(value) for value in dict(report["gates"]).values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
