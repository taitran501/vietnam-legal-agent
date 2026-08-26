"""Promptfoo adapter tests without invoking the Node CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from promptfoo.assertions import get_assert
from promptfoo.replay_provider import call_api
from promptfoo.tests import generate_tests


def _fixture_path(name: str) -> str:
    return str(Path("data/eval/examples", name).resolve())


def test_promptfoo_provider_returns_replay_report_for_example_fixture() -> None:
    fixture = _fixture_path("legal-follow-up.json")
    response = call_api("ignored", {}, {"vars": {"fixture": fixture}})
    report = json.loads(response["output"])
    result = report["result"]
    assert result["status"] == "pass"
    assertion = get_assert(response["output"], {"vars": {"fixture": fixture}})
    assert assertion["pass"] is True


def test_promptfoo_assertion_verifies_claim_citation_and_source_drawer() -> None:
    fixture = _fixture_path("source-citation-contract.json")
    response = call_api("ignored", {}, {"vars": {"fixture": fixture}})

    assertion = get_assert(response["output"], {"vars": {"fixture": fixture}})

    assert assertion["pass"] is True
    report = json.loads(response["output"])
    result = report["result"]
    assert result["claim_results"][0]["cited"] is True
    assert result["source_results"][0]["present_in_drawer"] is True
    assert result["source_results"][0]["official_url_matches"] is True


def test_promptfoo_assertion_rejects_source_payload_mismatch() -> None:
    fixture = _fixture_path("source-citation-contract.json")
    response = call_api("ignored", {}, {"vars": {"fixture": fixture}})
    report = json.loads(response["output"])
    report["result"]["source_results"][0]["present_in_drawer"] = False

    assertion = get_assert(
        json.dumps(report, ensure_ascii=False),
        {"vars": {"fixture": fixture}},
    )

    assert assertion["pass"] is False
    assert "source drawer" in assertion["reason"]


def test_promptfoo_assertion_rejects_unknown_failure_taxonomy() -> None:
    fixture = _fixture_path("legal-follow-up.json")
    response = call_api("ignored", {}, {"vars": {"fixture": fixture}})
    report = json.loads(response["output"])
    report["result"].update({"status": "fail", "failure_codes": ["not_a_real_code"]})

    assertion = get_assert(
        json.dumps(report, ensure_ascii=False),
        {"vars": {"fixture": fixture}},
    )

    assert assertion["pass"] is False
    assert "unknown failure taxonomy" in assertion["reason"]


def test_promptfoo_matrix_discovers_checked_in_engineering_fixtures() -> None:
    descriptions = {item["description"] for item in generate_tests()}

    assert "LEGAL_FOLLOWUP_REPLAY_EXAMPLE" in descriptions
    assert "SOURCE_CITATION_REPLAY_EXAMPLE" in descriptions


def test_promptfoo_provider_rejects_live_mode_in_pr_adapter() -> None:
    fixture = _fixture_path("legal-follow-up.json")

    with pytest.raises(ValueError, match="only permits deterministic replay"):
        call_api("ignored", {"config": {"mode": "live"}}, {"vars": {"fixture": fixture}})


def test_promptfoo_provider_serializes_replay_exception_as_failure_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_replay(*_args, **_kwargs):
        raise RuntimeError("deterministic runtime regression")

    monkeypatch.setattr("promptfoo.replay_provider.replay_case", failing_replay)
    fixture = _fixture_path("legal-follow-up.json")

    response = call_api("ignored", {}, {"vars": {"fixture": fixture}})
    report = json.loads(response["output"])
    assertion = get_assert(response["output"], {"vars": {"fixture": fixture}})

    assert report["result"]["failure_codes"] == ["source_provenance_loss"]
    assert report["result"]["metadata"]["adapter_error"] == "deterministic runtime regression"
    assert assertion["pass"] is False

