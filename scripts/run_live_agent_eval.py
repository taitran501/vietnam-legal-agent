"""Run the checked-in legal benchmark through the live autonomous runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from epr_agent.agent.graph import default_dependencies
from epr_agent.agent.runtime import AgentWorkflowRuntime
from epr_agent.eval.ragas_evaluator import evaluate_ragas_sample

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "data" / "eval" / "golden_legal_benchmark.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "live_agent_eval.json"


def _documents_for_evaluator(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "page_content": str(document.get("content") or document.get("page_content") or ""),
            "metadata": dict(document.get("metadata") or {}),
        }
        for document in documents
    ]


async def _run_case(runtime: AgentWorkflowRuntime, case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case["id"])
    query = str(case["query"])
    started = time.perf_counter()
    terminal: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = []

    async for event in runtime.stream(
        query=query,
        user_id="live-eval",
        conversation_id=f"live-eval-{case_id.lower()}",
        turn_id=f"live-eval-{uuid.uuid4()}",
        mode="auto",
        operation="message",
        trace_id=str(uuid.uuid4()),
    ):
        if event.get("type") in {"response_complete", "response_stopped"}:
            terminal = event
        elif event.get("type") == "error":
            errors.append(event)

    answer = str((terminal or {}).get("text") or "")
    documents = list((terminal or {}).get("documents") or [])
    source_drawer = list((terminal or {}).get("sources") or [])
    trace_id = str((terminal or {}).get("trace_id") or "")
    provider_status = "ok" if terminal is not None and not errors else "provider_unavailable"
    source_payload_status = (
        "ok"
        if source_drawer
        else "not_applicable"
        if not documents
        else "missing"
    )
    evaluation = await evaluate_ragas_sample(
        query=query,
        answer=answer,
        retrieved_docs=_documents_for_evaluator(documents),
        expected_anchors=list(case.get("expected_anchors") or []),
        sample_id=case_id,
        pass_threshold=0.70,
    )
    return {
        "id": case_id,
        "domain": str(case.get("domain") or "general"),
        "terminal_type": str((terminal or {}).get("type") or "missing"),
        "termination_reason": str((terminal or {}).get("termination_reason") or ""),
        "pipeline_version": str((terminal or {}).get("pipeline_version") or ""),
        "trace_id": trace_id,
        "corpus_sha": str((terminal or {}).get("corpus_sha") or ""),
        "document_count": len(documents),
        "source_drawer_count": len(source_drawer),
        "source_payload_status": source_payload_status,
        "provider_status": provider_status,
        "latency_s": round(time.perf_counter() - started, 3),
        "errors": errors,
        "metrics": {
            "faithfulness": evaluation.faithfulness,
            "answer_relevance": evaluation.answer_relevance,
            "context_precision": evaluation.context_precision,
            "context_recall": evaluation.context_recall,
            "anchor_accuracy": evaluation.anchor_accuracy,
            "overall_score": evaluation.overall_ragas_score,
            "passed": evaluation.passed_gate and not errors and terminal is not None,
            "evaluator_status": evaluation.evaluator_status,
        },
    }


def _promotion_ready(
    results: list[dict[str, Any]],
    *,
    min_pass_rate: float,
    min_anchor_accuracy: float,
    min_context_recall: float,
) -> bool:
    """Apply live-gate thresholds without treating unavailable evidence as a pass."""

    if not results:
        return False
    if any(item.get("provider_status") != "ok" for item in results):
        return False
    if any(item.get("source_payload_status") == "missing" for item in results):
        return False
    if any((item.get("metrics") or {}).get("evaluator_status") != "ok" for item in results):
        return False

    total = len(results)
    pass_rate = sum(bool(item["metrics"]["passed"]) for item in results) / total
    anchor_accuracy = sum(float(item["metrics"]["anchor_accuracy"]) for item in results) / total
    context_recall = sum(float(item["metrics"]["context_recall"]) for item in results) / total
    return (
        pass_rate >= min_pass_rate
        and anchor_accuracy >= min_anchor_accuracy
        and context_recall >= min_context_recall
    )


async def _run(args: argparse.Namespace) -> int:
    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    cases = list(benchmark.get("cases") or [])
    if not cases:
        raise ValueError("Live benchmark contains no cases")

    runtime = AgentWorkflowRuntime(default_dependencies(), answer_chunk_delay_s=0)
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        result = await _run_case(runtime, case)
        results.append(result)
        print(
            f"[{index:02d}/{len(cases):02d}] {result['id']} "
            f"passed={result['metrics']['passed']} latency_s={result['latency_s']}"
        )

    total = len(results)
    pass_rate = sum(bool(item["metrics"]["passed"]) for item in results) / total
    anchor_accuracy = sum(float(item["metrics"]["anchor_accuracy"]) for item in results) / total
    context_recall = sum(float(item["metrics"]["context_recall"]) for item in results) / total
    evaluator_statuses = sorted(
        {
            str((item.get("metrics") or {}).get("evaluator_status") or "unknown")
            for item in results
        }
    )
    evaluator_unavailable_cases = sum(
        (item.get("metrics") or {}).get("evaluator_status") != "ok" for item in results
    )
    provider_unavailable_cases = sum(item.get("provider_status") != "ok" for item in results)
    report = {
        "benchmark": str(args.benchmark),
        "sample_size": total,
        "thresholds": {
            "pass_rate": args.min_pass_rate,
            "anchor_accuracy": args.min_anchor_accuracy,
            "context_recall": args.min_context_recall,
        },
        "metrics": {
            "pass_rate": round(pass_rate, 4),
            "anchor_accuracy": round(anchor_accuracy, 4),
            "context_recall": round(context_recall, 4),
            "evaluator_statuses": evaluator_statuses,
            "evaluator_unavailable_cases": evaluator_unavailable_cases,
            "provider_unavailable_cases": provider_unavailable_cases,
        },
        "cases": results,
    }
    report["promotion_ready"] = _promotion_ready(
        results,
        min_pass_rate=args.min_pass_rate,
        min_anchor_accuracy=args.min_anchor_accuracy,
        min_context_recall=args.min_context_recall,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "promotion_ready": report["promotion_ready"]}, indent=2))
    return 0 if report["promotion_ready"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-pass-rate", type=float, default=0.70)
    parser.add_argument("--min-anchor-accuracy", type=float, default=0.80)
    parser.add_argument("--min-context-recall", type=float, default=0.75)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
