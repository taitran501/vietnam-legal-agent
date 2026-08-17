"""Unit tests for EprAgentRunner cognitive loop."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from epr_agent.agent.agent_loop import AgentRunConfig, EprAgentRunner
from epr_agent.agent.tool_registry import ToolDependencies, set_tool_dependencies
from epr_agent.domain.epr_rules import CaseFormResolver
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import CachedAnswer
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.history import ContextSnapshot, HistoryGateway
from epr_agent.tools.retrieval import StaticRetrievalGateway


class FakeHistory(HistoryGateway):
    async def initialize(self) -> None: pass
    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot:
        return ContextSnapshot(history=[], summary="", active_case=None)
    async def save_exchange(self, *args, **kwargs) -> int: return 1
    async def save_case(self, *args, **kwargs) -> dict: return {}
    async def clear_case(self, *args, **kwargs) -> None: pass
    async def record_run(self, *args, **kwargs) -> None: pass


class FakeGen:
    async def chitchat(self, *args, **kwargs) -> str: return "Xin chào"
    async def answer(self, *args, **kwargs) -> str: return "Câu trả lời"
    async def web(self, *args, **kwargs) -> tuple: return "web", []
    async def repair(self, *args, **kwargs) -> str: return ""


class FakeCache:
    async def lookup(self, *args, **kwargs): return None, "key"
    async def store(self, *args, **kwargs): pass


class MockSequenceLLM:
    """Mock LLM returning a programmed sequence of AIMessage responses."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def ainvoke(self, messages: list) -> AIMessage:
        if self.calls < len(self.responses):
            resp = self.responses[self.calls]
            self.calls += 1
            return resp
        # Default fallback: end loop with empty content
        return AIMessage(content="Đã hoàn thành phân tích.")


@pytest.fixture(autouse=True)
def setup_test_environment():
    sample_doc = DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế bao bì của nhà sản xuất.",
        document_id="doc-1",
        score=0.9,
        source="legal",
        metadata={"legal_anchor": "Điều 77", "source": "Luật BVMT"},
    )
    deps = ToolDependencies(
        retrieval=StaticRetrievalGateway(legal_documents=[sample_doc]),
        evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=10),
        generation=FakeGen(),
        cache=FakeCache(),
        history=FakeHistory(),
        case_resolver=CaseFormResolver(),
    )
    set_tool_dependencies(deps)
    yield
    set_tool_dependencies(None)


@pytest.mark.asyncio
async def test_agent_single_hop():
    mock_llm = MockSequenceLLM([
        # Step 1: LLM calls search_legal_provisions
        AIMessage(
            content="",
            tool_calls=[{
                "name": "search_legal_provisions",
                "args": {"query": "Điều 77"},
                "id": "call_1",
            }],
        ),
        # Step 2: LLM observes evidence and produces final answer
        AIMessage(content="Trách nhiệm tái chế được quy định tại Điều 77 [1]."),
    ])

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Điều 77 quy định gì?")

    assert result.termination_reason == "answer_complete"
    assert "Điều 77" in result.answer
    assert result.steps_taken == 2
    assert len(result.trajectory) == 1
    assert result.trajectory[0].tool == "search_legal_provisions"
    assert result.trajectory[0].allowed is True


@pytest.mark.asyncio
async def test_agent_multi_hop():
    mock_llm = MockSequenceLLM([
        # Step 1: Cache check
        AIMessage(
            content="",
            tool_calls=[{"name": "lookup_answer_cache", "args": {"query": "Điều 77"}, "id": "call_1"}],
        ),
        # Step 2: Search Hop 1
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Điều 77"}, "id": "call_2"}],
        ),
        # Step 3: Search Hop 2 (Nghị định 08)
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Nghị định 08 Điều 54"}, "id": "call_3"}],
        ),
        # Step 4: Final answer
        AIMessage(content="Điều 77 Luật BVMT kết hợp Nghị định 08 Điều 54 quy định chi tiết [1]."),
    ])

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Điều 77 và Nghị định 08?")

    assert result.termination_reason == "answer_complete"
    assert result.steps_taken == 4
    assert len(result.trajectory) == 3


@pytest.mark.asyncio
async def test_agent_loop_detection():
    mock_llm = MockSequenceLLM([
        # Step 1: Call search
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Điều 77"}, "id": "call_1"}],
        ),
        # Step 2: Try to call the exact same search query again
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Điều 77"}, "id": "call_2"}],
        ),
        # Step 3: Realizes it was denied and finishes
        AIMessage(content="Câu trả lời sau khi bị chặn lặp lại."),
    ])

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Điều 77?")

    assert len(result.trajectory) == 2
    assert result.trajectory[0].allowed is True
    assert result.trajectory[1].allowed is False
    assert "loop_detected" in result.trajectory[1].deny_reason


@pytest.mark.asyncio
async def test_agent_budget_exhaustion():
    # An infinite tool-calling loop
    infinite_llm = MockSequenceLLM([
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": f"Query {i}"}, "id": f"call_{i}"}],
        )
        for i in range(10)
    ])

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=3), llm=infinite_llm)
    result = await runner.run("Query?")

    assert result.termination_reason == "insufficient_evidence"
    assert result.steps_taken == 3


@pytest.mark.asyncio
async def test_agent_clarification_tool():
    mock_llm = MockSequenceLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "ask_user_for_clarification",
                "args": {"question": "Vật liệu bao bì là gì?", "missing_fields": ["material"]},
                "id": "call_1",
            }],
        ),
    ])

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Đánh giá nghĩa vụ EPR")

    assert result.termination_reason == "awaiting_user_input"
    assert result.awaiting_user_input is True
    assert "Vật liệu" in result.answer
    assert result.steps_taken == 1
