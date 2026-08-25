"""Generate Promptfoo cases from checked-in audited fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from epr_agent.eval.replay import load_cases

ROOT = Path(__file__).resolve().parents[1]


def generate_tests(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    del config
    fixtures = sorted((ROOT / "data" / "eval" / "audited").glob("*.json"))
    tests: list[dict[str, Any]] = []
    for fixture in fixtures:
        cases = load_cases(fixture)
        for case in cases:
            tests.append(
                {
                    "description": case.case_id,
                    "vars": {"fixture": str(fixture)},
                }
            )
    if not tests:
        raise RuntimeError("No audited evaluation fixtures found for Promptfoo")
    return tests

