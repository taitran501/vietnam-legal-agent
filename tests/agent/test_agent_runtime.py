"""Unit tests for AgentWorkflowRuntime."""

from __future__ import annotations

import pytest

from epr_agent.agent.agent_loop import AgentRunResult, AgentStep
from epr_agent.agent.guardrails import AgentGuardrails
from epr_agent.agent.runtime import AgentWorkflowRuntime, WorkflowDependencies, get_default_runtime
from epr_agent.agent.tool_registry import ToolDependencies, set_tool_dependencies
from epr_agent.domain.epr_rules import CaseFormResolver
from epr_agent.domain.models import DocumentRecord, TerminationReason
from epr_agent.tools.cache import ScopedAnswerCache
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
async def test_get_default_runtime_feature_flag(monkeypatch):
    from backend.config import get_settings
    get_default_runtime.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_pipeline_version", "pipeline-agent")
    
    runtime = get_default_runtime()
    assert runtime.__class__.__name__ == "AgentWorkflowRuntime"
    get_default_runtime.cache_clear()
