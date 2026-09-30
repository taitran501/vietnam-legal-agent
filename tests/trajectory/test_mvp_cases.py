"""Cross-domain basic-user acceptance matrix for the legal workflow."""

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


class HistoryDouble:
    def __init__(self, active_case=None):
        self.active_case = active_case

    async def initialize(self):
        return None

    async def load(self, user_id, conversation_id, max_messages):
        return ContextSnapshot([], self.active_case)

    async def save_exchange(self, *args, **kwargs):
        return None

    async def save_case(self, *args, **kwargs):
        return None

    async def clear_case(self, *args, **kwargs):
        return None

    async def record_run(self, *args, **kwargs):
        return None


class EmptyWebGeneration(StaticGenerationGateway):
    async def web(self, query: str):
        self.calls.append("web")
        return "", []


def law_doc(article: str, source: str, content: str) -> DocumentRecord:
    document_number = "82/2015/QH13" if source == "Luật Tài nguyên, môi trường biển và hải đảo 2015" else ""
    return DocumentRecord(
        content=(content + " ") * 6,
        metadata={
            "Dieu": article,
            "source": source,
            "source_file": "universal-corpus",
            "Corpus_Version": "general-law-test-v1",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "legal_anchor": article,
            **({"Document_Number": document_number} if document_number else {}),
        },
        document_id=f"law-{article}",
        source="legal",
    )


def deps(*, active_case=None, document: DocumentRecord | None = None, with_evidence=True):
    documents = [document] if with_evidence and document else []
    return WorkflowDependencies(
        history=HistoryDouble(active_case),
        cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="general-law-test-v1"),
        retrieval=StaticRetrievalGateway(legal_documents=documents),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway() if with_evidence else EmptyWebGeneration(),
        planner=BoundedPlanner(),
    )


CASES = [
    (
        "labor_wage_case",
        "Tôi bị công ty chậm trả lương hai tháng, tôi có quyền gì?",
        TaskType.CASE_ASSESSMENT.value,
        "answer_complete",
        law_doc("Điều 94", "Bộ luật Lao động 2019", "Người sử dụng lao động phải trả lương trực tiếp, đầy đủ và đúng hạn."),
        True,
        None,
    ),
    (
        "rental_deposit_case",
        "Chủ nhà giữ tiền đặt cọc sau khi tôi bàn giao nhà, tôi nên làm gì?",
        TaskType.CASE_ASSESSMENT.value,
        "answer_complete",
        law_doc("Điều 328", "Bộ luật Dân sự 2015", "Các bên xử lý tiền đặt cọc theo thỏa thuận và quy định pháp luật dân sự."),
        True,
        None,
    ),
    (
        "company_fact_lookup",
        "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?",
        TaskType.LEGAL_LOOKUP.value,
        "answer_complete",
        law_doc("Điều 111", "Luật Doanh nghiệp 2020", "Công ty cổ phần phải có ít nhất ba cổ đông và không hạn chế số lượng tối đa."),
        True,
        None,
    ),
    (
        "traffic_fine_lookup",
        "Không đội mũ bảo hiểm khi ngồi sau xe máy bị phạt bao nhiêu?",
        TaskType.LEGAL_LOOKUP.value,
        "answer_complete",
        law_doc("Điều 30", "Luật Giao thông đường bộ", "Người điều khiển và người ngồi trên xe mô tô phải đội mũ bảo hiểm."),
        True,
        None,
    ),
    (
        "family_case",
        "Tôi muốn ly hôn và đang trực tiếp nuôi con nhỏ, tòa xem xét điều gì?",
        TaskType.LEGAL_LOOKUP.value,
        "answer_complete",
        law_doc("Điều 81", "Luật Hôn nhân và Gia đình 2014", "Việc trông nom, chăm sóc, nuôi dưỡng con được xem xét theo quyền lợi mọi mặt của con."),
        True,
        None,
    ),
    (
        "general_checklist",
        "Lập checklist giấy tờ cần bàn giao khi nghỉ việc.",
        TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
        "answer_complete",
        law_doc("Điều 48", "Bộ luật Lao động 2019", "Khi chấm dứt hợp đồng, các bên thanh toán đầy đủ và hoàn tất thủ tục liên quan."),
        True,
        None,
    ),
    (
        "environmental_law_lookup",
        "Điều 1 Luật số 82/2015/QH13 điều chỉnh những vấn đề nào về tài nguyên và môi trường biển?",
        TaskType.LEGAL_LOOKUP.value,
        "answer_complete",
        law_doc("Điều 1", "Luật Tài nguyên, môi trường biển và hải đảo 2015", "Luật quy định quản lý tổng hợp tài nguyên, bảo vệ môi trường biển và hải đảo cùng quyền, nghĩa vụ của cơ quan, tổ chức, cá nhân liên quan."),
        True,
        None,
    ),
    (
        "no_evidence",
        "Quy định hiện hành cho một tình huống pháp lý rất cụ thể này là gì?",
        TaskType.LEGAL_LOOKUP.value,
        "insufficient_evidence",
        None,
        False,
        None,
    ),
    (
        "out_of_scope",
        "Hướng dẫn cách nấu phở bò Nam Định?",
        TaskType.LEGAL_LOOKUP.value,
        "out_of_scope",
        None,
        False,
        None,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case_id,query,task,reason,document,with_evidence,active_case",
    CASES,
    ids=[case[0] for case in CASES],
)
async def test_basic_user_trajectory(case_id, query, task, reason, document, with_evidence, active_case):
    state = await run_workflow(
        query,
        user_id="trajectory-user",
        conversation_id=f"conversation-{case_id}",
        deps=deps(active_case=active_case, document=document, with_evidence=with_evidence),
    )

    assert state["task_type"] == task
    assert state["termination_reason"] == reason
    assert state["missing_facts"] == []
    if reason == "answer_complete":
        assert state["citation_valid"] is True
        assert state["citations"]
    if reason == "insufficient_evidence":
        assert state["source"] == "error"
        assert "retrieve_web" not in state["action_sequence"]
