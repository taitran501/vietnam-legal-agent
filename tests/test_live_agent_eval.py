"""Live-agent promotion gate tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from scripts.run_live_agent_eval import _load_benchmark_cases, _promotion_ready, _run_case

from epr_agent.eval.contracts import EvalTurn, EvaluationCase, EvidenceStatus, ExpectedOutcome


def _case(
    *,
    evaluator_status: str = "ok",
    provider_status: str = "ok",
    source_payload_status: str = "ok",
    passed: bool = True,
) -> dict:
    return {
        "provider_status": provider_status,
        "source_payload_status": source_payload_status,
        "metrics": {
            "evaluator_status": evaluator_status,
            "passed": passed,
            "anchor_accuracy": 1.0,
            "context_recall": 1.0,
        },
    }


def test_live_gate_requires_available_evaluator_for_every_case() -> None:
    results = [_case(), _case(evaluator_status="evaluation_unavailable")]

    assert not _promotion_ready(
        results,
        min_pass_rate=0.5,
        min_anchor_accuracy=0.5,
        min_context_recall=0.5,
    )


def test_live_gate_requires_provider_for_every_case() -> None:
    results = [_case(), _case(provider_status="provider_unavailable", passed=False)]

    assert not _promotion_ready(
        results,
        min_pass_rate=0.5,
        min_anchor_accuracy=0.5,
        min_context_recall=0.5,
    )


def test_live_gate_requires_source_payload_when_documents_are_returned() -> None:
    results = [_case(), _case(source_payload_status="missing", passed=False)]

    assert not _promotion_ready(
        results,
        min_pass_rate=0.5,
        min_anchor_accuracy=0.5,
        min_context_recall=0.5,
    )


def test_live_gate_applies_thresholds_when_evidence_is_available() -> None:
    assert _promotion_ready(
        [_case(), _case()],
        min_pass_rate=1.0,
        min_anchor_accuracy=0.8,
        min_context_recall=0.8,
    )


def test_legacy_benchmark_is_adapted_to_informational_evaluation_case(tmp_path) -> None:
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "LEGACY-001",
                        "domain": "labor",
                        "query": "Quy định gì?",
                        "expected_anchors": ["Điều 1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = _load_benchmark_cases(benchmark)

    assert len(cases) == 1
    evaluation_case, expected_anchors = cases[0]
    assert evaluation_case.case_id == "LEGACY-001"
    assert evaluation_case.turns[0].expected_outcome == ExpectedOutcome.ANSWER_COMPLETE
    assert evaluation_case.evidence.status == EvidenceStatus.INFORMATIONAL
    assert expected_anchors == ["Điều 1"]


def test_structured_fixture_preserves_claim_anchors(tmp_path) -> None:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "case_id": "STRUCTURED-001",
                "turns": [{"query": "Quy định gì?"}],
                "claims": [
                    {
                        "claim_id": "claim-1",
                        "text": "Thời hạn là 10 ngày.",
                        "anchors": ["Điều 1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cases = _load_benchmark_cases(fixture)

    assert cases[0][0].case_id == "STRUCTURED-001"
    assert cases[0][1] == ["Điều 1"]


def test_live_gate_rejects_structured_replay_failure() -> None:
    result = _case()
    result.update(
        {
            "replay_status": "fail",
            "replay_gate_eligible": True,
            "replay_failure_codes": ["source_drawer_payload_mismatch"],
        }
    )

    assert not _promotion_ready(
        [result],
        min_pass_rate=0.5,
        min_anchor_accuracy=0.5,
        min_context_recall=0.5,
    )


@pytest.mark.asyncio
async def test_live_case_uses_structured_replay_report(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def fake_replay(runtime, case, **kwargs):
        calls["runtime"] = runtime
        calls["case_id"] = case.case_id
        calls["mode"] = kwargs["mode"]
        return {
            "schema_version": "evaluation-replay-v1",
            "pipeline_version": "pipeline-agent",
            "corpus_sha": "sha-test",
            "turns": [
                {
                    "query": "Quy định gì?",
                    "trace_id": "trace-1",
                    "errors": [],
                    "events": [
                        {
                            "type": "response_complete",
                            "text": "Theo Điều 1 [1].",
                            "documents": [
                                {
                                    "content": "Điều 1 quy định.",
                                    "metadata": {"legal_anchor": "Điều 1"},
                                }
                            ],
                            "sources": [{"source_id": "law-1"}],
                            "trace_id": "trace-1",
                            "pipeline_version": "pipeline-agent",
                            "corpus_sha": "sha-test",
                        }
                    ],
                }
            ],
            "result": {
                "status": "pass",
                "gate_eligible": True,
                "failure_codes": [],
            },
        }

    async def fake_ragas(**_kwargs):
        return SimpleNamespace(
            faithfulness=1.0,
            answer_relevance=1.0,
            context_precision=1.0,
            context_recall=1.0,
            anchor_accuracy=1.0,
            overall_ragas_score=1.0,
            passed_gate=True,
            evaluator_status="ok",
        )

    monkeypatch.setattr("scripts.run_live_agent_eval.replay_case", fake_replay)
    monkeypatch.setattr("scripts.run_live_agent_eval.evaluate_ragas_sample", fake_ragas)

    runtime = object()
    case = EvaluationCase(
        case_id="LIVE-001",
        turns=[EvalTurn(query="Quy định gì?", expected_outcome=ExpectedOutcome.ANSWER_COMPLETE)],
        expected_outcome=ExpectedOutcome.ANSWER_COMPLETE,
    )
    result = await _run_case(runtime, case, expected_anchors=["Điều 1"])

    assert calls["runtime"] is runtime
    assert calls["case_id"] == "LIVE-001"
    assert calls["mode"] == "live"
    assert result["replay_status"] == "pass"
    assert result["evidence_status"] == "informational"
    assert result["expected_anchors"] == ["Điều 1"]
    assert result["trace_id"] == "trace-1"
    assert result["provider_status"] == "ok"
    assert result["replay"]["result"]["failure_codes"] == []
