"""Unit tests for AgentWorkflowRuntime."""

from __future__ import annotations

import asyncio

import pytest

from epr_agent.agent.agent_loop import AgentRunResult, AgentStep
from epr_agent.agent.runtime import AgentWorkflowRuntime, WorkflowDependencies, get_default_runtime
from epr_agent.domain.models import DocumentRecord, TerminationReason
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.history import ContextSnapshot, HistoryGateway
from epr_agent.tools.retrieval import StaticRetrievalGateway


class FakeHistory(HistoryGateway):
    def __init__(self) -> None:
        self.exchanges: list[tuple] = []

    async def initialize(self) -> None: pass
    async def load(self, user_id: str, conversation_id: str, max_messages: int = 6) -> ContextSnapshot:
        return ContextSnapshot(history=[], summary="", active_case=None)
    async def save_exchange(self, user_id, conversation_id, query, answer, metadata=None) -> int:
        self.exchanges.append((user_id, conversation_id, query, answer))
        return 1
    async def save_case(self, *args, **kwargs) -> dict: return {}
    async def clear_case(self, *args, **kwargs) -> None: pass
    async def record_run(self, *args, **kwargs) -> None: pass


class FakeGen:
    async def chitchat(self, query: str, history: list) -> str: return "Xin chào! Tôi có thể giúp gì về EPR?"
    async def answer(self, *args, **kwargs) -> str: return "Câu trả lời"
    async def web(self, *args, **kwargs) -> tuple: return "web", []
    async def repair(self, *args, **kwargs) -> str: return ""


class FakeCache:
    async def lookup(self, *args, **kwargs): return None, "key"
    async def store(self, *args, **kwargs): pass


class FakeRunner:
    def __init__(self, result: AgentRunResult) -> None:
        self.result = result

    async def stream(self, query: str, **kwargs):
        yield {
            "type": "agent_tool_call",
            "step": 1,
            "tool": "search_legal_provisions",
            "args": {"query": query},
            "trace_id": kwargs.get("trace_id", ""),
        }
        yield {
            "type": "agent_tool_result",
            "step": 1,
            "tool": "search_legal_provisions",
            "status": "completed",
            "latency_ms": 10.0,
            "error_code": None,
            "trace_id": kwargs.get("trace_id", ""),
        }
        yield {
            "type": "agent_complete",
            "result": self.result,
        }

    async def run(self, query: str, **kwargs) -> AgentRunResult:
        return self.result


@pytest.fixture
def agent_deps():
    sample_doc = DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế bao bì của nhà sản xuất, nhập khẩu theo luật môi trường.",
        document_id="doc-1",
        score=0.9,
        source="legal",
        metadata={"legal_anchor": "Điều 77", "source": "Luật BVMT 2020"},
    )
    history = FakeHistory()
    deps = WorkflowDependencies(
        history=history,
        cache=FakeCache(),  # type: ignore[arg-type]
        retrieval=StaticRetrievalGateway(legal_documents=[sample_doc]),
        evidence=EvidenceEvaluator(min_docs=1, min_chars=10),
        generation=FakeGen(),  # type: ignore[arg-type]
        planner=None,  # type: ignore[arg-type]
    )
    return deps


@pytest.mark.asyncio
async def test_agent_runtime_input_validation(agent_deps):
    runtime = AgentWorkflowRuntime(agent_deps)
    events = []
    async for e in runtime.stream(query="", user_id="u1", conversation_id="c1"):
        events.append(e)

    assert any(e.get("type") == "response_complete" and e.get("termination_reason") == "invalid_input" for e in events)


@pytest.mark.asyncio
async def test_agent_runtime_chitchat_bypass(agent_deps):
    runtime = AgentWorkflowRuntime(agent_deps)
    events = []
    async for e in runtime.stream(query="Xin chào bạn", user_id="u1", conversation_id="c1"):
        events.append(e)

    complete_event = next(e for e in events if e.get("type") == "response_complete")
    assert complete_event["source"] == "chitchat"
    assert "Xin chào" in complete_event["text"]
    assert complete_event["pipeline_version"] == "pipeline-agent"


@pytest.mark.asyncio
async def test_agent_runtime_out_of_scope_bypass(agent_deps):
    runtime = AgentWorkflowRuntime(agent_deps)
    events = []
    async for e in runtime.stream(query="Cách nấu phở bò gia truyền", user_id="u1", conversation_id="c1"):
        events.append(e)

    complete_event = next(e for e in events if e.get("type") == "response_complete")
    assert complete_event["termination_reason"] == "out_of_scope"
    assert "ngoài phạm vi" in complete_event["text"]


@pytest.mark.asyncio
async def test_agent_runtime_successful_stream(agent_deps):
    doc = DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế bao bì của nhà sản xuất, nhập khẩu theo luật môi trường.",
        document_id="doc-1",
        metadata={"legal_anchor": "Điều 77", "source": "Luật BVMT 2020"},
    )
    result = AgentRunResult(
        answer="Trách nhiệm tái chế được quy định tại Điều 77 [1].",
        termination_reason=TerminationReason.ANSWER_COMPLETE.value,
        trajectory=[AgentStep(1, "search_legal_provisions", {"query": "Điều 77"}, {}, 10.0, True)],
        evidence=[doc.to_dict()],
        citations=[{"index": 1, "document_id": "doc-1", "label": "Điều 77"}],
        source="legal",
        steps_taken=2,
        cache_hit=False,
    )
    fake_runner = FakeRunner(result)
    runtime = AgentWorkflowRuntime(agent_deps, runner=fake_runner)

    events = []
    async for e in runtime.stream(query="Điều 77 quy định gì?", user_id="u1", conversation_id="c1"):
        events.append(e)

    # Verify event stream structure
    assert any(e.get("type") == "workflow_step" for e in events)
    assert any(e.get("type") == "response_chunk" for e in events)
    complete = next(e for e in events if e.get("type") == "response_complete")
    assert complete["pipeline_version"] == "pipeline-agent"
    assert "[1]" in complete["text"]
    assert len(complete["documents"]) == 1


@pytest.mark.asyncio
async def test_agent_runtime_regenerate_empty_query_recovery(agent_deps):
    # Setup history with prior user query
    class HistoryWithPriorTurn(FakeHistory):
        async def load(self, user_id: str, conversation_id: str, max_messages: int = 6) -> ContextSnapshot:
            return ContextSnapshot(
                history=[{"role": "user", "content": "Thời gian thử việc tối đa là bao lâu?"}],
                summary="",
                active_case=None,
            )

    deps_with_history = WorkflowDependencies(
        history=HistoryWithPriorTurn(),
        cache=agent_deps.cache,
        retrieval=agent_deps.retrieval,
        evidence=agent_deps.evidence,
        generation=agent_deps.generation,
        planner=agent_deps.planner,
    )

    doc = DocumentRecord(
        content="Điều 25 Bộ luật Lao động 2019: Thời gian thử việc tối đa 60 ngày đối với công việc có chức danh nghề nghiệp cần trình độ chuyên môn...",
        document_id="doc-25",
        metadata={"legal_anchor": "Điều 25", "source": "Bộ luật Lao động 2019"},
    )
    result = AgentRunResult(
        answer="Thời gian thử việc tối đa là 60 ngày theo Điều 25 [1].",
        termination_reason=TerminationReason.ANSWER_COMPLETE.value,
        trajectory=[AgentStep(1, "search_legal_provisions", {"query": "thử việc"}, {}, 10.0, True)],
        evidence=[doc.to_dict()],
        citations=[{"index": 1, "document_id": "doc-25", "label": "Điều 25"}],
        source="legal",
        steps_taken=1,
        cache_hit=False,
    )
    fake_runner = FakeRunner(result)
    runtime = AgentWorkflowRuntime(deps_with_history, runner=fake_runner)

    # Calling stream with query="" and operation="regenerate"
    events = []
    async for e in runtime.stream(
        query="",
        user_id="u1",
        conversation_id="c1",
        operation="regenerate",
    ):
        events.append(e)

    complete = next(e for e in events if e.get("type") == "response_complete")
    assert complete["termination_reason"] == "answer_complete"
    assert "Thời gian thử việc" in complete["text"] or "[1]" in complete["text"]


@pytest.mark.asyncio
async def test_get_default_runtime_feature_flag(monkeypatch):
    from epr_agent.config import get_settings

    get_default_runtime.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_pipeline_version", "pipeline-agent")

    runtime = get_default_runtime()
    assert runtime.__class__.__name__ == "AgentWorkflowRuntime"
    get_default_runtime.cache_clear()


@pytest.mark.asyncio
async def test_agent_runtime_reports_tool_completion_after_result(agent_deps):
    result = AgentRunResult(
        answer="Không đủ căn cứ.",
        termination_reason=TerminationReason.INSUFFICIENT_EVIDENCE.value,
        trajectory=[AgentStep(1, "search_legal_provisions", {}, {}, 12.5, True)],
        evidence=[],
        citations=[],
        source="error",
        steps_taken=1,
        cache_hit=False,
    )
    events = [
        event
        async for event in AgentWorkflowRuntime(agent_deps, runner=FakeRunner(result)).stream(
            query="Điều luật nào áp dụng?", user_id="u1", conversation_id="c1"
        )
    ]

    status_index = next(i for i, event in enumerate(events) if event.get("type") == "status" and event.get("stage") == "search_legal_provisions")
    step_index = next(i for i, event in enumerate(events) if event.get("type") == "workflow_step")
    assert status_index < step_index
    assert events[step_index]["status"] == "completed"
    assert events[step_index]["latency_ms"] == 10.0


@pytest.mark.asyncio
async def test_agent_runtime_durable_cancellation_wins_over_completion(agent_deps):
    class CancelledHistory(FakeHistory):
        def __init__(self) -> None:
            super().__init__()
            self.finished: list[dict] = []

        async def begin_turn(self, *args, **kwargs) -> dict:
            return {"status": "pending", "assistant_message_id": 1}

        async def is_turn_cancelled(self, *args, **kwargs) -> bool:
            return True

        async def finish_turn(self, *args, **kwargs) -> dict:
            self.finished.append(kwargs)
            return {"status": "stopped", "assistant_message_id": 1}

    history = CancelledHistory()
    deps = WorkflowDependencies(
        history=history,
        cache=agent_deps.cache,
        retrieval=agent_deps.retrieval,
        evidence=agent_deps.evidence,
        generation=agent_deps.generation,
        planner=agent_deps.planner,
    )
    result = AgentRunResult(
        answer="Câu trả lời muộn.",
        termination_reason="user_cancelled",
        trajectory=[], evidence=[], citations=[], source="error", steps_taken=0, cache_hit=False,
    )
    events = [
        event
        async for event in AgentWorkflowRuntime(deps, runner=FakeRunner(result)).stream(
            query="Điều luật nào áp dụng?",
            user_id="u1",
            conversation_id="c1",
            turn_id="turn-1",
        )
    ]

    assert any(event.get("type") == "response_stopped" for event in events)
    assert not any(event.get("type") == "response_complete" for event in events)
    assert history.finished[-1]["status"] == "stopped"


@pytest.mark.asyncio
async def test_agent_runtime_storage_failure_is_visible(agent_deps):
    class FailingHistory(FakeHistory):
        async def save_exchange(self, *args, **kwargs) -> int:
            raise OSError("database unavailable")

    deps = WorkflowDependencies(
        history=FailingHistory(),
        cache=agent_deps.cache,
        retrieval=agent_deps.retrieval,
        evidence=agent_deps.evidence,
        generation=agent_deps.generation,
        planner=agent_deps.planner,
    )
    result = AgentRunResult(
        answer="Không đủ căn cứ.",
        termination_reason=TerminationReason.INSUFFICIENT_EVIDENCE.value,
        trajectory=[], evidence=[], citations=[], source="error", steps_taken=1, cache_hit=False,
    )
    events = [
        event
        async for event in AgentWorkflowRuntime(deps, runner=FakeRunner(result)).stream(
            query="Điều luật nào áp dụng?", user_id="u1", conversation_id="c1"
        )
    ]

    assert any(event.get("type") == "error" and event.get("code") == "storage_unavailable" for event in events)
    assert not any(event.get("type") == "response_complete" for event in events)


class DurableHistory(FakeHistory):
    def __init__(self) -> None:
        super().__init__()
        self.finished: list[dict] = []

    async def begin_turn(self, *args, **kwargs) -> dict:
        return {"status": "pending", "assistant_message_id": 1}

    async def is_turn_cancelled(self, *args, **kwargs) -> bool:
        return False

    async def finish_turn(self, *args, **kwargs) -> dict:
        self.finished.append(kwargs)
        return {"status": kwargs["status"], "assistant_message_id": 1}


def _deps_with_history(agent_deps, history: FakeHistory) -> WorkflowDependencies:
    return WorkflowDependencies(
        history=history,
        cache=agent_deps.cache,
        retrieval=agent_deps.retrieval,
        evidence=agent_deps.evidence,
        generation=agent_deps.generation,
        planner=agent_deps.planner,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "termination_reason"),
    [
        ("", "invalid_input"),
        ("Xin chào bạn", "answer_complete"),
        ("Cách nấu phở bò gia truyền", "out_of_scope"),
    ],
)
async def test_agent_runtime_fast_paths_use_durable_turn_contract(
    agent_deps, query: str, termination_reason: str
) -> None:
    history = DurableHistory()
    events = [
        event
        async for event in AgentWorkflowRuntime(_deps_with_history(agent_deps, history)).stream(
            query=query,
            user_id="u1",
            conversation_id="c1",
            turn_id=f"turn-{termination_reason}",
        )
    ]

    assert any(
        event.get("type") == "response_complete"
        and event.get("termination_reason") == termination_reason
        for event in events
    )
    assert history.finished[-1]["status"] == "complete"
    assert history.exchanges == []


@pytest.mark.asyncio
async def test_agent_runtime_cancellation_storage_failure_is_visible(agent_deps) -> None:
    class FailingCancelledHistory(DurableHistory):
        async def is_turn_cancelled(self, *args, **kwargs) -> bool:
            return True

        async def finish_turn(self, *args, **kwargs) -> dict:
            raise OSError("storage unavailable")

    result = AgentRunResult(
        answer="Câu trả lời muộn.",
        termination_reason="user_cancelled",
        trajectory=[],
        evidence=[],
        citations=[],
        source="error",
        steps_taken=0,
        cache_hit=False,
    )
    events = [
        event
        async for event in AgentWorkflowRuntime(
            _deps_with_history(agent_deps, FailingCancelledHistory()),
            runner=FakeRunner(result),
        ).stream(
            query="Điều luật nào áp dụng?",
            user_id="u1",
            conversation_id="c1",
            turn_id="turn-cancelled",
        )
    ]

    assert any(
        event.get("type") == "error" and event.get("code") == "storage_unavailable"
        for event in events
    )
    assert not any(event.get("type") == "response_stopped" for event in events)


@pytest.mark.asyncio
async def test_agent_runtime_disconnect_finalizes_pending_turn(agent_deps) -> None:
    class BlockingRunner:
        async def stream(self, query: str, **kwargs):
            yield {
                "type": "agent_tool_call",
                "step": 1,
                "tool": "search_legal_provisions",
                "args": {"query": query},
            }
            await asyncio.Event().wait()

    history = DurableHistory()
    stream = AgentWorkflowRuntime(
        _deps_with_history(agent_deps, history), runner=BlockingRunner()
    ).stream(
        query="Điều 77 quy định gì?",
        user_id="u1",
        conversation_id="c1",
        turn_id="turn-disconnect",
    )

    while True:
        event = await anext(stream)
        if event.get("stage") == "search_legal_provisions":
            break
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await stream.aclose()

    assert history.finished[-1]["status"] == "stopped"
    assert history.finished[-1]["error_code"] == "client_disconnected"


@pytest.mark.asyncio
async def test_agent_runtime_unhandled_failure_finalizes_failed_turn(agent_deps) -> None:
    class FailingRunner:
        async def stream(self, query: str, **kwargs):
            if False:
                yield {"query": query}
            raise RuntimeError("runner crashed")

    history = DurableHistory()
    runtime = AgentWorkflowRuntime(
        _deps_with_history(agent_deps, history), runner=FailingRunner()
    )

    with pytest.raises(RuntimeError, match="runner crashed"):
        async for _event in runtime.stream(
            query="Điều 77 quy định gì?",
            user_id="u1",
            conversation_id="c1",
            turn_id="turn-failed",
        ):
            pass

    assert history.finished[-1]["status"] == "failed"
    assert history.finished[-1]["error_code"] == "stream_incomplete"


def test_cited_evidence_indices_ignores_out_of_range_bracketed_numbers():
    from epr_agent.agent.runtime import _cited_evidence_indices

    evidence = [{"document_id": "d1"}, {"document_id": "d2"}, {"document_id": "d3"}]
    # "[2023]" is a year, not a citation; only [2] points at an evidence item.
    assert _cited_evidence_indices("Nghị định [2023] tại Điều 78 [2].", evidence) == {2}
    assert _cited_evidence_indices("Không có trích dẫn.", evidence) == set()
    assert _cited_evidence_indices("", []) == set()


def test_documents_for_api_keeps_sources_when_answer_has_non_citation_brackets():
    from epr_agent.agent.runtime import _documents_for_api

    evidence = [
        {"document_id": "d1", "content": "Nội dung 1", "metadata": {"legal_anchor": "Điều 77"}},
        {"document_id": "d2", "content": "Nội dung 2", "metadata": {"legal_anchor": "Điều 78"}},
    ]
    state = {
        "answer": "Theo Nghị định 08/2022/NĐ-CP [2023], quy định tại Điều 78 [2].",
        "evidence": evidence,
    }
    documents = _documents_for_api(state)
    assert [doc["document_id"] for doc in documents] == ["d2"]


def test_source_snapshots_keeps_sources_when_answer_has_non_citation_brackets():
    from epr_agent.agent.runtime import _source_snapshots

    evidence = [
        {"document_id": "d1", "content": "Nội dung 1", "metadata": {"legal_anchor": "Điều 77", "Source_Title": "Luật BVMT 2020"}},
        {"document_id": "d2", "content": "Nội dung 2", "metadata": {"legal_anchor": "Điều 78", "Source_Title": "Nghị định 08/2022/NĐ-CP"}},
    ]
    state = {
        "answer": "Theo Nghị định 08/2022/NĐ-CP [2023], quy định tại Điều 78 [2].",
        "evidence": evidence,
    }
    snapshots = _source_snapshots(state)
    assert [snapshot["source_id"] for snapshot in snapshots] == ["d2"]
