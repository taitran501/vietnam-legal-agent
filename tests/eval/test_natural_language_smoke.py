from __future__ import annotations

import json
from pathlib import Path

from scripts.run_natural_language_smoke import evaluate_turn_contract


def test_natural_smoke_contract_evaluates_canonical_sources_and_retrieval_phase() -> None:
    events = [
        {"type": "workflow_step", "action": "understand"},
        {"type": "workflow_step", "action": "check_evidence"},
        {
            "type": "response_complete",
            "route": "legal_lookup",
            "termination_reason": "answer_complete",
            "context_loaded": True,
            "history_messages": 2,
            "is_follow_up": True,
            "standalone_query": "Chủ đề 2026. Còn gì nữa?",
            "sources": [
                {
                    "source_id": "law-08",
                    "instrument_number": "08/2026/QH16",
                    "anchor": "Điều 1",
                }
            ],
            "documents": [
                {"document_id": "chunk-raw", "metadata": {"source_id": "law-08"}}
            ],
            "trace_id": "trace-1",
        },
    ]

    observed, failures = evaluate_turn_contract(
        events,
        {
            "route": "legal_lookup",
            "termination_reason": "answer_complete",
            "context_loaded": True,
            "history_messages": 2,
            "is_follow_up": True,
            "source_nonempty": True,
            "anchor_contains": "Điều 1",
            "instrument_contains": "08/2026/QH16",
            "retrieval_count_min": 1,
            "standalone_contains": ["2026", "còn gì nữa"],
        },
    )

    assert failures == []
    assert observed["source_ids"] == ["law-08"]
    assert observed["retrieval_count"] == 1


def test_natural_smoke_contract_reports_missing_terminal_and_empty_source_mismatch() -> None:
    observed, failures = evaluate_turn_contract(
        [{"type": "status", "stage": "understand"}],
        {"source_empty": True, "retrieval_count_exact": 0},
    )

    assert observed["sources_count"] == 0
    assert "no terminal SSE event received" in failures


def test_natural_smoke_fixture_is_multi_turn_and_deterministic() -> None:
    fixture_path = Path("data/eval/natural_language_smoke.json")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["mode"] == "deterministic"
    assert len(fixture["cases"]) == 10
    follow_up = next(item for item in fixture["cases"] if item["id"] == "follow_up_same_conversation")
    assert len(follow_up["turns"]) == 2
    assert next(item for item in fixture["cases"] if item["id"] == "bitcoin_out_of_scope")
