"""Promptfoo assertion delegating quality semantics to internal reports."""

from __future__ import annotations

import json
from typing import Any


def get_assert(output: str, context: dict[str, Any]) -> dict[str, Any]:
    del context
    try:
        report = json.loads(output)
        result = dict(report.get("result") or {})
    except (TypeError, json.JSONDecodeError) as exc:
        return {"pass": False, "score": 0.0, "reason": f"invalid replay report: {exc}"}

    status = str(result.get("status") or "")
    gate_eligible = bool(result.get("gate_eligible"))
    if status == "informational" and not gate_eligible:
        return {
            "pass": True,
            "score": 0.0,
            "reason": "fixture is pending legal audit and is informational only",
        }
    passed = status == "pass" and gate_eligible and not result.get("failure_codes")
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "audited replay passed" if passed else f"replay failed: {result.get('failure_codes')}",
    }

