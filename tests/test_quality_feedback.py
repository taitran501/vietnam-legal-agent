"""Trace-linked quality feedback persistence and triage tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from backend.api.routes.feedback import QualityReviewRequest
from sqlalchemy import event

from vietnam_legal_agent.agent.workflow.contracts import default_dependencies
from vietnam_legal_agent.config import get_settings
from vietnam_legal_agent.infra.persistence import PersistenceStore, sqlite_database_url
from vietnam_legal_agent.tools.legal_readiness import LegalReadinessGate


@pytest.mark.asyncio
async def test_feedback_creates_redacted_quality_triage_item(tmp_path: Path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "quality.sqlite3")))
    await store.initialize()
    try:
        await store.ensure_conversation("owner", "conversation", "Q")
        message_id = await store.append_exchange(
            "owner",
            "conversation",
            "Số điện thoại 0912345678 hỏi Điều 1?",
            "Theo Điều 1, thời hạn là 10 ngày.",
            {
                "trace_id": "trace-1",
                "pipeline_version": "pipeline-v4",
                "corpus_sha": "sha-1",
                "sources": [
                    {
                        "source_id": "law-1",
                        "anchor": "Điều 1",
                        "official_url": "https://example.gov.vn/law-1",
                        "excerpt": "Không được lưu vào triage snapshot.",
                    }
                ],
            },
        )
        saved = await store.save_feedback("owner", "conversation", message_id, 1, "Cần kiểm tra")
        assert saved and saved["quality_feedback_id"]

        items = await store.list_quality_feedback()
        assert len(items) == 1
        item = items[0]
        assert item["trace_id"] == "trace-1"
        assert item["status"] == "new"
        assert item["query"].startswith("Số điện thoại")
        assert "091****678" in item["query"]
        assert "excerpt" not in item["evidence_snapshot"]["sources"][0]
        assert item["evidence_snapshot"]["sources"][0]["source_id"] == "law-1"

        updated = await store.update_quality_feedback(
            int(item["id"]),
            status="accepted",
            failure_category="source_provenance_loss",
            reviewer_id="quality-reviewer",
            review_notes="Reproduced with replay report.",
            dataset_case_id="FEEDBACK-1",
        )
        assert updated and updated["status"] == "accepted"
        assert updated["failure_category"] == "source_provenance_loss"
        assert updated["dataset_case_id"] == "FEEDBACK-1"
    finally:
        await store.close()


def test_quality_review_request_restricts_state_transitions() -> None:
    assert QualityReviewRequest(status="reproduced", failure_category="followup_context_loss").status == "reproduced"
    with pytest.raises(ValueError):
        QualityReviewRequest(status="unknown")


@pytest.mark.asyncio
async def test_list_quality_feedback_runs_in_single_query(tmp_path: Path) -> None:
    """Verify list_quality_feedback eliminates the N+1 query cascade via a single joined query."""
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "quality_single.sqlite3")))
    await store.initialize()
    try:
        # Seed multiple feedback entries across conversations
        for i in range(4):
            conv_id = f"conv-{i // 2}"
            await store.ensure_conversation("owner", conv_id, f"Seed {i}")
            mid = await store.append_exchange("owner", conv_id, f"Câu hỏi {i}?", f"Câu trả lời {i}")
            await store.save_feedback("owner", conv_id, mid, 1, f"Comment {i}")

        executed_queries: list[str] = []

        def hook(conn, cursor, statement, params, context, executemany):
            executed_queries.append(statement)

        event.listen(store.engine.sync_engine, "before_cursor_execute", hook)
        try:
            items = await store.list_quality_feedback(limit=50)
        finally:
            event.remove(store.engine.sync_engine, "before_cursor_execute", hook)

        assert len(items) == 4
        # Single query execution eliminates N+1 queries
        assert len(executed_queries) == 1, f"Expected 1 SQL query, executed {len(executed_queries)}"
        for item in items:
            assert item["query"].startswith("Câu hỏi")
            assert item["answer"].startswith("Câu trả lời")
    finally:
        await store.close()


def test_workflow_enforce_legal_readiness_gate_wiring() -> None:
    """Verify default_dependencies wires LegalReadinessGate and ScopedAnswerCache when enabled."""
    settings = get_settings()

    with patch.object(settings, "enforce_legal_readiness_gate", False):
        deps_disabled = default_dependencies()
        assert deps_disabled.legal_readiness is None
        assert deps_disabled.cache.legal_readiness_sha == ""

    with patch.object(settings, "enforce_legal_readiness_gate", True):
        deps_enabled = default_dependencies()
        assert deps_enabled.legal_readiness is not None
        assert isinstance(deps_enabled.legal_readiness, LegalReadinessGate)
        assert deps_enabled.cache.legal_readiness_sha == deps_enabled.legal_readiness.manifest_sha256

