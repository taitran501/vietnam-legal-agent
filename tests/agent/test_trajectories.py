"""Deterministic end-to-end trajectories for the bounded compliance workflow."""

from __future__ import annotations

import pytest

from epr_agent.agent.graph import WorkflowDependencies, run_workflow
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.domain.models import DocumentRecord, TaskType
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


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


def legal_document() -> DocumentRecord:
    return DocumentRecord(
        content="Nội dung Điều 77 về trách nhiệm tái chế và thực hiện nghĩa vụ EPR. " * 8,
        metadata={
            "Dieu": "Điều 77",
            "source": "Nghị định 08/2022/NĐ-CP",
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "epr-law-structure-v2",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "legal_anchor": "Điều 77",
        },
        document_id="law-77",
        source="legal",
        score=0.94,
    )


def dependencies(*, history: TrajectoryHistory | None = None, legal: bool = True, generation=None) -> WorkflowDependencies:
    return WorkflowDependencies(
        history=history or TrajectoryHistory(),
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=[legal_document()] if legal else []),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=generation or StaticGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?",
        "Công ty tôi là nhà nhập khẩu chai thủy tinh tại Việt Nam, cần đánh giá nghĩa vụ EPR.",
        "Doanh nghiệp sản xuất pin kim loại cho thị trường Việt Nam có phải thực hiện EPR không?",
    ],
)
async def test_assessment_with_complete_facts_is_evidence_linked(query: str):
    state = await run_workflow(query, user_id="trajectory", conversation_id="assessment", deps=dependencies())

    assert state["task_type"] == TaskType.ASSESS_EPR_OBLIGATION.value
    assert state["termination_reason"] == "answer_complete"
    assert state["missing_facts"] == []
    assert state["assessment"]["status"] == "preliminary"
    assert state["citations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_missing"),
    [
        (
            "Tôi là nhà sản xuất, có phải thực hiện EPR không?",
            {"product_or_packaging", "material", "activity_scope"},
        ),
        (
            "Công ty tôi sản xuất bao bì tại Việt Nam, cần đánh giá nghĩa vụ EPR.",
            {"material"},
        ),
        (
            "Tôi là nhà nhập khẩu bao bì nhựa, có phải thực hiện EPR không?",
            {"activity_scope"},
        ),
    ],
)
async def test_assessment_with_missing_facts_stops_for_exact_follow_up(query: str, expected_missing: set[str]):
    state = await run_workflow(query, user_id="trajectory", conversation_id="missing", deps=dependencies())

    assert state["termination_reason"] == "awaiting_user_input"
    assert set(state["missing_facts"]) == expected_missing
    assert "retrieve_legal" not in state["action_sequence"]
    assert state["case_state"]["status"] == "collecting"


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", [TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST])
async def test_follow_up_resumes_active_case(task_type: TaskType):
    history = TrajectoryHistory(
        {
            "task_type": task_type.value,
            "facts": {
                "business_role": "nhà sản xuất",
                "product_or_packaging": "bao bì",
                "activity_scope": "thị trường Việt Nam",
            },
            "status": "collecting",
        }
    )
    state = await run_workflow(
        "Vật liệu là nhựa",
        user_id="trajectory",
        conversation_id=f"resume-{task_type.value}",
        deps=dependencies(history=history),
    )

    assert state["task_type"] == task_type.value
    assert state["missing_facts"] == []
    assert state["facts"]["material"] == "nhựa"
    assert state["termination_reason"] == "answer_complete"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Lập checklist EPR cho nhà sản xuất bao bì nhựa tại Việt Nam.",
        "Lập checklist tuân thủ cho nhà nhập khẩu chai thủy tinh tại Việt Nam.",
    ],
)
async def test_checklist_has_evidence_and_assumptions(query: str):
    state = await run_workflow(query, user_id="trajectory", conversation_id="checklist", deps=dependencies())

    assert state["task_type"] == TaskType.BUILD_COMPLIANCE_CHECKLIST.value
    assert state["termination_reason"] == "answer_complete"
    assert state["checklist"]
    assert state["citations"]
    assert all(item["assumption"] for item in state["checklist"])


@pytest.mark.asyncio
async def test_out_of_scope_question_stops_without_web_search():
    state = await run_workflow(
        "Quy định về chứng khoán là gì?",
        user_id="trajectory",
        conversation_id="out-of-scope",
        deps=dependencies(legal=False),
    )

    assert state["termination_reason"] == "out_of_scope"
    assert "retrieve_web" not in state["action_sequence"]


@pytest.mark.asyncio
async def test_epr_corpus_miss_without_web_evidence_stops_safely():
    state = await run_workflow(
        "Nghĩa vụ EPR cho bao bì hiện nay là gì?",
        user_id="trajectory",
        conversation_id="no-evidence",
        deps=dependencies(legal=False, generation=NoWebGeneration()),
    )

    assert state["termination_reason"] == "insufficient_evidence"
    assert state["source"] == "error"
    assert state["retrieval_actions"] <= 3
