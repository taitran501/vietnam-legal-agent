from __future__ import annotations

import json
from pathlib import Path


def test_legacy_golden_manifest_still_contains_33_cases():
    path = Path(__file__).parents[1] / "eval" / "test_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 33
    assert {case["expected_route"] for case in payload["cases"]} >= {"chitchat", "vectorstore_faq"}
