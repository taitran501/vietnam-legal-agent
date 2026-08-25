"""Replay audited legal cases through AgentWorkflowRuntime.

Deterministic mode never initializes OpenAI/Qdrant providers. Live mode is
explicit and intended for the manual pilot workflow only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from epr_agent.agent.graph import default_dependencies
from epr_agent.agent.runtime import AgentWorkflowRuntime
from epr_agent.eval.replay import (
    deterministic_runtime,
    load_cases,
    replay_case,
    write_report,
)

DEFAULT_FIXTURE = ROOT / "data" / "eval" / "audited" / "2026-law-follow-up.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "evaluation-replay.json"


async def _run(args: argparse.Namespace) -> int:
    cases = load_cases(args.fixture)
    reports: list[dict[str, Any]] = []
    for case in cases:
        runtime: AgentWorkflowRuntime
        if args.mode == "deterministic":
            runtime = deterministic_runtime(case)
        else:
            runtime = AgentWorkflowRuntime(default_dependencies(), answer_chunk_delay_s=0)
        reports.append(
            await replay_case(
                runtime,
                case,
                mode=args.mode,
                user_id=args.user_id,
                conversation_id=args.conversation_id,
            )
        )
    write_report(args.output, reports)
    payload = json.loads(Path(args.output).read_text(encoding="utf-8"))
    print(json.dumps({key: payload[key] for key in ("cases", "gate_eligible", "passed", "informational")}, ensure_ascii=False))
    failed_gate = any(
        report["result"].get("gate_eligible") and report["result"].get("status") != "pass"
        for report in reports
    )
    return 1 if failed_gate else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mode", choices=("deterministic", "live"), default="deterministic")
    parser.add_argument("--user-id", default="evaluation")
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
