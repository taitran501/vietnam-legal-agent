"""Live-agent promotion gate tests."""

from __future__ import annotations

from scripts.run_live_agent_eval import _promotion_ready


def _case(*, evaluator_status: str = "ok", provider_status: str = "ok", passed: bool = True) -> dict:
    return {
        "provider_status": provider_status,
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


def test_live_gate_applies_thresholds_when_evidence_is_available() -> None:
    assert _promotion_ready(
        [_case(), _case()],
        min_pass_rate=1.0,
        min_anchor_accuracy=0.8,
        min_context_recall=0.8,
    )
