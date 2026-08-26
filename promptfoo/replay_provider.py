"""Promptfoo provider wrapping the deterministic replay runner."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from epr_agent.eval.replay import (
    config_hash,
    deterministic_runtime,
    git_commit_sha,
    load_cases,
    replay_case,
)


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
    try:
        report = asyncio.run(
            replay_case(
                deterministic_runtime(case),
                case,
                mode=mode,
                user_id="promptfoo",
                conversation_id=f"promptfoo-{case.case_id.lower()}",
            )
        )
    except Exception as exc:  # noqa: BLE001 - preserve a failing matrix artifact
        report = {
            "schema_version": "evaluation-replay-v1",
            "case_id": case.case_id,
            "mode": mode,
            "commit_sha": git_commit_sha(),
            "config_hash": config_hash(mode=mode, case=case),
            "turns": [],
            "result": {
                "case_id": case.case_id,
                "status": "fail",
                "gate_eligible": True,
                "failure_codes": ["source_provenance_loss"],
                "metadata": {
                    "adapter_error": str(exc),
                    "error_type": type(exc).__name__,
                },
            },
        }
    return {
        "output": json.dumps(report, ensure_ascii=False),
        "metadata": {
            "case_id": case.case_id,
            "mode": mode,
            "schema_version": report.get("schema_version"),
            "evaluation": report["result"],
        },
    }

