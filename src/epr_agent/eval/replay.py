"""Replay the real agent runtime and emit structured evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from epr_agent.agent.agent_loop import AgentRunResult, AgentStep
from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.runtime import AgentWorkflowRuntime
from epr_agent.domain.models import AgentState, DocumentRecord
from epr_agent.eval.contracts import (
    EvaluationCase,
    EvaluationResult,
    EvaluationStatus,
    ExpectedOutcome,
    FailureCode,
)
from epr_agent.eval.evidence_verifier import verify_evaluation_case
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import EvidenceGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


class ReplayRuntime(Protocol):
    def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...


class ReplayHistory:
    """In-memory history adapter for deterministic runtime replay."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        return None

    async def load(self, _user_id: str, _conversation_id: str, max_messages: int = 6) -> ContextSnapshot:
        return ContextSnapshot(history=list(self.messages[-max_messages:]), summary="", active_case=None)

    async def save_exchange(
        self,
        _user_id: str,
        _conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> int:
        self.messages.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message, "metadata": dict(metadata or {})},
            ]
        )
        return len(self.messages)

    async def begin_turn(
        self,
        _user_id: str,
        _conversation_id: str,
        _turn_id: str,
        _query: str,
        *,
        mode: str,
        operation: str,
        replay_metadata: dict[str, Any],
        target_assistant_message_id: int | None,
    ) -> dict[str, Any]:
        return {"status": "pending", "assistant_message_id": len(self.messages) + 1}

    async def update_turn_content(
        self, _user_id: str, _conversation_id: str, _turn_id: str, _content: str
    ) -> bool:
        return True

    async def is_turn_cancelled(self, _user_id: str, _conversation_id: str, _turn_id: str) -> bool:
        return False

    async def cancel_turn(self, _user_id: str, _conversation_id: str, _turn_id: str) -> dict[str, Any] | None:
        return {"status": "stopped"}

    async def finish_turn(
        self,
        _user_id: str,
        _conversation_id: str,
        _turn_id: str,
        *,
        content: str,
        metadata: dict[str, Any] | None,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "content": content,
            "metadata": metadata,
            "status": status,
            "error_code": error_code,
        }
        self.finished.append(record)
        return {"status": record.get("status", "complete"), "assistant_message_id": len(self.messages) + 1}

    async def save_case(self, _user_id: str, _conversation_id: str, _state: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def clear_case(self, _user_id: str, _conversation_id: str) -> None:
        return None

    async def get_case(self, _user_id: str, _conversation_id: str) -> dict[str, Any] | None:
        return None

    async def record_run(self, state: AgentState, _started_at: float, _ended_at: float) -> None:
        self.runs.append(dict(state))


class DeterministicReplayRunner:
    """Bounded runner double used only when replay is explicitly deterministic.

    It creates source-aligned synthetic output from the fixture contract.  It
    is a plumbing/control-flow check, not a legal opinion.  Live provider runs
    are optional evidence for latency and integration behavior, not a legal
    quality gate.
    """

    def __init__(self, case: EvaluationCase) -> None:
        self.case = case
        self._turn_index = 0

    def _result(self, expected_outcome: ExpectedOutcome | None = None) -> AgentRunResult:
        documents: list[dict[str, Any]] = []
        answer_lines: list[str] = []
        citations: list[dict[str, Any]] = []
        source_by_id = {source.source_id: source for source in self.case.sources}
        for index, claim in enumerate(self.case.claims, start=1):
            source_id = claim.source_ids[0] if claim.source_ids else ""
            source_record = source_by_id.get(source_id)
            anchor = claim.anchors[0] if claim.anchors else ""
            documents.append(
                DocumentRecord(
                    content=f"{anchor} {claim.text}".strip(),
                    document_id=source_id or f"replay-doc-{index}",
                    source="legal",
                    metadata={
                        "source_id": source_id,
                        "source_title": source_record.title if source_record else "",
                        "legal_anchor": anchor,
                        "official_url": source_record.official_url if source_record else "",
                    },
                ).to_dict()
            )
            answer_lines.append(f"{claim.text} [{index}]")
            citations.append({"index": index, "document_id": source_id or f"replay-doc-{index}", "label": anchor})

        outcome = expected_outcome or self.case.expected_outcome or ExpectedOutcome.SAFE_STOP
        if not answer_lines:
            answer = "Chưa có đủ dữ liệu nguồn trong bản replay để trả lời an toàn."
            termination = "insufficient_evidence"
            source_name = "error"
        else:
            answer = "\n".join(answer_lines)
            termination = outcome.value
            source_name = "legal"
        return AgentRunResult(
            answer=answer,
            termination_reason=termination,
            trajectory=[
                AgentStep(
                    step=1,
                    tool="search_legal_provisions",
                    args={"query": self.case.turns[0].query},
                    observation={},
                    latency_ms=0.1,
                    allowed=True,
                )
            ],
            evidence=documents,
            citations=citations,
            source=source_name,
            steps_taken=1,
            cache_hit=False,
            awaiting_user_input=outcome == ExpectedOutcome.CLARIFICATION,
        )

    async def stream(self, _query: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        trace_id = str(kwargs.get("trace_id") or "")
        turn = self.case.turns[min(self._turn_index, len(self.case.turns) - 1)]
        self._turn_index += 1
        result = self._result(turn.expected_outcome)
        yield {
            "type": "agent_tool_call",
            "step": 1,
            "tool": "search_legal_provisions",
            "args": {"query": _query},
            "trace_id": trace_id,
        }
        yield {
            "type": "agent_tool_result",
            "step": 1,
            "tool": "search_legal_provisions",
            "status": "completed",
            "latency_ms": 0.1,
            "error_code": None,
            "trace_id": trace_id,
        }
        yield {"type": "agent_complete", "result": result}

    async def run(self, _query: str, **_kwargs: Any) -> AgentRunResult:
        return self._result()


def deterministic_runtime(case: EvaluationCase) -> AgentWorkflowRuntime:
    documents = [
        DocumentRecord(
            content=f"{anchor} {claim.text}".strip(),
            document_id=source_id,
            source="legal",
            metadata={"source_id": source_id, "legal_anchor": anchor},
        )
        for claim in case.claims
        for source_id in claim.source_ids[:1]
        for anchor in claim.anchors[:1]
    ]
    deps = WorkflowDependencies(
        history=ReplayHistory(),
        cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="replay"),
        retrieval=StaticRetrievalGateway(legal_documents=documents),
        evidence=EvidenceEvaluator(min_docs=1, min_chars=1),
        generation=EvidenceGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=2, max_repairs=1, max_iterations=5),
    )
    return AgentWorkflowRuntime(
        deps,
        runner=DeterministicReplayRunner(case),
        answer_chunk_delay_s=0,
    )


def _observed_outcome(terminal: Mapping[str, Any]) -> ExpectedOutcome | None:
    termination = str(terminal.get("termination_reason") or "")
    if termination == ExpectedOutcome.ANSWER_COMPLETE.value:
        return ExpectedOutcome.ANSWER_COMPLETE
    if termination == ExpectedOutcome.CLARIFICATION.value or termination == "awaiting_user_input":
        return ExpectedOutcome.CLARIFICATION
    if termination or terminal.get("type") in {"response_stopped", "error"}:
        return ExpectedOutcome.SAFE_STOP
    return None


def _terminal(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        (
            event
            for event in reversed(events)
            if event.get("type") in {"response_complete", "response_stopped", "error"}
        ),
        {},
    )


def _case_for_turn(case: EvaluationCase, turn_index: int) -> EvaluationCase:
    """Project case-level claims/outcome onto the turn being verified."""

    turn = case.turns[turn_index - 1]
    is_final_turn = turn_index == len(case.turns)
    expected_claim_ids = set(turn.expected_claim_ids)
    if expected_claim_ids:
        claims = [claim for claim in case.claims if claim.claim_id in expected_claim_ids]
    elif is_final_turn or len(case.turns) == 1:
        claims = list(case.claims)
    else:
        claims = []

    claim_ids = {claim.claim_id for claim in claims}
    citations = [citation for citation in case.citations if citation.claim_id in claim_ids]
    source_ids = {
        source_id
        for claim in claims
        for source_id in claim.source_ids
    }
    source_ids.update(citation.source_id for citation in citations)
    sources = (
        list(case.sources)
        if is_final_turn and not expected_claim_ids and not claims
        else [source for source in case.sources if source.source_id in source_ids]
    )
    expected_outcome = turn.expected_outcome if turn.expected_outcome is not None else (
        case.expected_outcome if is_final_turn else None
    )
    return case.model_copy(
        update={
            "turns": [turn],
            "expected_outcome": expected_outcome,
            "claims": claims,
            "sources": sources,
            "citations": citations,
        }
    )


async def replay_case(
    runtime: ReplayRuntime,
    case: EvaluationCase,
    *,
    mode: str,
    user_id: str = "evaluation",
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Run all turns in one case and return a JSON-serialisable report."""

    conversation_id = conversation_id or f"eval-{case.case_id.lower()}-{uuid.uuid4().hex[:12]}"
    turn_reports: list[dict[str, Any]] = []
    final_terminal: dict[str, Any] = {}
    final_documents: list[Mapping[str, Any]] = []
    final_drawer: list[Mapping[str, Any]] = []
    turn_results: list[EvaluationResult] = []
    started = time.perf_counter()

    for turn_index, turn in enumerate(case.turns, start=1):
        trace_id = str(uuid.uuid4())
        turn_started = time.perf_counter()
        events: list[dict[str, Any]] = []
        async for event in runtime.stream(
            query=turn.query,
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=f"{conversation_id}-turn-{turn_index}",
            mode="auto",
            operation="message" if turn_index == 1 else "continue_case",
            trace_id=trace_id,
            replay_metadata={"case_id": case.case_id, "turn_index": turn_index, "mode": mode},
        ):
            events.append(dict(event))
        terminal = _terminal(events)
        documents = [item for item in terminal.get("documents") or [] if isinstance(item, Mapping)]
        raw_drawer = terminal.get("sources")
        drawer = [item for item in raw_drawer or [] if isinstance(item, Mapping)]
        turn_case = _case_for_turn(case, turn_index)
        turn_result = verify_evaluation_case(
            turn_case,
            answer=str(terminal.get("text") or ""),
            documents=documents,
            source_drawer_documents=drawer,
            observed_outcome=_observed_outcome(terminal),
        )
        turn_results.append(turn_result)
        final_terminal = terminal
        final_documents = documents
        final_drawer = drawer
        turn_reports.append(
            {
                "turn_index": turn_index,
                "query": turn.query,
                "trace_id": str(terminal.get("trace_id") or trace_id),
                "terminal_type": str(terminal.get("type") or "missing"),
                "termination_reason": str(terminal.get("termination_reason") or ""),
                "observed_outcome": (_observed_outcome(terminal) or ""),
                "latency_ms": round((time.perf_counter() - turn_started) * 1000, 2),
                "events": events,
                "tool_trajectory": [
                    {
                        key: event.get(key)
                        for key in ("type", "step", "tool", "status", "latency_ms", "error_code")
                        if key in event
                    }
                    for event in events
                    if event.get("type") in {"agent_tool_call", "agent_tool_result", "workflow_step"}
                ],
                "documents": documents,
                "source_drawer": drawer,
                "source_drawer_present": isinstance(raw_drawer, list),
                "errors": [event for event in events if event.get("type") == "error"],
                "evaluation": turn_result.model_dump(mode="json"),
            }
        )

    final_case = _case_for_turn(case, len(case.turns))
    result = verify_evaluation_case(
        final_case,
        answer=str(final_terminal.get("text") or ""),
        documents=final_documents,
        source_drawer_documents=final_drawer,
        observed_outcome=_observed_outcome(final_terminal),
    )
    failure_codes = list(result.failure_codes)
    if not final_terminal:
        failure_codes.append(FailureCode.PROVIDER_UNAVAILABLE if mode == "live" else FailureCode.SOURCE_PROVENANCE_LOSS)
    if any(event.get("type") == "error" for report in turn_reports for event in report["events"]):
        failure_codes.append(FailureCode.PROVIDER_UNAVAILABLE if mode == "live" else FailureCode.SOURCE_PROVENANCE_LOSS)
    for turn_result in turn_results:
        failure_codes.extend(turn_result.failure_codes)
    unique_failure_codes = list(dict.fromkeys(failure_codes))
    result = result.model_copy(
        update={
            "status": EvaluationStatus.FAIL if unique_failure_codes else result.status,
            "gate_eligible": result.gate_eligible and all(item.gate_eligible for item in turn_results),
            "failure_codes": unique_failure_codes,
            "metadata": {
                **result.metadata,
                "turn_count": len(turn_reports),
                "turn_failures": [
                    code.value
                    for item in turn_results
                    for code in item.failure_codes
                ],
            },
        }
    )
    report = {
        "schema_version": "evaluation-replay-v1",
        "case_id": case.case_id,
        "mode": mode,
        "conversation_id": conversation_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": git_commit_sha(),
        "corpus_sha": str(final_terminal.get("corpus_sha") or ""),
        "pipeline_version": str(final_terminal.get("pipeline_version") or "pipeline-agent"),
        "model_id": os.getenv("OPENAI_MODEL", "configured"),
        "config_hash": config_hash(mode=mode, case=case),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "turns": turn_reports,
        "turn_results": [item.model_dump(mode="json") for item in turn_results],
        "result": result.model_dump(mode="json"),
    }
    return report


def config_hash(*, mode: str, case: EvaluationCase) -> str:
    payload = {"mode": mode, "case_id": case.case_id, "turn_count": len(case.turns), "pipeline": "pipeline-agent"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def git_commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def load_cases(path: str | Path) -> list[EvaluationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        raw_cases = payload["cases"]
    else:
        raw_cases = [payload]
    return [EvaluationCase.model_validate(item) for item in raw_cases]


def write_report(path: str | Path, reports: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "evaluation-replay-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": len(reports),
        "gate_eligible": sum(bool(report["result"].get("gate_eligible")) for report in reports),
        "passed": sum(report["result"].get("status") == EvaluationStatus.PASS.value for report in reports),
        "informational": sum(report["result"].get("status") == EvaluationStatus.INFORMATIONAL.value for report in reports),
        "reports": reports,
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
