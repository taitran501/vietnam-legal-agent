"""Balanced basic-user flows for the general Vietnamese legal assistant."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from vietnam_legal_agent.agent.agent_loop import AgentRunConfig, VietnameseLegalAgentRunner
from vietnam_legal_agent.agent.tool_registry import ToolDependencies, set_tool_dependencies
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.history import ContextSnapshot, HistoryGateway
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


class MockHistory(HistoryGateway):
    async def initialize(self) -> None:
        return None

    async def load(self, user_id: str, conversation_id: str, max_messages: int = 6) -> ContextSnapshot:
        return ContextSnapshot(history=[], summary="", active_case=None)

    async def save_exchange(self, *args, **kwargs) -> int:
        return 1

    async def save_case(self, *args, **kwargs) -> dict:
        return {}

    async def clear_case(self, *args, **kwargs) -> None:
        return None

    async def record_run(self, *args, **kwargs) -> None:
        return None


class MockGeneration:
    async def chitchat(self, query: str, history: list) -> str:
        return "Chào bạn! Tôi có thể giúp tra cứu và giải thích quy định pháp luật Việt Nam."

    async def answer(self, *args, **kwargs) -> str:
        return "Trả lời mẫu"

    async def web(self, *args, **kwargs) -> tuple[str, list]:
        return "web", []

    async def repair(self, *args, **kwargs) -> str:
        return ""


class MockCache:
    async def lookup(self, *args, **kwargs):
        return None, "key"

    async def store(self, *args, **kwargs) -> None:
        return None


@pytest.fixture(autouse=True)
def setup_environment():
    sample_docs = [
        DocumentRecord(
            content="Người sử dụng lao động phải trả lương trực tiếp, đầy đủ và đúng hạn cho người lao động.",
            document_id="labor-wage",
            score=0.95,
            source="legal",
            metadata={"legal_anchor": "Điều 94", "Dieu": "94", "source": "Bộ luật Lao động 2019"},
        ),
        DocumentRecord(
            content="Tiền đặt cọc được xử lý theo thỏa thuận; bên nhận cọc phải hoàn trả hoặc thanh toán theo quy định nếu giao dịch không được xác lập, thực hiện.",
            document_id="civil-deposit",
            score=0.94,
            source="legal",
            metadata={"legal_anchor": "Điều 328", "Dieu": "328", "source": "Bộ luật Dân sự 2015"},
        ),
        DocumentRecord(
            content="Người điều khiển và người ngồi trên xe mô tô, xe gắn máy phải đội mũ bảo hiểm theo quy định.",
            document_id="traffic-helmet",
            score=0.92,
            source="legal",
            metadata={"legal_anchor": "Điều 30", "Dieu": "30", "source": "Luật Giao thông đường bộ"},
        ),
    ]
    set_tool_dependencies(
        ToolDependencies(
            retrieval=StaticRetrievalGateway(legal_documents=sample_docs),
            evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=10),
            generation=MockGeneration(),
            cache=MockCache(),
            history=MockHistory(),
        )
    )
    yield
    set_tool_dependencies(None)


class LookupLLM:
    def __init__(self, query: str, answer: str) -> None:
        self.query = query
        self.answer = answer
        self.calls = 0

    async def ainvoke(self, messages: list) -> AIMessage:
        if self.calls == 0:
            self.calls += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_legal_provisions",
                        "args": {"query": self.query},
                        "id": "lookup-1",
                    }
                ],
            )
        return AIMessage(content=self.answer)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_query", "search_query", "answer"),
    [
        (
            "Công ty chậm trả lương cho tôi hai tháng thì tôi nên làm gì?",
            "chậm trả lương đúng hạn Điều 94 Bộ luật Lao động",
            "Người sử dụng lao động phải trả lương đầy đủ và đúng hạn theo Điều 94 Bộ luật Lao động [1].",
        ),
        (
            "Chủ nhà không trả tiền cọc sau khi tôi bàn giao nhà, quy định thế nào?",
            "hoàn trả tiền đặt cọc thuê nhà Điều 328 Bộ luật Dân sự",
            "Việc xử lý tiền đặt cọc căn cứ thỏa thuận và Điều 328 Bộ luật Dân sự [1].",
        ),
        (
            "Người ngồi sau xe máy có bắt buộc đội mũ bảo hiểm không?",
            "người ngồi sau xe máy đội mũ bảo hiểm Điều 30",
            "Người ngồi trên xe mô tô phải đội mũ bảo hiểm theo Điều 30 [1].",
        ),
    ],
)
async def test_basic_user_legal_question_uses_retrieval(
    user_query: str,
    search_query: str,
    answer: str,
) -> None:
    runner = VietnameseLegalAgentRunner(
        config=AgentRunConfig(max_steps=3),
        llm=LookupLLM(search_query, answer),
    )

    result = await runner.run(user_query)

    assert result.termination_reason == "answer_complete"
    assert "[1]" in result.answer
    assert result.trajectory[0].tool == "search_legal_provisions"


@pytest.mark.asyncio
async def test_greeting_is_answered_without_forcing_a_legal_domain() -> None:
    class GreetingLLM:
        async def ainvoke(self, messages: list) -> AIMessage:
            return AIMessage(content="Chào bạn! Bạn cần tìm hiểu quy định nào?")

    runner = VietnameseLegalAgentRunner(config=AgentRunConfig(max_steps=2), llm=GreetingLLM())

    result = await runner.run("Chào bạn")

    assert result.termination_reason == "answer_complete"
    assert "Chào bạn" in result.answer
    assert result.trajectory == []
