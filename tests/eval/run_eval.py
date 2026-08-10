"""Run the 50-case legal-first workflow contract against a local stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

from epr_agent.agent.runtime import stream_chat
from tests.eval.legal_first_manifest import LEGAL_FIRST_CASES


async def run_case(case: dict[str, object]) -> dict[str, object]:
    started = time.perf_counter()
    events = [event async for event in stream_chat(
        query=str(case["query"]), user_id="eval-local", conversation_id=f"eval-{uuid.uuid4().hex}",
    )]
    complete = next((event for event in events if event.get("type") == "response_complete"), {})
    actions = [str(event.get("action")) for event in events if event.get("type") == "workflow_step"]
    expected_articles = [item.lower() for item in case.get("expected_articles", [])]
    citations = complete.get("citations") or []
    citation_labels = " ".join(str(item.get("label", "")) for item in citations).lower()
    passed = (
        complete.get("task_type") == case["expected_task_type"]
        and complete.get("termination_reason") == case["termination"]
        and complete.get("source") == case["source_type"]
        and all(action in actions for action in case["required_actions"])
        and all(action not in actions for action in case["forbidden_actions"])
        and all(article in citation_labels for article in expected_articles)
    )
    return {"id": case["id"], "passed": passed, "actions": actions, "termination": complete.get("termination_reason"), "duration_ms": round((time.perf_counter() - started) * 1000, 2)}


async def main(limit: int | None, output: Path | None) -> int:
    results = [await run_case(case) for case in LEGAL_FIRST_CASES[:limit]]
    if output:
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [result for result in results if not result["passed"]]
    print(json.dumps({"total": len(results), "passed": len(results) - len(failed), "failed": failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.limit, args.output)))
