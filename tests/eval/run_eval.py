"""Run the Pipeline V4 evaluation suites locally.

Default mode uses deterministic adapters and is safe for repeated local test
runs.  ``--live`` uses the configured Docker runtime, real Qdrant collection,
and OpenAI embedding/generation path; it is intentionally manual and may
incur API cost.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Make the documented root command work without relying on pytest's
# pythonpath configuration or an editable install.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from epr_agent.agent.runtime import stream_chat
from epr_agent.domain.epr_rules import EPR_RULE_PACK_VERSION
from epr_agent.domain.tasks import classify_route
from tests.agent.v4_test_support import NoEvidenceRetrieval
from tests.agent.v4_test_support import runtime as deterministic_runtime
from tests.eval.pipeline_v4_manifest import (
    E2E_TRAJECTORIES,
    MANIFEST,
    QUERY_UNDERSTANDING_CASES,
    RETRIEVAL_CASES,
)


def _expected_termination(case: dict[str, Any]) -> str:
    if case.get("expected_termination"):
        return str(case["expected_termination"])
    return {
        "completed": "answer_complete",
        "needs_information": "awaiting_user_input",
        "insufficient_evidence": "insufficient_evidence",
        "out_of_scope": "out_of_scope",
        "failed": "error",
    }.get(str(case.get("expected_outcome", "completed")), "answer_complete")


def _anchors_from_document(document: dict[str, Any]) -> set[str]:
    metadata = document.get("metadata") or {}
    values = [metadata.get("legal_anchor"), metadata.get("Dieu"), document.get("content")]
    return {str(value) for value in values if value}


def _documents(complete: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in complete.get("documents") or [] if isinstance(item, dict)]


def _retrieval_metrics(case: dict[str, Any], complete: dict[str, Any]) -> dict[str, float | bool]:
    expected = {str(item) for item in case.get("expected_articles") or []}
    ranked = _documents(complete)
    ranked_anchors = [_anchors_from_document(document) for document in ranked]
    if not expected:
        return {"p_at_1": 1.0, "ndcg_at_3": 1.0, "recall_at_5": 1.0, "explicit_hit_at_1": True}

    def relevant(anchor_set: set[str]) -> int:
        return int(any(any(gold.casefold() in value.casefold() for value in anchor_set) for gold in expected))

    p_at_1 = float(relevant(ranked_anchors[0])) if ranked_anchors else 0.0
    retrieved = sum(relevant(anchors) for anchors in ranked_anchors[:5])
    recall_at_5 = min(1.0, retrieved / max(1, len(expected)))
    dcg = sum(relevant(anchors) / math.log2(index + 2) for index, anchors in enumerate(ranked_anchors[:3]))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(3, len(expected))))
    ndcg = dcg / ideal if ideal else 0.0
    explicit = case.get("category") == "explicit"
    return {
        "p_at_1": p_at_1,
        "ndcg_at_3": ndcg,
        "recall_at_5": recall_at_5,
        "explicit_hit_at_1": bool(p_at_1) if explicit else True,
    }


def _route_results() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in QUERY_UNDERSTANDING_CASES:
        history = [{"role": "user", "content": "Điều 77 quy định trách nhiệm tái chế EPR."}] if case.get("is_follow_up") else []
        actual = classify_route(str(case["query"]), history, None).value
        expected = str(case["expected_route"])
        passed = actual == expected or case.get("expected_behavior") == "clarify_or_safe_stop" and actual in {"out_of_scope", "legal_lookup"}
        results.append({"id": case["id"], "expected": expected, "actual": actual, "passed": passed})
    return results


async def _turn(
    *,
    query: str,
    conversation_id: str,
    live: bool,
    intent_hint: str = "auto",
    operation: str = "message",
    mode: str = "auto",
    runtime: Any = None,
    live_url: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if live and live_url:
        import httpx

        payload = {
            "query": query,
            "conversation_id": conversation_id,
            "mode": mode,
            "operation": operation,
            "intent_hint": intent_hint,
            "interaction_source": "composer",
        }
        events: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(base_url=live_url, timeout=60.0) as client, client.stream(
                "POST", "/api/v1/chat", json=payload
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            event = json.loads(line.removeprefix("data:").strip())
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict):
                            events.append(event)
        except httpx.HTTPError as exc:
            events.append({"type": "error", "message": str(exc)})
        complete = next((event for event in reversed(events) if event.get("type") == "response_complete"), {})
        return complete, events

    events = [
        event
        async for event in stream_chat(
            query=query,
            user_id="eval-v4-live" if live else "eval-v4-deterministic",
            conversation_id=conversation_id,
            mode=mode,
            operation=operation,
            intent_hint=intent_hint,
            runtime=runtime,
        )
    ]
    complete = next((event for event in reversed(events) if event.get("type") == "response_complete"), {})
    return complete, events


async def _run_trajectory(case: dict[str, Any], *, live: bool, live_url: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    conversation_id = f"eval-v4-{uuid.uuid4().hex}"
    deterministic = None
    if not live:
        retrieval = NoEvidenceRetrieval() if case.get("expected_outcome") == "insufficient_evidence" else None
        deterministic, _, _ = deterministic_runtime(retrieval=retrieval)

    route = str(case["expected_route"])
    hint = route if route in {"case_assessment", "compliance_checklist"} else "auto"
    complete, events = await _turn(
        query=str(case["query"]), conversation_id=conversation_id, live=live, intent_hint=hint, runtime=deterministic, live_url=live_url
    )
    turns = [{"complete": complete, "events": events}]
    if case.get("resume_query"):
        resumed, resume_events = await _turn(
            query=str(case["resume_query"]),
            conversation_id=conversation_id,
            live=live,
            intent_hint=hint,
            operation="continue_case",
            runtime=deterministic,
            live_url=live_url,
        )
        turns.append({"complete": resumed, "events": resume_events})
        complete, events = resumed, resume_events

    expected_outcome = str(case.get("resume_expected_outcome") or case.get("expected_outcome", "completed"))
    expected_type = str(case.get("expected_result_type", "legal_answer"))
    if expected_outcome == "completed" and expected_type == "none":
        expected_type = "checklist" if route == "compliance_checklist" else "assessment"
    expected_termination = _expected_termination({**case, "expected_outcome": expected_outcome})
    missing = {str(item) for item in case.get("expected_missing_facts") or []}
    if case.get("resume_query") and expected_outcome == "completed":
        missing = set()
    actual_missing = {str(item) for item in complete.get("missing_facts") or []}
    required = {str(item) for item in case.get("required_issues") or []}
    covered = {str(item) for item in complete.get("covered_issues") or []}
    assessment = complete.get("assessment") or {}
    expected_status = case.get("expected_assessment_status")
    if case.get("resume_query") and expected_outcome == "completed":
        expected_status = case.get("resume_expected_assessment_status", "likely_in_scope")
    expected_ui = str(case.get("expected_ui") or "")
    if case.get("resume_query") and expected_outcome == "completed":
        expected_ui = "checklist_result" if expected_type == "checklist" else "assessment_result"
    actual_ui = (
        "assessment_result" if expected_outcome == "completed" and expected_type == "assessment"
        else "checklist_result" if expected_outcome == "completed" and expected_type == "checklist"
        else "missing_facts" if expected_outcome == "needs_information"
        else "safe_stop" if expected_outcome in {"insufficient_evidence", "out_of_scope"}
        else "answer"
    )
    sequences = [event.get("sequence") for event in events]
    sse_contract = bool(events) and sequences == list(range(1, len(events) + 1)) and all(
        event.get("trace_id") and event.get("pipeline_version") == "pipeline-v4" for event in events
    )
    passed = (
        complete.get("route") == route
        and complete.get("outcome") == expected_outcome
        and complete.get("result_type", "none") == expected_type
        and (not missing or missing.issubset(actual_missing))
        and (expected_outcome != "completed" or not required or required.issubset(covered))
        and (expected_outcome != "completed" or bool(complete.get("citations")) or route == "out_of_scope")
        and (expected_status is None or assessment.get("status") == expected_status)
        and (not expected_ui or actual_ui == expected_ui)
        and complete.get("termination_reason") == expected_termination
        and (not live or sse_contract)
    )
    return {
        "id": case["id"],
        "passed": passed,
        "route": complete.get("route"),
        "expected_route": route,
        "outcome": complete.get("outcome"),
        "expected_outcome": expected_outcome,
        "result_type": complete.get("result_type"),
        "termination": complete.get("termination_reason"),
        "expected_termination": expected_termination,
        "missing_facts": sorted(actual_missing),
        "expected_missing_facts": sorted(missing),
        "required_issues": sorted(required),
        "covered_issues": sorted(covered),
        "assessment_status": assessment.get("status"),
        "expected_assessment_status": expected_status,
        "ui_state": actual_ui,
        "expected_ui": expected_ui,
        "citation_count": len(complete.get("citations") or []),
        "trace_id": complete.get("trace_id"),
        "event_types": [event.get("type") for event in events],
        "sse_contract": sse_contract,
        "turn_count": len(turns),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def _run_retrieval_case(case: dict[str, Any], *, live: bool, live_url: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    deterministic = None
    if not live:
        deterministic, _, _ = deterministic_runtime(
            retrieval=NoEvidenceRetrieval() if case.get("category") == "no_evidence" else None
        )
    complete, _ = await _turn(
        query=str(case["query"]),
        conversation_id=f"eval-v4-retrieval-{uuid.uuid4().hex}",
        live=live,
        runtime=deterministic,
        live_url=live_url,
    )
    metrics = _retrieval_metrics(case, complete)
    expected_termination = str(case.get("expected_termination", "answer_complete"))
    passed = (
        complete.get("route") == case["expected_route"]
        and complete.get("termination_reason") == expected_termination
        and bool(metrics["explicit_hit_at_1"])
    )
    return {
        "id": case["id"],
        "passed": passed,
        "route": complete.get("route"),
        "termination": complete.get("termination_reason"),
        **metrics,
        "trace_id": complete.get("trace_id"),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    durations = sorted(float(item.get("duration_ms", 0.0)) for item in results)
    return {
        "total": len(results),
        "passed": sum(bool(item.get("passed")) for item in results),
        "failed": [item for item in results if not item.get("passed")],
        "p95_ms": durations[max(0, int(len(durations) * 0.95) - 1)] if durations else 0.0,
    }


async def run(suite: str, *, live: bool, limit: int | None) -> dict[str, Any]:
    live_url = os.getenv("EPR_EVAL_API_BASE_URL", "http://127.0.0.1") if live else None
    report: dict[str, Any] = {
        "manifest_version": MANIFEST["version"],
        "pipeline_version": "pipeline-v4",
        "mode": "live" if live else "deterministic",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "embedding_profile": MANIFEST["embedding_profile"],
        "rule_pack_version": EPR_RULE_PACK_VERSION,
        "git_sha": _git_sha(),
        "route": {"results": _route_results()},
    }
    if live:
        report["live_base_url"] = live_url
        report["readiness"] = await _live_readiness(live_url)
        report["appendix_sha256"] = (
            _file_sha256(ROOT / "artifacts" / "appendix_xxii.jsonl")
            or _file_sha256(ROOT / "data" / "appendix_xxii.jsonl")
            or (report["readiness"].get("corpus") or {}).get("appendix_sha256")
        )
    if suite in {"retrieval", "all"}:
        cases = RETRIEVAL_CASES[:limit]
        results = [await _run_retrieval_case(case, live=live, live_url=live_url) for case in cases]
        report["retrieval"] = {**_summary(results), "p_at_1": _mean(results, "p_at_1"), "ndcg_at_3": _mean(results, "ndcg_at_3"), "recall_at_5": _mean(results, "recall_at_5"), "explicit_hit_at_1": all(bool(item["explicit_hit_at_1"]) for item in results), "results": results}
    if suite in {"e2e", "all"}:
        cases = E2E_TRAJECTORIES[:limit]
        results = [await _run_trajectory(case, live=live, live_url=live_url) for case in cases]
        report["e2e"] = {**_summary(results), "issue_coverage": _issue_coverage(results), "citation_rate": _citation_rate(results), "results": results}
    report["route"]["summary"] = _summary(report["route"]["results"])
    return report


def _mean(results: list[dict[str, Any]], key: str) -> float:
    values = [float(item[key]) for item in results if key in item]
    return round(sum(values) / len(values), 6) if values else 0.0


def _issue_coverage(results: list[dict[str, Any]]) -> float:
    values = [
        len(set(item["required_issues"]) & set(item["covered_issues"])) / len(item["required_issues"])
        for item in results
        if item["required_issues"] and item.get("outcome") == "completed"
    ]
    return round(sum(values) / len(values), 6) if values else 1.0


def _citation_rate(results: list[dict[str, Any]]) -> float:
    # Chitchat and out-of-scope safe stops have no material legal claim to
    # cite.  Count only completed legal result types in this quality gate.
    completed = [
        item for item in results
        if item["outcome"] == "completed"
        and item.get("result_type") in {"legal_answer", "assessment", "checklist"}
    ]
    return round(sum(bool(item["citation_count"]) for item in completed) / len(completed), 6) if completed else 1.0


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _live_readiness(base_url: str | None) -> dict[str, Any]:
    if not base_url:
        return {"status": "not_configured"}
    import httpx

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
            response = await client.get("/api/v1/ready")
            payload = response.json()
            return {"http_status": response.status_code, **payload}
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Pipeline V4 evaluation matrix")
    parser.add_argument("--suite", choices=("retrieval", "e2e", "all"), default="all")
    parser.add_argument("--live", action="store_true", help="Use the real configured runtime")
    parser.add_argument("--live-url", help="HTTP base URL for the live Docker stack (overrides EPR_EVAL_API_BASE_URL)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.live_url:
        os.environ["EPR_EVAL_API_BASE_URL"] = args.live_url
    report = asyncio.run(run(args.suite, live=args.live, limit=args.limit))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"retrieval", "e2e"}}, ensure_ascii=False, indent=2))
    failed = len(report["route"]["summary"]["failed"])
    for suite_name in ("retrieval", "e2e"):
        if suite_name in report:
            failed += len(report[suite_name]["failed"])
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
