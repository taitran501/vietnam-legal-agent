"""Promptfoo adapter tests without invoking the Node CLI."""

from __future__ import annotations

import json
from pathlib import Path

from promptfoo.assertions import get_assert
from promptfoo.replay_provider import call_api


def test_promptfoo_provider_returns_replay_report_for_example_fixture() -> None:
    fixture = str(Path("data/eval/examples/legal-follow-up.json").resolve())
    response = call_api("ignored", {}, {"vars": {"fixture": fixture}})
    report = json.loads(response["output"])
    result = report["result"]
    assert result["status"] == "pass"
    assertion = get_assert(response["output"], {})
    assert assertion["pass"] is True

