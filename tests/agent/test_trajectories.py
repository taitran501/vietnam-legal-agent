"""Deterministic user journeys across ordinary Vietnamese legal topics."""

from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.graph import WorkflowDependencies, run_workflow
from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.generation import StaticGenerationGateway
from vietnam_legal_agent.tools.history import ContextSnapshot
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


class TrajectoryHistory:
    def __init__(self, active_case: dict | None = None) -> None:
        self.active_case = active_case

    async def initialize(self) -> None:
        return None

    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot:
        return ContextSnapshot(history=[], active_case=self.active_case)


class NoWebGeneration(StaticGenerationGateway):
    async def web(self, query: str):
        self.calls.append("web")
        return "", []


def legal_document(content: str, article: str, source: str) -> DocumentRecord:
    return DocumentRecord(
        content=content * 5,
        metadata={
            "Dieu": article,
            "source": source,
            "Corpus_Version": "general-law-test-v1",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "legal_anchor": article,
        },
        document_id=f"law-{article}",
        source="legal",
        score=0.94,
    )


def dependencies(
    *,
    history: TrajectoryHistory | None = None,
    documents: list[DocumentRecord] | None = None,
    generation=None,
) -> WorkflowDependencies:
    return WorkflowDependencies(
        history=history or TrajectoryHistory(),
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=documents or []),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=generation or StaticGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "document", "task"),
    [
        (
            "Tôi bị công ty chậm trả lương hai tháng, tôi có quyền gì?",
            legal_document(
                "Người sử dụng lao động phải trả lương trực tiếp, đầy đủ, đúng hạn cho người lao động.",
                "Điều 94",
                "Bộ luật Lao động 2019",
            ),
            TaskType.CASE_ASSESSMENT.value,
        ),
        (
            "Chủ nhà không trả tiền đặt cọc sau khi tôi bàn giao nhà, có đúng không?",
            legal_document(
                "Tiền đặt cọc được xử lý theo thỏa thuận và quy định của pháp luật dân sự về đặt cọc.",
                "Điều 328",
                "Bộ luật Dân sự 2015",
            ),
            TaskType.LEGAL_LOOKUP.value,
        ),
        (
            "Người ngồi sau xe máy không đội mũ bảo hiểm thì bị xử lý thế nào?",
            legal_document(
                "Người điều khiển và người ngồi trên xe mô tô, xe gắn máy phải đội mũ bảo hiểm.",
                "Điều 30",
                "Luật Giao thông đường bộ",
            ),
            TaskType.LEGAL_LOOKUP.value,
        ),
    ],
)
async def test_basic_legal_case_uses_evidence_without_fixed_intake(
    query: str,
    document: DocumentRecord,
    task: str,
) -> None:
    state = await run_workflow(
        query,
        user_id="trajectory",
        conversation_id="general-case",
        deps=dependencies(documents=[document]),
    )

    assert state["task_type"] == task
    assert state["termination_reason"] == "answer_complete"
    assert state["missing_facts"] == []
    assert state["citations"]
    assert "retrieve_legal" in state["action_sequence"]


@pytest.mark.asyncio
async def test_short_case_description_is_not_blocked_by_mandatory_fields() -> None:
    state = await run_workflow(
        "Tôi bị công ty chậm lương, tôi có quyền gì?",
        user_id="trajectory",
        conversation_id="short-case",
        deps=dependencies(
            documents=[
                legal_document(
                    "Người sử dụng lao động phải trả lương đầy đủ, đúng hạn và bảo đảm quyền lợi của người lao động.",
                    "Điều 94",
                    "Bộ luật Lao động 2019",
                )
            ]
        ),
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["missing_facts"] == []
    assert state["case_state"] is None or "required_count" not in state["case_state"]


@pytest.mark.asyncio
async def test_follow_up_keeps_user_context_without_requesting_a_form() -> None:
    history = TrajectoryHistory(
        {
            "task_type": TaskType.CASE_ASSESSMENT.value,
            "facts": {"employment_issue": "chậm trả lương", "duration": "hai tháng"},
            "status": "ready",
        }
    )
    state = await run_workflow(
        "Tôi đã nhắc công ty hai lần rồi.",
        user_id="trajectory",
        conversation_id="case-follow-up",
        deps=dependencies(
            history=history,
            documents=[
                legal_document(
                    "Người sử dụng lao động phải trả lương đầy đủ và đúng hạn cho người lao động.",
                    "Điều 94",
                    "Bộ luật Lao động 2019",
                )
            ],
        ),
    )

    assert state["termination_reason"] == "answer_complete"
    assert state["missing_facts"] == []
    assert state["facts"]["duration"] == "hai tháng"


@pytest.mark.asyncio
async def test_checklist_route_is_available_for_a_general_legal_task() -> None:
    state = await run_workflow(
        "Lập checklist giấy tờ cần chuẩn bị khi nghỉ việc.",
        user_id="trajectory",
        conversation_id="labor-checklist",
        deps=dependencies(
            documents=[
                legal_document(
                    "Khi chấm dứt hợp đồng lao động, các bên thực hiện trách nhiệm thanh toán và bàn giao theo quy định.",
                    "Điều 48",
                    "Bộ luật Lao động 2019",
                )
            ]
        ),
    )

    assert state["task_type"] == TaskType.BUILD_COMPLIANCE_CHECKLIST.value
    assert state["termination_reason"] == "answer_complete"
    assert state["answer"]
    assert state["citations"]


@pytest.mark.asyncio
async def test_out_of_scope_question_stops_without_web_search() -> None:
    state = await run_workflow(
        "Hướng dẫn cách nấu phở bò Nam Định?",
        user_id="trajectory",
        conversation_id="out-of-scope",
        deps=dependencies(),
    )

    assert state["termination_reason"] == "out_of_scope"
    assert "retrieve_web" not in state["action_sequence"]


@pytest.mark.asyncio
async def test_missing_legal_evidence_stops_without_fabricated_answer() -> None:
    state = await run_workflow(
        "Quy định hiện hành cho tình huống pháp lý rất cụ thể này là gì?",
        user_id="trajectory",
        conversation_id="no-evidence",
        deps=dependencies(generation=NoWebGeneration()),
    )

    assert state["termination_reason"] == "insufficient_evidence"
    assert state["source"] == "error"
    assert state["retrieval_actions"] <= 3
