"""
Quick latency probe for legal hybrid retrieval.

Usage:
    python -m tests.eval.retrieval_latency
    python -m tests.eval.retrieval_latency --repeat 3
    python -m tests.eval.retrieval_latency --query "Điều 77 quy định gì?"
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.retrieval import retrieve_legal  # noqa: E402


DEFAULT_QUERIES = [
    "giờ tui nhập khẩu hàng hóa có chứa chất ô nhiễm khó phân hủy thì có cần làm thủ tục gì trước khi bán ra thị trường k",
    "Điều 77 quy định gì về trách nhiệm tái chế?",
    "Tỷ lệ tái chế bắt buộc đối với sản phẩm bao bì được quy định ở đâu?",
    "Công ty tôi nhập khẩu pin lithium từ nước ngoài, chúng tôi phải thực hiện nghĩa vụ gì?",
]


def _fmt(ms: float) -> str:
    return f"{ms:.1f}ms"


def run_one(query: str) -> dict:
    started = time.perf_counter()
    docs = retrieve_legal(query)
    end_to_end_ms = (time.perf_counter() - started) * 1000

    stage = {}
    if docs:
        stage = docs[0].metadata.get("retrieval_debug", {}).get("latency_ms", {}) or {}

    return {
        "query": query,
        "docs": docs,
        "end_to_end_ms": end_to_end_ms,
        "stage_ms": stage,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure legal retrieval latency.")
    parser.add_argument("--query", action="append", help="One or more queries to run")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat each query N times")
    args = parser.parse_args()

    queries = args.query or DEFAULT_QUERIES
    repeat = max(1, args.repeat)
    totals: list[float] = []

    for query in queries:
        print(f"\n=== {query}")
        for i in range(repeat):
            result = run_one(query)
            totals.append(result["end_to_end_ms"])
            stage = result["stage_ms"]
            top = ""
            if result["docs"]:
                top = str(result["docs"][0].metadata.get("Dieu", ""))[:90]
            print(
                f"run#{i+1}: e2e={_fmt(result['end_to_end_ms'])} "
                f"semantic={_fmt(float(stage.get('semantic', 0.0)))} "
                f"lexical={_fmt(float(stage.get('lexical', 0.0)))} "
                f"parse={_fmt(float(stage.get('parse', 0.0)))} "
                f"explicit={_fmt(float(stage.get('explicit', 0.0)))} "
                f"rerank={_fmt(float(stage.get('rerank_merge', 0.0)))} "
                f"total={_fmt(float(stage.get('total', 0.0)))} "
                f"top1={top}"
            )

    if totals:
        mean = statistics.mean(totals)
        median = statistics.median(totals)
        p95 = sorted(totals)[max(0, int(len(totals) * 0.95) - 1)]
        print(
            f"\nSummary: runs={len(totals)} "
            f"mean={_fmt(mean)} median={_fmt(median)} p95={_fmt(p95)}"
        )


if __name__ == "__main__":
    main()
