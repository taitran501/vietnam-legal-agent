"""Static contract checks for the provider-backed live evaluation workflow."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "live-agent-eval.yml"


def test_live_agent_workflow_is_manual_and_pilot_scoped() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "environment: pilot" in workflow
    assert "group: live-agent-eval-pilot" in workflow


def test_live_agent_workflow_declares_runtime_and_corpus_contract() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "image: redis:7.4-alpine" in workflow
    assert "REDIS_URL: redis://127.0.0.1:6379/0" in workflow
    assert "QDRANT_CLOUD_URL: ${{ secrets.QDRANT_CLOUD_URL }}" in workflow
    assert "QDRANT_API_KEY: ${{ secrets.QDRANT_API_KEY }}" in workflow
    assert "LAW_COLLECTION: ${{ vars.PILOT_LAW_COLLECTION }}" in workflow
    assert "python -m scripts.sync_corpus_metadata --check" in workflow
    assert "--benchmark data/eval/golden_legal_benchmark.json" in workflow
