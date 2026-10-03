"""
Compare retrieval quality/latency across multiple law collections.

Usage:
    python -m tests.eval.benchmark_collections
    python -m tests.eval.benchmark_collections --collections law_collection,law_collection_doc_v2
    python -m tests.eval.benchmark_collections --output artifacts/collection_benchmark.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class GoldenCase:
    query: str
    expect_any: tuple[str, ...]


_golden_benchmark = json.loads(
    (ROOT / "data" / "eval" / "golden_legal_benchmark.json").read_text(encoding="utf-8")
)
GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase(
        query=str(case["query"]),
        expect_any=tuple(str(anchor).casefold() for anchor in case.get("expected_anchors", [])),
    )
    for case in _golden_benchmark.get("cases", [])
    if case.get("query") and case.get("expected_anchors")
]

@dataclass
class QueryRow:
    query: str
    top1_hit: bool
    top3_hit: bool
    latency_ms: float
    docs_count: int
    top_dieu: str
    top_source: str


@dataclass
class CollectionScore:
    collection: str
    queries: int
    top1_pass: int
    top3_pass: int
    top1_rate: float
    top3_rate: float
    latency_avg_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    rows: list[QueryRow]


def _iter_collections(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


async def _run_one(collection: str) -> CollectionScore:
    os.environ["LAW_COLLECTION"] = collection
    # Import after LAW_COLLECTION override so settings picks current collection.
    from vietnam_legal_agent.retrieval.retrieval import retrieve_legal_async  # noqa: WPS433

    await retrieve_legal_async(GOLDEN_CASES[0].query)

    latencies: list[float] = []
    rows: list[QueryRow] = []

    for case in GOLDEN_CASES:
        started = time.perf_counter()
        docs = await retrieve_legal_async(case.query)
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)

        top_texts = [
            ((d.metadata.get("Dieu", "") + " " + (d.page_content or "")).lower())
            for d in docs[:3]
        ]
        top1_hit = bool(top_texts) and any(token in top_texts[0] for token in case.expect_any)
        top3_hit = any(any(token in txt for token in case.expect_any) for txt in top_texts)

        rows.append(
            QueryRow(
                query=case.query,
                top1_hit=top1_hit,
                top3_hit=top3_hit,
                latency_ms=round(latency, 2),
                docs_count=len(docs),
                top_dieu=(docs[0].metadata.get("Dieu", "") if docs else ""),
                top_source=(docs[0].metadata.get("retrieval_source", "") if docs else ""),
            )
        )

    top1_pass = sum(1 for r in rows if r.top1_hit)
    top3_pass = sum(1 for r in rows if r.top3_hit)
    p95_idx = max(0, int(0.95 * (len(latencies) - 1)))

    return CollectionScore(
        collection=collection,
        queries=len(GOLDEN_CASES),
        top1_pass=top1_pass,
        top3_pass=top3_pass,
        top1_rate=round(top1_pass / len(GOLDEN_CASES), 3),
        top3_rate=round(top3_pass / len(GOLDEN_CASES), 3),
        latency_avg_ms=round(statistics.mean(latencies), 2),
        latency_p95_ms=round(sorted(latencies)[p95_idx], 2),
        latency_max_ms=round(max(latencies), 2),
        rows=rows,
    )


def _print_summary(scores: Iterable[CollectionScore]) -> None:
    print("\nCollection Benchmark")
    print("-" * 92)
    print(f"{'Collection':<28} {'Top1':>8} {'Top3':>8} {'Avg(ms)':>10} {'P95(ms)':>10} {'Max(ms)':>10}")
    print("-" * 92)
    for s in scores:
        print(
            f"{s.collection:<28} "
            f"{s.top1_rate:>8.3f} "
            f"{s.top3_rate:>8.3f} "
            f"{s.latency_avg_ms:>10.2f} "
            f"{s.latency_p95_ms:>10.2f} "
            f"{s.latency_max_ms:>10.2f}"
        )
    print("-" * 92)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark retrieval quality/latency by collection.")
    parser.add_argument(
        "--collections",
        default="law_collection,law_collection_doc_v1,law_collection_doc_v2",
        help="Comma-separated collection names.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/collection_benchmark.json",
        help="JSON output path.",
    )
    args = parser.parse_args()

    collections = _iter_collections(args.collections)
    if not collections:
        raise ValueError("No valid collection names provided.")

    scores: list[CollectionScore] = []
    for collection in collections:
        print(f"[benchmark] running collection={collection}")
        score = await _run_one(collection)
        scores.append(score)

    _print_summary(scores)

    output_path = (ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(s) for s in scores], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[benchmark] report_saved={output_path}")


if __name__ == "__main__":
    asyncio.run(_main())
