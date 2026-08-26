"""Executable CLI Benchmark Harness for evaluating Vietnam Legal Agent with RAGAS metrics.

Usage:
    python scripts/run_legal_ragas_harness.py [--limit N] [--output-dir DIR] [--pass-gate 0.80]

Computes:
- Mean Faithfulness (Độ trung thực)
- Mean Answer Relevance (Độ trúng đích)
- Mean Context Recall (Độ bao phủ căn cứ luật)
- Mean Context Precision (Độ chính xác tài liệu)
- Mean Statutory Anchor Accuracy (Độ chuẩn xác số Điều/Khoản)
- Quality Gate Pass Rate (% ca vượt ngưỡng)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Add project root and src to path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from epr_agent.agent.agent_loop import EprAgentRunner
from epr_agent.eval.ragas_evaluator import (
    RagasSampleResult,
    evaluate_ragas_sample,
    unavailable_ragas_result,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def run_benchmark(
    benchmark_file: Path,
    limit: int | None = None,
    output_dir: Path | None = None,
    pass_gate: float = 0.80,
) -> dict:
    """Run RAGAS evaluation over the benchmark dataset."""
    if not benchmark_file.exists():
        raise FileNotFoundError(f"Benchmark file not found: {benchmark_file}")

    data = json.loads(await asyncio.to_thread(benchmark_file.read_text, encoding="utf-8"))

    cases = data.get("cases", [])
    if limit:
        cases = cases[:limit]

    logger.info("Starting RAGAS Legal Benchmark with %d cases...", len(cases))
    runner = EprAgentRunner()

    results: list[RagasSampleResult] = []
    start_time = time.time()

    for idx, case in enumerate(cases, start=1):
        case_id = case.get("id", f"case_{idx}")
        query = case["query"]
        expected_anchors = case.get("expected_anchors", [])

        logger.info("[%d/%d] Evaluating %s: %s", idx, len(cases), case_id, query[:60])

        try:
            # Execute through autonomous agent runner
            agent_result = await runner.run(query=query)
            retrieved_docs = [
                {"page_content": d.get("excerpt", ""), "metadata": d.get("metadata", {})}
                for d in agent_result.evidence
            ]

            # Compute RAGAS metric bundle
            eval_result = await evaluate_ragas_sample(
                query=query,
                answer=agent_result.answer,
                retrieved_docs=retrieved_docs,
                expected_anchors=expected_anchors,
                sample_id=case_id,
                pass_threshold=pass_gate,
            )
            results.append(eval_result)

            status_icon = "✅ PASS" if eval_result.passed_gate else "❌ FAIL"
            logger.info(
                "    -> %s (Score: %.2f | Faith: %.2f | Rel: %.2f | Recall: %.2f)",
                status_icon,
                eval_result.overall_ragas_score,
                eval_result.faithfulness,
                eval_result.answer_relevance,
                eval_result.context_recall,
            )
        except Exception as exc:  # noqa: BLE001 - preserve a failed case in the aggregate report
            logger.error("Error evaluating %s: %s", case_id, exc)
            # Create failed placeholder
            results.append(
                unavailable_ragas_result(
                    sample_id=case_id,
                    query=query,
                    details={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
            )

    elapsed = time.time() - start_time
    total = len(results)
    passed_count = sum(1 for r in results if r.passed_gate)

    avg_faithfulness = sum(r.faithfulness for r in results) / total if total else 0.0
    avg_relevance = sum(r.answer_relevance for r in results) / total if total else 0.0
    avg_precision = sum(r.context_precision for r in results) / total if total else 0.0
    avg_recall = sum(r.context_recall for r in results) / total if total else 0.0
    avg_anchor = sum(r.anchor_accuracy for r in results) / total if total else 0.0
    avg_overall = sum(r.overall_ragas_score for r in results) / total if total else 0.0
    pass_rate = (passed_count / total) * 100 if total else 0.0
    evaluator_statuses = sorted({r.evaluator_status for r in results})
    evaluator_unavailable_cases = sum(
        r.evaluator_status != "ok" for r in results
    )

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_cases": total,
        "passed_cases": passed_count,
        "pass_rate_pct": round(pass_rate, 2),
        "duration_seconds": round(elapsed, 2),
        "metrics": {
            "mean_faithfulness": round(avg_faithfulness, 3),
            "mean_answer_relevance": round(avg_relevance, 3),
            "mean_context_precision": round(avg_precision, 3),
            "mean_context_recall": round(avg_recall, 3),
            "mean_anchor_accuracy": round(avg_anchor, 3),
            "mean_overall_ragas": round(avg_overall, 3),
        },
        "gate_threshold": pass_gate,
        "evaluator_statuses": evaluator_statuses,
        "evaluator_unavailable_cases": evaluator_unavailable_cases,
        "results": [r.model_dump(mode="json") for r in results],
    }

    # Output reports
    out_dir = output_dir or (_ROOT / "data" / "eval" / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / f"ragas_report_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    report_text = json.dumps(summary, ensure_ascii=False, indent=2)
    await asyncio.to_thread(report_file.write_text, report_text, encoding="utf-8")

    logger.info("=" * 60)
    logger.info("RAGAS EVALUATION SUMMARY")
    logger.info("Total Cases: %d | Passed: %d (%.1f%%)", total, passed_count, pass_rate)
    logger.info("Mean Faithfulness      : %.3f", avg_faithfulness)
    logger.info("Mean Answer Relevance  : %.3f", avg_relevance)
    logger.info("Mean Context Recall    : %.3f", avg_recall)
    logger.info("Mean Context Precision : %.3f", avg_precision)
    logger.info("Mean Anchor Accuracy   : %.3f", avg_anchor)
    logger.info("Overall RAGAS Score    : %.3f", avg_overall)
    logger.info("Report saved to: %s", report_file)
    logger.info("=" * 60)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Vietnamese Legal RAGAS Benchmark Harness")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of benchmark cases to run")
    parser.add_argument("--pass-gate", type=float, default=0.80, help="Pass gate threshold (default 0.80)")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory to save JSON reports")
    parser.add_argument(
        "--benchmark-file",
        type=str,
        default=str(_ROOT / "data" / "eval" / "golden_legal_benchmark.json"),
        help="Path to golden benchmark JSON",
    )
    args = parser.parse_args()

    asyncio.run(
        run_benchmark(
            benchmark_file=Path(args.benchmark_file),
            limit=args.limit,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            pass_gate=args.pass_gate,
        )
    )


if __name__ == "__main__":
    main()
