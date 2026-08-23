from __future__ import annotations

import pytest

from epr_agent.agent.agent_loop import AgentRunResult
from epr_agent.agent.graph import WorkflowDependencies, run_workflow
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.runtime import AgentWorkflowRuntime
from epr_agent.domain.models import DocumentRecord, TerminationReason
from epr_agent.domain.tasks import deterministic_task_understanding, rewrite_follow_up
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


class MemoryHistory:
    def __init__(self, history: list[dict[str, object]] | None = None) -> None:
        self.history = history or []
        self.saved_exchanges: list[tuple] = []

    async def initialize(self) -> None:
        return None

    async def load(self, _user_id: str, _conversation_id: str, max_messages: int) -> ContextSnapshot:
        return ContextSnapshot(self.history[-max_messages:], None, "")

    async def save_exchange(self, *args, **kwargs) -> int:
        self.saved_exchanges.append((args, kwargs))
        return len(self.saved_exchanges)

    async def save_case(self, *args, **kwargs) -> dict:
        return {}

    async def clear_case(self, *args, **kwargs) -> None:
        return None

    async def record_run(self, *args, **kwargs) -> None:
        return None


class CapturingRunner:
    def __init__(self, result: AgentRunResult) -> None:
        self.result = result
        self.queries: list[str] = []

    async def stream(self, query: str, **kwargs):
        self.queries.append(query)
        yield {"type": "agent_complete", "result": self.result}


class FailingRunner:
    async def stream(self, query: str, **kwargs):
        raise AssertionError("a context-only follow-up must be clarified before the agent loop")
        yield  # pragma: no cover


def _deps(history: MemoryHistory, retrieval: StaticRetrievalGateway | None = None) -> WorkflowDependencies:
    return WorkflowDependencies(
        history=history,  # type: ignore[arg-type]
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=retrieval or StaticRetrievalGateway(),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=2, max_repairs=1),
    )


def _document() -> DocumentRecord:
    return DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế bao bì của nhà sản xuất, nhập khẩu. " * 4,
        document_id="law-77",
        source="legal",
        score=0.9,
        metadata={"legal_anchor": "Điều 77", "source": "Nghị định 08/2022/NĐ-CP"},
    )


@pytest.mark.parametrize("query", ["còn gìk", "còn gì", "còn luật nào nữa"])
def test_follow_up_rewrite_uses_prior_answer_and_canonical_sources(query: str) -> None:
    history: list[dict[str, object]] = [
        {"role": "user", "content": "2026 có luật gì mới k"},
        {
            "role": "assistant",
            "content": "Luật số 08/2026/QH16 đã được kiểm tra [1].",
            "metadata": {
                "sources": [
                    {
                        "source_id": "law-08-2026",
                        "instrument_number": "08/2026/QH16",
                        "title": "Luật số 08/2026/QH16",
                    }
                ]
            },
        },
    ]

    rewritten = rewrite_follow_up(query, history, None)

    assert "2026 có luật gì mới" in rewritten
    assert query in rewritten
    assert "08/2026/QH16" in rewritten
    assert "khác với những mục đã nêu" in rewritten


def test_full_instrument_follow_up_can_stand_alone() -> None:
    assert deterministic_task_understanding("còn Luật số 08/2026/QH16?", [], None).is_follow_up is False


def test_context_only_follow_up_is_marked_even_without_history() -> None:
    plan = deterministic_task_understanding("còn gìk", [], None)

    assert plan.is_follow_up is True
    assert plan.standalone_query == "còn gìk"


def test_continuation_question_without_particle_uses_previous_legal_topic() -> None:
    history: list[dict[str, object]] = [
        {"role": "user", "content": "2026 có luật gì mới k"},
        {"role": "assistant", "content": "Đã kiểm tra các văn bản năm 2026."},
    ]

    rewritten = rewrite_follow_up("có nghị định nào không", history, None)

    assert rewritten != "có nghị định nào không"
    assert "2026 có luật gì mới" in rewritten


@pytest.mark.asyncio
async def test_bounded_workflow_clarifies_context_only_follow_up() -> None:
    retrieval = StaticRetrievalGateway(legal_documents=[_document()])
    state = await run_workflow(
        "còn gìk",
        user_id="u1",
        conversation_id="new-conversation",
        deps=_deps(MemoryHistory(), retrieval),
    )

    assert state["termination_reason"] == TerminationReason.AWAITING_USER_INPUT.value
    assert state["source"] == "follow_up"
    assert state["clarification_required"] is True
    assert retrieval.calls == []


@pytest.mark.asyncio
async def test_agent_runtime_rewrites_existing_follow_up_before_runner() -> None:
    history_data: list[dict[str, object]] = [
        {"role": "user", "content": "2026 có luật gì mới k"},
        {
            "role": "assistant",
            "content": "Luật số 08/2026/QH16 [1].",
            "metadata": {"sources": [{"instrument_number": "08/2026/QH16"}]},
        },
    ]
    history = MemoryHistory(
        history_data
    )
    result = AgentRunResult(
        answer="Điều 77 quy định trách nhiệm tái chế [1].",
        termination_reason=TerminationReason.ANSWER_COMPLETE.value,
        trajectory=[],
        evidence=[_document().to_dict()],
        citations=[],
        source="legal",
        steps_taken=1,
        cache_hit=False,
    )
    runner = CapturingRunner(result)
    runtime = AgentWorkflowRuntime(_deps(history), runner=runner, answer_chunk_delay_s=0)

    events = [
        event
        async for event in runtime.stream(
            query="còn gìk",
            user_id="u1",
            conversation_id="existing-conversation",
        )
    ]

    complete = next(event for event in events if event["type"] == "response_complete")
    assert runner.queries and "2026 có luật gì mới" in runner.queries[0]
    assert "08/2026/QH16" in runner.queries[0]
    assert complete["is_follow_up"] is True
    assert complete["context_loaded"] is True
    assert complete["history_messages"] == 2
    assert "còn gìk" in complete["standalone_query"]
    assert complete["documents"][0]["metadata"]["source_id"] == "law-77"


@pytest.mark.asyncio
async def test_agent_runtime_rejects_legal_answer_without_evidence() -> None:
    history = MemoryHistory()
    result = AgentRunResult(
        answer="Tôi không có thông tin cụ thể về luật mới năm 2026.",
        termination_reason=TerminationReason.ANSWER_COMPLETE.value,
        trajectory=[],
        evidence=[],
        citations=[],
        source="legal",
        steps_taken=0,
        cache_hit=False,
    )
    runtime = AgentWorkflowRuntime(_deps(history), runner=CapturingRunner(result), answer_chunk_delay_s=0)

    events = [
        event
        async for event in runtime.stream(
            query="2026 có luật gì mới k",
            user_id="u1",
            conversation_id="no-evidence",
        )
    ]

    complete = next(event for event in events if event["type"] == "response_complete")
    assert complete["source"] == "error"
    assert complete["termination_reason"] == TerminationReason.CITATION_VERIFICATION_FAILED.value
    assert "chưa tìm đủ căn cứ pháp lý" in complete["text"]


@pytest.mark.asyncio
async def test_agent_runtime_clarifies_context_only_query_in_new_conversation() -> None:
    history = MemoryHistory()
    runtime = AgentWorkflowRuntime(_deps(history), runner=FailingRunner(), answer_chunk_delay_s=0)

    events = [
        event
        async for event in runtime.stream(
            query="còn gìk",
            user_id="u1",
            conversation_id="new-agent-conversation",
        )
    ]

    complete = next(event for event in events if event["type"] == "response_complete")
    assert complete["source"] == "follow_up"
    assert complete["awaiting_user_input"] is True
    assert complete["is_follow_up"] is True
    assert history.saved_exchanges
