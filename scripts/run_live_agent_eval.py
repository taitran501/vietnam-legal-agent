"""Run the checked-in legal benchmark through the live autonomous runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from epr_agent.agent.graph import default_dependencies
from epr_agent.agent.runtime import AgentWorkflowRuntime
from epr_agent.eval.contracts import EvalTurn, EvaluationCase, EvidenceStatus, ExpectedOutcome
from epr_agent.eval.ragas_evaluator import evaluate_ragas_sample, unavailable_ragas_result
from epr_agent.eval.replay import replay_case

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


def _legacy_case_to_evaluation_case(case: dict[str, Any]) -> EvaluationCase:
    """Adapt the historical benchmark without turning it into legal ground truth.

    The checked-in benchmark predates the structured evaluation contract.  It
    remains useful for runtime/provider smoke coverage, but its expected
    anchors are passed separately as informational RAGAS inputs.  The replay
    report is still the source of truth for event, trace and payload evidence.
    """

    case_id = str(case.get("id") or case.get("case_id") or "").strip()
    query = str(case.get("query") or "").strip()
    if not case_id or not query:
        raise ValueError("Legacy benchmark cases require non-empty id and query")
    return EvaluationCase(
        case_id=case_id,
        domain=str(case.get("domain") or "general"),
        turns=[EvalTurn(query=query, expected_outcome=ExpectedOutcome.ANSWER_COMPLETE)],
        expected_outcome=ExpectedOutcome.ANSWER_COMPLETE,
        evidence={
            "status": EvidenceStatus.INFORMATIONAL,
            "notes": "Legacy runtime benchmark; expected anchors are informational only.",
        },
    )


def _load_benchmark_cases(path: Path) -> list[tuple[EvaluationCase, list[str]]]:
    """Load structured fixtures and adapt the legacy 50-case benchmark."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(raw_cases, list):
        raw_cases = [payload]

    loaded: list[tuple[EvaluationCase, list[str]]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise TypeError("Evaluation benchmark cases must be JSON objects")
        if isinstance(raw_case.get("turns"), list):
            evaluation_case = EvaluationCase.model_validate(raw_case)
            expected_anchors = sorted(
                {
                    anchor
                    for claim in evaluation_case.claims
                    for anchor in claim.anchors
                    if anchor
                }
            )
        else:
            evaluation_case = _legacy_case_to_evaluation_case(raw_case)
            expected_anchors = [str(anchor) for anchor in raw_case.get("expected_anchors") or [] if anchor]
        loaded.append((evaluation_case, expected_anchors))
    return loaded


def _terminal_event(turn_report: dict[str, Any]) -> dict[str, Any]:
    return next(
        (
            event
            for event in reversed(turn_report.get("events") or [])
            if event.get("type") in {"response_complete", "response_stopped", "error"}
        ),
        {},
    )


def _failed_replay_report(
    case: EvaluationCase,
    *,
    conversation_id: str,
    error: Exception,
) -> dict[str, Any]:
    """Create a stable case artifact when the runtime cannot produce a replay."""

    message = str(error) or type(error).__name__
    error_event = {
        "type": "error",
        "code": "provider_unavailable",
        "error_code": "provider_unavailable",
        "message": message,
    }
    turn = {
        "turn_index": 1,
        "query": case.turns[0].query,
        "conversation_id": conversation_id,
        "trace_id": "",
        "events": [error_event],
        "errors": [error_event],
        "documents": [],
        "source_drawer": [],
        "terminal_type": "error",
    }
    return {
        "schema_version": "evaluation-replay-v1",
        "case_id": case.case_id,
        "mode": "live",
        "conversation_id": conversation_id,
        "pipeline_version": "pipeline-agent",
        "corpus_sha": "",
        "turns": [turn],
        "result": {
            "status": "fail",
            "gate_eligible": True,
            "failure_codes": ["provider_unavailable"],
        },
        "error": message,
    }


async def _run_case(
    runtime: AgentWorkflowRuntime,
    case: EvaluationCase,
    *,
    expected_anchors: list[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    conversation_id = f"live-eval-{case.case_id.lower()}"
    replay_error: Exception | None = None
    try:
        replay = await replay_case(
            runtime,
            case,
            mode="live",
            user_id="live-eval",
            conversation_id=conversation_id,
        )
        if not isinstance(replay, dict):
            raise TypeError("replay_invalid_report")
        turns = replay.get("turns")
        if (
            not isinstance(turns, list)
            or not turns
            or any(not isinstance(turn, dict) for turn in turns)
        ):
            raise TypeError("replay_invalid_turns")
    except Exception as exc:  # noqa: BLE001 - preserve a failed case artifact
        replay_error = exc
        replay = _failed_replay_report(case, conversation_id=conversation_id, error=exc)

    final_turn = (replay.get("turns") or [{}])[-1]
    terminal = _terminal_event(final_turn)
    errors = [event for turn in replay.get("turns") or [] for event in turn.get("errors") or []]
    query = str(final_turn.get("query") or case.turns[-1].query)
    answer = str(terminal.get("text") or "")
    documents = [
        document for document in terminal.get("documents") or [] if isinstance(document, dict)
    ]
    raw_source_drawer = terminal.get("sources")
    source_drawer = [
        document for document in raw_source_drawer or [] if isinstance(document, dict)
    ]
    trace_id = str(terminal.get("trace_id") or final_turn.get("trace_id") or "")
    provider_status = "ok" if terminal and not errors else "provider_unavailable"
    replay_result = dict(replay.get("result") or {})
    replay_failure_codes = [str(code) for code in replay_result.get("failure_codes") or []]
    if "provider_unavailable" in replay_failure_codes:
        provider_status = "provider_unavailable"
    source_payload_status = (
        "ok"
        if source_drawer
        else "not_applicable"
        if not documents
        else "missing"
    )
    evaluator_error: Exception | None = None
    if replay_error is not None or provider_status != "ok" or not terminal:
        evaluation = unavailable_ragas_result(
            sample_id=case.case_id,
            query=query,
            details={
                "error_code": "provider_unavailable",
                "provider_error": str(replay_error) if replay_error else "terminal_unavailable",
            },
        )
    else:
        try:
            evaluation = await evaluate_ragas_sample(
                query=query,
                answer=answer,
                retrieved_docs=_documents_for_evaluator(documents),
                expected_anchors=expected_anchors,
                sample_id=case.case_id,
                pass_threshold=0.70,
            )
        except Exception as exc:  # noqa: BLE001 - evaluator health is a gate
            evaluator_error = exc
            evaluation = unavailable_ragas_result(
                sample_id=case.case_id,
                query=query,
                context_recall=0.0,
                anchor_accuracy=0.0,
                details={
                    "error_code": "evaluation_unavailable",
                    "evaluator_error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
    replay_passed = (
        replay_result.get("status") == "pass"
        and bool(replay_result.get("gate_eligible", True))
        and not replay_failure_codes
    )
    return {
        "id": case.case_id,
        "domain": case.domain,
        "evidence_status": case.evidence.status.value,
        "expected_anchors": expected_anchors,
        "terminal_type": str(terminal.get("type") or "missing"),
        "termination_reason": str(terminal.get("termination_reason") or ""),
        "pipeline_version": str(terminal.get("pipeline_version") or replay.get("pipeline_version") or ""),
        "trace_id": trace_id,
        "corpus_sha": str(terminal.get("corpus_sha") or replay.get("corpus_sha") or ""),
        "document_count": len(documents),
        "source_drawer_count": len(source_drawer),
        "source_payload_status": source_payload_status,
        "provider_status": provider_status,
        "provider_error": str(replay_error) if replay_error else None,
        "evaluator_error": str(evaluator_error) if evaluator_error else None,
        "latency_s": round(time.perf_counter() - started, 3),
        "errors": errors,
        "replay_status": str(replay_result.get("status") or "fail"),
        "replay_gate_eligible": bool(replay_result.get("gate_eligible")),
        "replay_failure_codes": replay_failure_codes,
        "replay": replay,
        "metrics": {
            "faithfulness": evaluation.faithfulness,
            "answer_relevance": evaluation.answer_relevance,
            "context_precision": evaluation.context_precision,
            "context_recall": evaluation.context_recall,
            "anchor_accuracy": evaluation.anchor_accuracy,
            "overall_score": evaluation.overall_ragas_score,
            "passed": evaluation.passed_gate and replay_passed and not errors and bool(terminal),
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
    if any(
        "replay_status" in item
        and (item.get("replay_status") != "pass" or not item.get("replay_gate_eligible", False))
        for item in results
    ):
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
    cases = _load_benchmark_cases(args.benchmark)
    if not cases:
        raise ValueError("Live benchmark contains no cases")

    runtime = AgentWorkflowRuntime(default_dependencies(), answer_chunk_delay_s=0)
    results: list[dict[str, Any]] = []
    for index, (case, expected_anchors) in enumerate(cases, start=1):
        result = await _run_case(runtime, case, expected_anchors=expected_anchors)
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
        "schema_version": "live-agent-eval-v2",
        "mode": "live",
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
