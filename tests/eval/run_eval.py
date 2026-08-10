"""Run Pipeline V3 workflow contracts against a ready local stack.

This is intentionally a manual, variable-cost runner. Unit tests consume
deterministic doubles; this runner uses ``WorkflowRuntime`` through the same
``stream_chat`` API surface as FastAPI and records only a local JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from epr_agent.agent.runtime import stream_chat
from tests.eval.pipeline_v3_manifest import E2E_TRAJECTORIES, QUERY_UNDERSTANDING_CASES, RETRIEVAL_CASES


def _cases(suite: str) -> list[dict[str, object]]:
    return {
        "query": QUERY_UNDERSTANDING_CASES,
        "retrieval": RETRIEVAL_CASES,
        "e2e": E2E_TRAJECTORIES,
    }[suite]


async def _turn(*, query: str, conversation_id: str, mode: str = "auto") -> tuple[dict[str, Any], list[str]]:
    events = [
        event
        async for event in stream_chat(
            query=query,
            user_id="eval-local",
            conversation_id=conversation_id,
            mode=mode,
        )
    ]
    complete = next((event for event in events if event.get("type") == "response_complete"), {})
    actions = [str(event.get("action")) for event in events if event.get("type") == "workflow_step"]
    return complete, actions


async def run_case(case: dict[str, object]) -> dict[str, object]:
    started = time.perf_counter()
    conversation_id = f"eval-v3-{uuid.uuid4().hex}"
    for prior in case.get("prelude", []):
        await _turn(query=str(prior), conversation_id=conversation_id)
    complete, actions = await _turn(
        query=str(case["query"]),
        conversation_id=conversation_id,
        mode=str(case.get("mode") or "auto"),
    )
    expected_route = str(case["expected_route"])
    expected_termination = str(case.get("expected_termination") or "answer_complete")
    expected_articles = [str(value).casefold() for value in case.get("expected_articles", [])]
    citation_labels = " ".join(
        str(item.get("label", "")) for item in complete.get("citations") or [] if isinstance(item, dict)
    ).casefold()
    passed = (
        complete.get("route") == expected_route
        and complete.get("termination_reason") == expected_termination
        and all(article in citation_labels for article in expected_articles)
    )
    return {
        "id": case["id"],
        "passed": passed,
        "route": complete.get("route"),
        "termination": complete.get("termination_reason"),
        "actions": actions,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def main(suite: str, limit: int | None, output: Path | None) -> int:
    selected = _cases(suite)[:limit]
    results = [await run_case(case) for case in selected]
    durations = sorted(float(result["duration_ms"]) for result in results)
    report = {
        "suite": suite,
        "total": len(results),
        "passed": sum(bool(result["passed"]) for result in results),
        "failed": [result for result in results if not result["passed"]],
        "p95_ms": durations[max(0, int(len(durations) * 0.95) - 1)] if durations else 0.0,
        "results": results,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("query", "retrieval", "e2e"), default="e2e")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.suite, args.limit, args.output)))
