from __future__ import annotations

import pytest

from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.v4 import V4WorkflowRuntime
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


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
        content="Điều 77 quy định trách nhiệm tái chế bao bì của nhà sản xuất, nhập khẩu. " * 4,
        document_id="law-77",
        score=0.95,
        source="legal",
        metadata={
            "legal_anchor": "Điều 77",
            "Dieu": "Điều 77",
            "Document_Number": "08/2022/NĐ-CP",
            "source": "Nghị định 08/2022/NĐ-CP",
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
        query="Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?",
        user_id="u1",
        conversation_id="case-context",
    )
    assert first["termination_reason"] == "awaiting_user_input"

    second = await runtime.run(
        query="Doanh thu 12 tỷ",
        user_id="u1",
        conversation_id="case-context",
    )

    assert second["context_loaded"] is True
    assert second["history_messages"] == 2
    assert second["is_follow_up"] is True
    assert "nhà sản xuất bao bì nhựa" in second["standalone_query"].lower()
    assert "Doanh thu 12 tỷ" in second["standalone_query"]


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
