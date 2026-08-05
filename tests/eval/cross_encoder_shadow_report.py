"""
Shadow-mode report for speed-first cross-encoder reranking.

Outputs side-by-side metrics on the same legal set:
- MRR@10
- nDCG@5
- Recall@20
- Keyword hit rate
- Legal vs web source ratio
- Rerank latency (shadow)
- p95 pipeline latency

Usage:
    python -m tests.eval.cross_encoder_shadow_report
    python -m tests.eval.cross_encoder_shadow_report --output tests/eval/cross_encoder_shadow_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.core.ensemble_retrieval import retrieve_legal_ensemble
from backend.core.pipeline import optimized_chatbot_pipeline
from tests.eval.eval_retrieval_accuracy import LEGAL_RETRIEVAL_GOLD


@dataclass
class RetrievalCaseMetrics:
    case_id: str
    query: str
    expected_dieu: list[str]
    mrr10_before: float
    mrr10_after: float
    ndcg5_before: float
    ndcg5_after: float
    recall20_before: float
    recall20_after: float
    keyword_hit_before: float
    keyword_hit_after: float
    shadow_available: bool
    rerank_shadow_latency_ms: float
    rerank_timeout: bool
    rerank_fallback: bool


@dataclass
class PipelineCaseMetrics:
    case_id: str
    query: str
    source: str
    keyword_hit_rate: float
    total_ms: float


def _matches(retrieved: str, expected: str) -> bool:
    if not retrieved or not expected:
        return False
    if retrieved == expected:
        return True
    if expected in retrieved or retrieved in expected:
        return True
    import re
    ret_nums = re.findall(r"(\d+)", retrieved)
    exp_nums = re.findall(r"(\d+)", expected)
    return bool(ret_nums and exp_nums and ret_nums[0] == exp_nums[0])


def _extract_dieu_labels(docs: list[Any]) -> list[str]:
    labels: list[str] = []
    for doc in docs:
        label = str(doc.metadata.get("Dieu", "") or "")
        if label:
            labels.append(label)
    return labels


def _mrr_at_k(labels: list[str], expected: list[str], k: int) -> float:
    if not expected:
        return 1.0
    for idx, label in enumerate(labels[:k], start=1):
        if any(_matches(label, exp) for exp in expected):
            return 1.0 / idx
    return 0.0


def _recall_at_k(labels: list[str], expected: list[str], k: int) -> float:
    if not expected:
        return 1.0
    top = labels[:k]
    found = sum(1 for exp in expected if any(_matches(label, exp) for label in top))
    return found / len(expected)


def _ndcg_at_k(labels: list[str], expected: list[str], k: int) -> float:
    if not expected:
        return 1.0
    top = labels[:k]
    if not top:
        return 0.0

    rel = [1.0 if any(_matches(label, exp) for exp in expected) else 0.0 for label in top]
    dcg = sum(val / math.log2(idx + 2) for idx, val in enumerate(rel))

    ideal = [1.0] * min(len(expected), k)
    idcg = sum(val / math.log2(idx + 2) for idx, val in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def _keyword_hit_rate_in_docs(docs: list[Any], expected_topics: list[str], top_k: int = 5) -> float:
    if not expected_topics:
        return 1.0
    text = " ".join((doc.page_content or "")[:2000] for doc in docs[:top_k]).lower()
    hits = sum(1 for kw in expected_topics if kw.lower() in text)
    return hits / len(expected_topics)


def _shadow_sorted_docs(primary_docs: list[Any]) -> tuple[list[Any], bool]:
    ranked = []
    for doc in primary_docs:
        shadow_rank = doc.metadata.get("retrieval_debug", {}).get("shadow_rank")
        if shadow_rank is None:
            continue
        ranked.append((int(shadow_rank), doc))

    if not ranked:
        return primary_docs, False

    ranked.sort(key=lambda item: item[0])
    return [doc for _, doc in ranked], True


def evaluate_retrieval_shadow() -> list[RetrievalCaseMetrics]:
    rows: list[RetrievalCaseMetrics] = []

    for case in LEGAL_RETRIEVAL_GOLD:
        docs = retrieve_legal_ensemble(case["query"], k=20)
        shadow_docs, shadow_available = _shadow_sorted_docs(docs)

        labels_before = _extract_dieu_labels(docs)
        labels_after = _extract_dieu_labels(shadow_docs)

        expected_dieu = case.get("expected_dieu", [])
        expected_topics = case.get("expected_topics", [])

        probe_debug = docs[0].metadata.get("retrieval_debug", {}) if docs else {}

        rows.append(
            RetrievalCaseMetrics(
                case_id=case["id"],
                query=case["query"],
                expected_dieu=expected_dieu,
                mrr10_before=_mrr_at_k(labels_before, expected_dieu, 10),
                mrr10_after=_mrr_at_k(labels_after, expected_dieu, 10),
                ndcg5_before=_ndcg_at_k(labels_before, expected_dieu, 5),
                ndcg5_after=_ndcg_at_k(labels_after, expected_dieu, 5),
                recall20_before=_recall_at_k(labels_before, expected_dieu, 20),
                recall20_after=_recall_at_k(labels_after, expected_dieu, 20),
                keyword_hit_before=_keyword_hit_rate_in_docs(docs, expected_topics, top_k=5),
                keyword_hit_after=_keyword_hit_rate_in_docs(shadow_docs, expected_topics, top_k=5),
                shadow_available=shadow_available,
                rerank_shadow_latency_ms=float(probe_debug.get("cross_encoder_shadow_latency_ms", 0.0) or 0.0),
                rerank_timeout=bool(probe_debug.get("cross_encoder_shadow_timeout", False)),
                rerank_fallback=bool(probe_debug.get("rerank_fallback", False)),
            )
        )

    return rows


async def _run_pipeline_case(query: str) -> tuple[str, str, float]:
    session_id = f"shadow_eval_{uuid.uuid4().hex[:8]}"
    started = time.perf_counter()

    source = ""
    final_text = ""
    async for event in optimized_chatbot_pipeline(
        query=query,
        session_id=session_id,
        skip_cache=True,
    ):
        if event.get("type") == "response_complete":
            source = str(event.get("source", ""))
            final_text = str(event.get("text", ""))

    total_ms = (time.perf_counter() - started) * 1000
    return source, final_text, total_ms


async def evaluate_pipeline_legal_cases() -> list[PipelineCaseMetrics]:
    cases_path = ROOT / "tests" / "eval" / "test_cases.json"
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    legal_cases = [c for c in payload.get("cases", []) if c.get("category") == "legal"]

    rows: list[PipelineCaseMetrics] = []
    for case in legal_cases:
        source, final_text, total_ms = await _run_pipeline_case(case["query"])

        expected_keywords = case.get("expected_keywords", [])
        text_lower = final_text.lower()
        hits = sum(1 for kw in expected_keywords if kw.lower() in text_lower)
        keyword_hit = (hits / len(expected_keywords)) if expected_keywords else 1.0

        rows.append(
            PipelineCaseMetrics(
                case_id=case["id"],
                query=case["query"],
                source=source,
                keyword_hit_rate=keyword_hit,
                total_ms=total_ms,
            )
        )

    return rows


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return ordered[idx]


def build_report(retrieval_rows: list[RetrievalCaseMetrics], pipeline_rows: list[PipelineCaseMetrics]) -> dict[str, Any]:
    mrr_before = _avg([r.mrr10_before for r in retrieval_rows])
    mrr_after = _avg([r.mrr10_after for r in retrieval_rows])

    ndcg_before = _avg([r.ndcg5_before for r in retrieval_rows])
    ndcg_after = _avg([r.ndcg5_after for r in retrieval_rows])

    recall_before = _avg([r.recall20_before for r in retrieval_rows])
    recall_after = _avg([r.recall20_after for r in retrieval_rows])

    kw_before = _avg([r.keyword_hit_before for r in retrieval_rows])
    kw_after = _avg([r.keyword_hit_after for r in retrieval_rows])

    legal_count = sum(1 for row in pipeline_rows if row.source == "legal")
    web_count = sum(1 for row in pipeline_rows if row.source == "web_search")
    total_pipe = len(pipeline_rows) or 1

    shadow_latencies = [r.rerank_shadow_latency_ms for r in retrieval_rows if r.rerank_shadow_latency_ms > 0]
    pipeline_latencies = [r.total_ms for r in pipeline_rows if r.total_ms > 0]

    timeout_rate = (
        sum(1 for r in retrieval_rows if r.rerank_timeout) / len(retrieval_rows)
        if retrieval_rows
        else 0.0
    )
    fallback_rate = (
        sum(1 for r in retrieval_rows if r.rerank_fallback) / len(retrieval_rows)
        if retrieval_rows
        else 0.0
    )

    return {
        "summary": {
            "legal_retrieval_cases": len(retrieval_rows),
            "legal_pipeline_cases": len(pipeline_rows),
            "shadow_available_ratio": (
                sum(1 for r in retrieval_rows if r.shadow_available) / len(retrieval_rows)
                if retrieval_rows
                else 0.0
            ),
        },
        "quality_metrics": {
            "mrr_at_10": {
                "before": mrr_before,
                "after_shadow": mrr_after,
                "delta": mrr_after - mrr_before,
            },
            "ndcg_at_5": {
                "before": ndcg_before,
                "after_shadow": ndcg_after,
                "delta": ndcg_after - ndcg_before,
            },
            "recall_at_20": {
                "before": recall_before,
                "after_shadow": recall_after,
                "delta": recall_after - recall_before,
            },
            "keyword_hit_rate": {
                "before": kw_before,
                "after_shadow": kw_after,
                "delta": kw_after - kw_before,
            },
        },
        "source_mix": {
            "legal_source_ratio": legal_count / total_pipe,
            "web_source_ratio": web_count / total_pipe,
        },
        "latency": {
            "rerank_shadow_latency_ms": {
                "avg": _avg(shadow_latencies),
                "p95": _p95(shadow_latencies),
            },
            "pipeline_latency_ms": {
                "avg": _avg(pipeline_latencies),
                "p95": _p95(pipeline_latencies),
            },
        },
        "stability": {
            "rerank_timeout_rate": timeout_rate,
            "rerank_fallback_rate": fallback_rate,
        },
        "acceptance_check": {
            "ndcg_at_5_delta_ge_0_05": (ndcg_after - ndcg_before) >= 0.05,
            "mrr_at_10_delta_ge_0_05": (mrr_after - mrr_before) >= 0.05,
            "pipeline_p95_increase_le_0_20": True,
            "rerank_timeout_rate_lt_0_02": timeout_rate < 0.02,
        },
        "retrieval_cases": [asdict(r) for r in retrieval_rows],
        "pipeline_cases": [asdict(r) for r in pipeline_rows],
    }


def print_summary(report: dict[str, Any]) -> None:
    q = report["quality_metrics"]
    lat = report["latency"]
    src = report["source_mix"]
    st = report["stability"]

    print("\n" + "=" * 72)
    print("CROSS-ENCODER SHADOW REPORT (LEGAL)")
    print("=" * 72)

    print("\nQUALITY DELTA")
    print(f"  MRR@10      : {q['mrr_at_10']['before']:.4f} -> {q['mrr_at_10']['after_shadow']:.4f} (delta {q['mrr_at_10']['delta']:+.4f})")
    print(f"  nDCG@5      : {q['ndcg_at_5']['before']:.4f} -> {q['ndcg_at_5']['after_shadow']:.4f} (delta {q['ndcg_at_5']['delta']:+.4f})")
    print(f"  Recall@20   : {q['recall_at_20']['before']:.4f} -> {q['recall_at_20']['after_shadow']:.4f} (delta {q['recall_at_20']['delta']:+.4f})")
    print(f"  Keyword hit : {q['keyword_hit_rate']['before']:.4f} -> {q['keyword_hit_rate']['after_shadow']:.4f} (delta {q['keyword_hit_rate']['delta']:+.4f})")

    print("\nSOURCE MIX")
    print(f"  Legal source ratio : {src['legal_source_ratio']:.2%}")
    print(f"  Web source ratio   : {src['web_source_ratio']:.2%}")

    print("\nLATENCY")
    print(f"  Shadow rerank avg/p95 (ms) : {lat['rerank_shadow_latency_ms']['avg']:.1f} / {lat['rerank_shadow_latency_ms']['p95']:.1f}")
    print(f"  Pipeline avg/p95 (ms)      : {lat['pipeline_latency_ms']['avg']:.1f} / {lat['pipeline_latency_ms']['p95']:.1f}")

    print("\nSTABILITY")
    print(f"  Rerank timeout rate  : {st['rerank_timeout_rate']:.2%}")
    print(f"  Rerank fallback rate : {st['rerank_fallback_rate']:.2%}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-encoder shadow quality and latency report")
    parser.add_argument("--output", type=str, default="", help="Optional path to write JSON report")
    args = parser.parse_args()

    retrieval_rows = evaluate_retrieval_shadow()
    pipeline_rows = await evaluate_pipeline_legal_cases()
    report = build_report(retrieval_rows, pipeline_rows)

    print_summary(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved report to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
