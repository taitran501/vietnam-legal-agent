"""Unit tests for the Vietnamese legal agent cognitive loop."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

from vietnam_legal_agent.agent.agent_loop import (
    AgentRunConfig,
    VietnameseLegalAgentRunner,
    _append_evidence_documents,
    _compact_observation_for_agent,
    _prepare_legal_search_args,
)
from vietnam_legal_agent.agent.tool_registry import ToolDependencies, set_tool_dependencies
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.history import ContextSnapshot, HistoryGateway
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


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
        self.messages: list[list] = []

    async def ainvoke(self, messages: list) -> AIMessage:
        self.messages.append(list(messages))
        if self.calls < len(self.responses):
            resp = self.responses[self.calls]
            self.calls += 1
            return resp
        # Default fallback: end loop with empty content
        return AIMessage(content="Đã hoàn thành phân tích.")


@pytest.fixture(autouse=True)
def setup_test_environment():
    sample_doc = DocumentRecord(
        content="Điều 25 quy định thời gian thử việc tối đa đối với công việc cần trình độ chuyên môn.",
        document_id="doc-1",
        score=0.9,
        source="legal",
        metadata={"legal_anchor": "Điều 25", "source": "Bộ luật Lao động 2019"},
    )
    deps = ToolDependencies(
        retrieval=StaticRetrievalGateway(legal_documents=[sample_doc]),
        evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=10),
        generation=FakeGen(),
        cache=FakeCache(),
        history=FakeHistory(),
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
                "args": {"query": "Điều 25"},
                "id": "call_1",
            }],
        ),
        # Step 2: LLM observes evidence and produces final answer
        AIMessage(content="Thời gian thử việc được quy định tại Điều 25 [1]."),
    ])

    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Điều 25 quy định gì?")

    assert result.termination_reason == "answer_complete"
    assert "Điều 25" in result.answer
    assert result.steps_taken == 2
    assert len(result.trajectory) == 1
    assert result.trajectory[0].tool == "search_legal_provisions"
    assert result.trajectory[0].allowed is True


@pytest.mark.asyncio
async def test_legal_route_forces_search_even_when_model_draft_is_short():
    mock_llm = MockSequenceLLM([
        AIMessage(content="Có thể kiện."),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "search_legal_provisions",
                "args": {"query": "nghĩa vụ trả nợ hợp đồng vay"},
                "id": "call_legal_search",
            }],
        ),
        AIMessage(content="Điều 466 Bộ luật Dân sự quy định nghĩa vụ trả nợ [1]."),
    ])
    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)

    result = await runner.run(
        "Tôi cho bạn vay tiền có giấy viết tay, giờ bạn không trả thì có kiện được không?",
        require_legal_evidence=True,
    )

    assert result.termination_reason == "answer_complete"
    assert len(result.trajectory) == 1
    assert result.trajectory[0].tool == "search_legal_provisions"
    assert mock_llm.calls == 3


@pytest.mark.asyncio
async def test_structured_retrieval_query_reaches_search_and_stays_internal():
    user_query = "Công ty giữ lại lương tháng cuối của tôi sau khi nghỉ việc. Tôi phải làm sao?"
    rewrite = "người sử dụng lao động thanh toán tiền lương khi chấm dứt hợp đồng lao động"
    mock_llm = MockSequenceLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "search_legal_provisions",
                "args": {"query": "tiền lương chưa thanh toán sau khi nghỉ việc"},
                "id": "call_rewritten_search",
            }],
        ),
        AIMessage(content="Căn cứ cần đối chiếu là trách nhiệm thanh toán khi chấm dứt hợp đồng [1]."),
    ])
    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)

    result = await runner.run(
        user_query,
        require_legal_evidence=True,
        retrieval_queries=[rewrite],
    )

    assert result.termination_reason == "answer_complete"
    search_query = result.trajectory[0].args["query"]
    assert search_query == user_query
    assert result.trajectory[0].args["related_queries"] == [
        rewrite,
        "tiền lương chưa thanh toán sau khi nghỉ việc",
    ]
    assert any(
        "<legal_retrieval_query_hints>" in str(content) and rewrite in str(content)
        for role, content in mock_llm.messages[0]
        if role == "system"
    )


@pytest.mark.asyncio
async def test_recovery_instructions_do_not_replace_the_user_query_used_for_search():
    user_query = "Chủ nhà muốn tăng tiền thuê giữa thời hạn hợp đồng. Tôi có phải đồng ý không?"
    recovery_query = (
        f"{user_query}\n\nYêu cầu tra cứu lại sau kiểm chứng: dùng thuật ngữ pháp lý chính xác."
    )
    mock_llm = MockSequenceLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "search_legal_provisions",
                "args": {"query": "giá thuê trong hợp đồng thuê tài sản"},
                "id": "call_recovery_search",
            }],
        ),
        AIMessage(content="Giá thuê do các bên thỏa thuận theo Điều 473 [1]."),
    ])
    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)

    result = await runner.run(
        recovery_query,
        require_legal_evidence=True,
        search_user_query=user_query,
    )

    assert result.termination_reason == "answer_complete"
    assert result.trajectory[0].args["query"] == user_query
    assert "tra cứu lại" not in result.trajectory[0].args["query"]


def test_legal_search_keeps_user_scenario_and_discards_inferred_article_anchors():
    user_query = "Công ty cho tôi nghỉ việc ngay mà không báo trước, họ làm vậy có đúng luật không?"

    prepared = _prepare_legal_search_args(
        user_query,
        {
            "query": "nghỉ việc không báo trước theo Điều 36, Điều 37 và Điều 38",
            "required_anchors": ["Điều 36", "Điều 37", "Điều 38"],
        },
    )

    assert "required_anchors" not in prepared
    assert prepared["query"] == user_query
    assert "Điều 36" not in prepared["related_queries"][0]


def test_legal_search_preserves_explicit_user_article_anchor():
    user_query = "Theo Điều 36 Bộ luật Lao động 2019, công ty có được cho tôi nghỉ ngay không?"

    prepared = _prepare_legal_search_args(
        user_query,
        {
            "query": "Bộ luật Lao động Điều 39/2019/QH13 về cho nghỉ việc",
            "required_anchors": ["Điều 39", "Điều 40"],
        },
    )

    assert prepared["required_anchors"] == ["Bộ luật Lao động 2019 | Điều 36"]
    assert "Điều 39" not in prepared["query"]
    assert "Điều 36" in prepared["query"]


def test_legal_search_uses_retrieval_rewrite_without_trusting_its_anchors():
    prepared = _prepare_legal_search_args(
        "Công ty giữ lại lương sau khi nghỉ việc, làm sao?",
        {"query": "tiền lương sau khi chấm dứt hợp đồng theo Điều 48"},
        retrieval_queries=["thanh toán tiền lương khi chấm dứt hợp đồng lao động theo Điều 48"],
    )

    assert prepared["query"] == "Công ty giữ lại lương sau khi nghỉ việc, làm sao?"
    assert prepared["related_queries"] == [
        "thanh toán tiền lương khi chấm dứt hợp đồng lao động",
        "tiền lương sau khi chấm dứt hợp đồng",
    ]
    assert all("Điều 48" not in query for query in prepared["related_queries"])
    assert "required_anchors" not in prepared


def test_legal_search_deduplicates_the_tool_rewrite_from_retrieval_hints():
    user_query = "Hàng xóm xây tường lấn sang đất nhà tôi. Tôi nên xử lý thế nào?"
    rewrite = "quyền yêu cầu tháo dỡ công trình xây dựng lấn chiếm đất đai của hàng xóm"
    prepared = _prepare_legal_search_args(
        user_query,
        {"query": f"{rewrite}\n{user_query}"},
        retrieval_queries=[
            rewrite,
            "ranh giới bất động sản và quyền sử dụng đất khi hàng xóm xây tường lấn ranh",
        ],
    )

    assert prepared["query"] == user_query
    assert prepared["related_queries"] == [
        rewrite,
        "ranh giới bất động sản và quyền sử dụng đất khi hàng xóm xây tường lấn ranh",
    ]


def test_legal_search_reserves_query_slots_for_understanding_rewrites():
    prepared = _prepare_legal_search_args(
        "Mua máy giặt mới bị hỏng, shop từ chối bảo hành thì tôi có quyền gì?",
        {"query": "quyền người tiêu dùng và trách nhiệm của bên bán khi sản phẩm có lỗi"},
        retrieval_queries=[
            "cửa hàng từ chối bảo hành máy giặt mới bị hỏng",
            "tổ chức cá nhân kinh doanh thực hiện trách nhiệm bảo hành sản phẩm hàng hóa",
        ],
    )

    assert prepared["related_queries"] == [
        "cửa hàng từ chối bảo hành máy giặt mới bị hỏng",
        "tổ chức cá nhân kinh doanh thực hiện trách nhiệm bảo hành sản phẩm hàng hóa",
    ]


def test_retrieval_results_keep_global_citation_indices_across_searches():
    all_evidence = []
    first = {
        "document_id": "unrelated-source",
        "source": "legal",
        "content": "Một tài liệu không liên quan.",
        "metadata": {"source_title": "Nguồn A"},
    }
    second = {
        "document_id": "labor-law-36",
        "source": "legal",
        "content": "Điều 36 quy định về hợp đồng lao động.",
        "metadata": {"legal_anchor": "Điều 36", "source_title": "Bộ luật Lao động"},
    }

    assert _append_evidence_documents(all_evidence, [first]) == [1]
    second_indices = _append_evidence_documents(all_evidence, [second])
    observed = _compact_observation_for_agent(
        "search_legal_provisions",
        {"documents": [second]},
        citation_indices=second_indices,
    )

    assert len(all_evidence) == 2
    assert observed["documents"][0]["citation_index"] == 2
    assert _append_evidence_documents(all_evidence, [first]) == [1]
    assert len(all_evidence) == 2


@pytest.mark.asyncio
async def test_agent_multi_hop():
    mock_llm = MockSequenceLLM([
        # Step 1: Cache check
        AIMessage(
            content="",
            tool_calls=[{"name": "lookup_answer_cache", "args": {"query": "Điều 25"}, "id": "call_1"}],
        ),
        # Step 2: Search Hop 1
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Điều 25"}, "id": "call_2"}],
        ),
        # Step 3: Search Hop 2 (Nghị định 08)
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Bộ luật Lao động Điều 26"}, "id": "call_3"}],
        ),
        # Step 4: Final answer
        AIMessage(content="Điều 25 Bộ luật Lao động 2019 kết hợp Bộ luật Lao động Điều 26 quy định chi tiết [1]."),
    ])

    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Điều 25 và Nghị định 08?")

    assert result.termination_reason == "answer_complete"
    assert result.steps_taken == 4
    assert len(result.trajectory) == 3


@pytest.mark.asyncio
async def test_agent_loop_detection():
    mock_llm = MockSequenceLLM([
        # Step 1: Call search
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Điều 25"}, "id": "call_1"}],
        ),
        # Step 2: Try to call the exact same search query again
        AIMessage(
            content="",
            tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Điều 25"}, "id": "call_2"}],
        ),
        # Step 3: Realizes it was denied and finishes
        AIMessage(content="Câu trả lời sau khi bị chặn lặp lại."),
    ])

    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Điều 25?")

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

    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=3), llm=infinite_llm)
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
                "args": {"question": "Công ty đã chậm trả lương trong bao lâu?", },
                "id": "call_1",
            }],
        ),
    ])

    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=5), llm=mock_llm)
    result = await runner.run("Công ty chậm trả lương, tôi nên làm gì?")

    assert result.termination_reason == "awaiting_user_input"
    assert result.awaiting_user_input is True
    assert "chậm trả lương" in result.answer
    assert result.steps_taken == 1


@pytest.mark.asyncio
async def test_agent_emits_tool_result_after_execution():
    completed = False

    async def probe_tool() -> dict:
        nonlocal completed
        await asyncio.sleep(0)
        completed = True
        return {"ok": True}

    mock_llm = MockSequenceLLM([
        AIMessage(content="", tool_calls=[{"name": "probe_tool", "args": {}, "id": "call-1"}]),
        AIMessage(content="Hoàn tất."),
    ])
    runner = VietnameseLegalAgentRunner(llm=mock_llm, tools=[probe_tool])
    events = []
    async for event in runner.stream("Kiểm tra"):
        events.append((event, completed))

    call_index = next(i for i, (event, _) in enumerate(events) if event["type"] == "agent_tool_call")
    result_index = next(i for i, (event, _) in enumerate(events) if event["type"] == "agent_tool_result")
    assert call_index < result_index
    assert events[result_index][1] is True
    assert events[result_index][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_agent_tool_timeout_has_terminal_result_event():
    async def slow_tool() -> dict:
        await asyncio.sleep(0.05)
        return {"ok": True}

    mock_llm = MockSequenceLLM([
        AIMessage(content="", tool_calls=[{"name": "slow_tool", "args": {}, "id": "call-1"}]),
        AIMessage(content="Không thể hoàn tất."),
    ])
    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(tool_timeout_s=0.001), llm=mock_llm, tools=[slow_tool])
    events = [event async for event in runner.stream("Kiểm tra timeout")]

    tool_result = next(event for event in events if event["type"] == "agent_tool_result")
    assert tool_result["status"] == "timed_out"
    assert tool_result["error_code"] == "tool_timeout"


@pytest.mark.asyncio
async def test_agent_checks_durable_cancellation_before_llm_call():
    mock_llm = MockSequenceLLM([AIMessage(content="Không được gọi")])
    runner = VietnameseLegalAgentRunner(llm=mock_llm)

    result = await runner.run("Kiểm tra dừng", is_cancelled=lambda: asyncio.sleep(0, result=True))

    assert result.termination_reason == "user_cancelled"
    assert mock_llm.calls == 0
