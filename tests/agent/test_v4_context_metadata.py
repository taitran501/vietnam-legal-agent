from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.graph import WorkflowDependencies
from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.v4 import V4WorkflowRuntime
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.generation import StaticGenerationGateway
from vietnam_legal_agent.tools.history import ContextSnapshot
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


class CaseHistory:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.case: dict[str, object] | None = None
        self.next_id = 1

    async def initialize(self) -> None:
        return None

    async def load(self, _user_id: str, _conversation_id: str, max_messages: int) -> ContextSnapshot:
        return ContextSnapshot(history=self.messages[-max_messages:], active_case=self.case)

    async def save_exchange(
        self,
        _user_id: str,
        _conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, object],
    ) -> int:
        self.messages.extend(
            [
                {"role": "user", "content": user_message, "status": "complete"},
                {"role": "assistant", "content": assistant_message, "status": "complete", "metadata": metadata},
            ]
        )
        message_id = self.next_id
        self.next_id += 1
        return message_id

    async def save_case(self, _user_id: str, _conversation_id: str, state: dict[str, object]) -> dict[str, object]:
        self.case = dict(state)
        return dict(state)

    async def clear_case(self, _user_id: str, _conversation_id: str) -> None:
        self.case = None

    async def record_run(self, _state: dict[str, object], _started_at: float, _ended_at: float) -> None:
        return None


def _dependencies(history: CaseHistory) -> WorkflowDependencies:
    document = DocumentRecord(
        content="Điều 41 Bộ luật Lao động quy định nghĩa vụ khi người sử dụng lao động chấm dứt hợp đồng trái pháp luật. " * 4,
        document_id="labor-41",
        score=0.95,
        source="legal",
        metadata={
            "legal_anchor": "Điều 41",
            "Dieu": "Điều 41",
            "Document_Number": "45/2019/QH14",
            "source": "Bộ luật Lao động 2019",
        },
    )
    return WorkflowDependencies(
        history=history,  # type: ignore[arg-type]
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=[document]),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=2, max_repairs=1),
    )


@pytest.mark.asyncio
async def test_v4_case_follow_up_preserves_context_metadata_and_topic() -> None:
    history = CaseHistory()
    runtime = V4WorkflowRuntime(_dependencies(history), answer_chunk_delay_s=0)
    first = await runtime.run(
        query="Công ty chấm dứt hợp đồng lao động của tôi trái pháp luật và không báo trước, tôi nên làm gì?",
        user_id="u1",
        conversation_id="case-context",
    )
    assert first["termination_reason"] == "answer_complete"

    second = await runtime.run(
        query="Còn khoản bồi thường thì sao?",
        user_id="u1",
        conversation_id="case-context",
    )

    assert second["context_loaded"] is True
    assert second["history_messages"] == 2
    assert second["is_follow_up"] is True
    assert "chấm dứt hợp đồng" in second["standalone_query"].lower()
    assert "bồi thường" in second["standalone_query"]


@pytest.mark.asyncio
async def test_browser_history_excludes_current_pending_turn() -> None:
    from tests.e2e_backend import BrowserHistoryGateway

    history = BrowserHistoryGateway()
    key = ("u1", "conversation")
    history.messages[key] = [
        {"role": "user", "content": "Câu hỏi trước", "status": "complete", "turn_id": "old"},
        {"role": "assistant", "content": "Trả lời trước", "status": "complete", "turn_id": "old"},
        {"role": "user", "content": "Câu hỏi hiện tại", "status": "complete", "turn_id": "current"},
        {"role": "assistant", "content": "", "status": "pending", "turn_id": "current"},
    ]

    snapshot = await history.load("u1", "conversation", 6)

    assert [item["content"] for item in snapshot.history] == ["Câu hỏi trước", "Trả lời trước"]
