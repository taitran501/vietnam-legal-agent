"""Trace-linked quality feedback persistence and triage tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from backend.api.routes.feedback import QualityReviewRequest

from epr_agent.infra.persistence import PersistenceStore, sqlite_database_url


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
