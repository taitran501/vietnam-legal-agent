"""Promptfoo provider wrapping the deterministic replay runner."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from epr_agent.eval.replay import deterministic_runtime, load_cases, replay_case


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del prompt
    variables = dict(context.get("vars") or {})
    fixture = str(variables.get("fixture") or "")
    if not fixture:
        raise ValueError("Promptfoo test is missing vars.fixture")
    cases = load_cases(fixture)
    if len(cases) != 1:
        raise ValueError(f"Promptfoo fixture must contain exactly one case: {fixture}")
    case = cases[0]
    mode = str((options.get("config") or {}).get("mode") or "deterministic")
    if mode != "deterministic":
        raise ValueError("PR Promptfoo provider only permits deterministic replay")
    report = asyncio.run(
        replay_case(
            deterministic_runtime(case),
            case,
            mode=mode,
            user_id="promptfoo",
            conversation_id=f"promptfoo-{case.case_id.lower()}",
        )
    )
    return {
        "output": json.dumps(report, ensure_ascii=False),
        "metadata": {
            "case_id": case.case_id,
            "evaluation": report["result"],
        },
    }

