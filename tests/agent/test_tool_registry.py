"""Tests for the domain-neutral legal agent tool registry."""

from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.tool_registry import (
    ALL_AGENT_TOOLS,
    ToolDependencies,
    ask_user_for_clarification,
    evaluate_legal_case,
    load_conversation_context,
    search_legal_provisions,
    search_web_official,
    set_tool_dependencies,
)
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.history import ContextSnapshot, HistoryGateway
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


class FakeHistoryGateway(HistoryGateway):
    def __init__(self, snapshot: ContextSnapshot | None = None) -> None:
        self.snapshot = snapshot or ContextSnapshot(history=[], summary="", active_case=None)

    async def initialize(self) -> None:
        return None

    async def load(
        self, user_id: str, conversation_id: str, max_messages: int = 6
    ) -> ContextSnapshot:
        return self.snapshot

    async def save_exchange(
        self,
        user_id: str,
        conversation_id: str,
        user_query: str,
        assistant_answer: str,
        metadata: dict | None = None,
    ) -> int:
        return 1

    async def save_case(
        self, user_id: str, conversation_id: str, active_case: dict
    ) -> dict:
        return active_case

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        return None

    async def record_run(
        self, state: dict, started_at: float, ended_at: float
    ) -> None:
        return None


class FakeGenerationGateway:
    async def chitchat(self, query: str, history: list) -> str:
        return "Xin chào!"

    async def answer(
        self, task_type: str, query: str, documents: list, facts: dict
    ) -> str:
        return "Câu trả lời có căn cứ [1]."

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]:
        return "Kết quả tra cứu", [
            DocumentRecord(
                content="Trang văn bản pháp luật chính thức có nội dung về thời gian thử việc.",
                document_id="web-labor-25",
                source="web",
                metadata={
                    "title": "Bộ luật Lao động",
                    "official_url": "https://vbpl.vn/1",
                    "authority": "official",
                },
            )
        ]

    async def repair(self, answer: str, documents: list, task_type: str) -> str:
        return answer


@pytest.fixture(autouse=True)
def inject_test_deps():
    sample_doc = DocumentRecord(
        content=(
            "Điều 25 Bộ luật Lao động quy định thời gian thử việc tối đa "
            "đối với công việc cần trình độ chuyên môn."
        ),
        document_id="labor-25",
        score=0.9,
        source="legal",
        metadata={
            "legal_anchor": "Điều 25",
            "Dieu": "Điều 25",
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động 2019",
        },
    )
    set_tool_dependencies(
        ToolDependencies(
            retrieval=StaticRetrievalGateway(legal_documents=[sample_doc]),
            evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=30),
            generation=FakeGenerationGateway(),
            cache=ScopedAnswerCache(InMemoryAnswerCache()),
            history=FakeHistoryGateway(),
        )
    )
    yield
    set_tool_dependencies(None)


def test_agent_exposes_only_general_conversation_and_retrieval_tools():
    assert {tool.__name__ for tool in ALL_AGENT_TOOLS} == {
        "search_legal_provisions",
        "search_web_official",
        "lookup_answer_cache",
        "load_conversation_context",
        "ask_user_for_clarification",
    }


@pytest.mark.asyncio
async def test_search_legal_provisions_returns_grounded_results_for_an_ordinary_topic():
    result = await search_legal_provisions(
        "Điều 25 Bộ luật Lao động quy định thời gian thử việc tối đa bao lâu?"
    )
    assert result["ok"] is True
    assert result["total_found"] == 1
    assert result["evidence_sufficient"] is True
    assert result["documents"][0]["metadata"]["legal_anchor"] == "Điều 25"


@pytest.mark.asyncio
async def test_search_without_evidence_reports_a_recoverable_gap():
    set_tool_dependencies(
        ToolDependencies(
            retrieval=StaticRetrievalGateway(legal_documents=[]),
            evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=30),
            generation=FakeGenerationGateway(),
            cache=ScopedAnswerCache(InMemoryAnswerCache()),
            history=FakeHistoryGateway(),
        )
    )
    result = await search_legal_provisions(
        "Điều 999 Bộ luật Lao động quy định gì?"
    )
    assert result["ok"] is True
    assert result["evidence_sufficient"] is False
    assert result["total_found"] == 0
    assert result["suggested_followup_query"]


@pytest.mark.asyncio
async def test_official_web_search_keeps_source_documents():
    result = await search_web_official(
        "Tìm văn bản chính thức về thời gian thử việc"
    )
    assert result["ok"] is True
    assert result["total_found"] == 1
    assert "vbpl.vn" in result["documents"][0]["metadata"]["official_url"]


@pytest.mark.asyncio
async def test_case_assessment_requires_source_retrieval_before_a_conclusion():
    result = await evaluate_legal_case(
        "labor", {"employment_issue": "chậm trả lương"}
    )
    assert result["ok"] is False
    assert result["status"] == "retrieval_required"


@pytest.mark.asyncio
async def test_conversational_clarification_accepts_one_natural_question():
    question = "Công ty đã chậm trả lương trong bao lâu?"
    result = await ask_user_for_clarification(question)
    assert result["ok"] is True
    assert result["awaiting_user_input"] is True
    assert result["question"] == question


@pytest.mark.asyncio
async def test_load_context_returns_history_without_a_form_contract():
    snapshot = ContextSnapshot(
        history=[{"role": "user", "content": "Công ty chậm trả lương."}],
        summary="Trao đổi về tiền lương.",
        active_case={
            "task_type": "case_assessment",
            "facts": {"delay": "hai tuần"},
        },
    )
    set_tool_dependencies(
        ToolDependencies(
            retrieval=StaticRetrievalGateway(),
            evidence_evaluator=EvidenceEvaluator(),
            generation=FakeGenerationGateway(),
            cache=ScopedAnswerCache(InMemoryAnswerCache()),
            history=FakeHistoryGateway(snapshot=snapshot),
        )
    )
    result = await load_conversation_context("u1", "c1")
    assert result["ok"] is True
    assert len(result["history_messages"]) == 1
    assert result["has_active_case"] is True
