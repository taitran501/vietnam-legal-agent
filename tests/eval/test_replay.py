"""Runtime replay and structured artifact tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from epr_agent.eval.contracts import (
    AuditedEvalCase,
    AuditStatus,
    AuthoritativeSource,
    EvalTurn,
    EvaluationStatus,
    ExpectedCitation,
    ExpectedClaim,
    ExpectedOutcome,
)
from epr_agent.eval.replay import replay_case, write_report


class FakeReplayRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream(self, **kwargs: Any):
        self.calls.append(dict(kwargs))
        trace_id = str(kwargs["trace_id"])
        documents = [
            {
                "source_id": "law-1",
                "document_id": "chunk-1",
                "anchor": "Điều 1",
                "official_url": "https://example.gov.vn/law-1",
                "page_content": "Điều 1 quy định thời hạn 10 ngày.",
            }
        ]
        yield {"type": "status", "stage": "load_context", "trace_id": trace_id}
        yield {
            "type": "agent_tool_result",
            "step": 1,
            "tool": "search_legal_provisions",
            "status": "completed",
            "latency_ms": 1.0,
            "trace_id": trace_id,
        }
        yield {
            "type": "response_complete",
            "text": "Theo Điều 1, thời hạn là 10 ngày [1].",
            "documents": documents,
            "sources": documents,
            "termination_reason": "answer_complete",
            "pipeline_version": "pipeline-agent",
            "trace_id": trace_id,
            "corpus_sha": "sha-test",
        }


def _case() -> AuditedEvalCase:
    return AuditedEvalCase(
        case_id="REPLAY-001",
        turns=[EvalTurn(query="Quy định gì?"), EvalTurn(query="Còn gì nữa?")],
        expected_outcome=ExpectedOutcome.ANSWER_COMPLETE,
        claims=[
            ExpectedClaim(
                claim_id="claim-1",
                text="Thời hạn là 10 ngày.",
                source_ids=["law-1"],
                anchors=["Điều 1"],
                match_terms=["10 ngày"],
            )
        ],
        sources=[
            AuthoritativeSource(
                source_id="law-1",
                official_url="https://example.gov.vn/law-1",
                anchors=["Điều 1"],
                corpus_sha="sha-test",
            )
        ],
        citations=[ExpectedCitation(claim_id="claim-1", source_id="law-1", anchor="Điều 1", citation_index=1)],
        audit={
            "status": AuditStatus.AUDITED,
            "audited_by": "test",
            "audited_at": "2026-08-25",
            "corpus_sha": "sha-test",
        },
    )


@pytest.mark.asyncio
async def test_replay_preserves_multi_turn_conversation_and_source_artifacts() -> None:
    runtime = FakeReplayRuntime()
    report = await replay_case(runtime, _case(), mode="deterministic", conversation_id="conversation-1")

    assert len(runtime.calls) == 2
    assert runtime.calls[0]["conversation_id"] == runtime.calls[1]["conversation_id"] == "conversation-1"
    assert runtime.calls[1]["operation"] == "continue_case"
    assert len(report["turns"]) == 2
    assert report["turns"][0]["tool_trajectory"][0]["tool"] == "search_legal_provisions"
    assert report["result"]["status"] == EvaluationStatus.PASS.value
    assert report["result"]["source_results"][0]["source_id"] == "law-1"
    assert report["pipeline_version"] == "pipeline-agent"


@pytest.mark.asyncio
async def test_replay_pending_case_is_reported_as_informational() -> None:
    from epr_agent.eval.replay import deterministic_runtime, load_cases

    case = load_cases(Path("data/eval/audited/2026-law-follow-up.json"))[0]
    report = await replay_case(deterministic_runtime(case), case, mode="deterministic")
    assert report["result"]["status"] == EvaluationStatus.INFORMATIONAL.value
    assert report["result"]["gate_eligible"] is False


def test_write_report_is_json_serialisable(tmp_path: Path) -> None:
    output = tmp_path / "replay.json"
    write_report(output, [{"result": {"status": "informational", "gate_eligible": False}}])
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["cases"] == 1
    assert payload["informational"] == 1
