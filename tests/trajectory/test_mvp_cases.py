from __future__ import annotations

import pytest

from epr_agent.agent.graph import WorkflowDependencies, run_workflow
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


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


def law_doc():
    return DocumentRecord(
        content="Tài liệu pháp luật EPR dùng để đối chiếu nghĩa vụ, sản phẩm, vật liệu và hình thức thực hiện. " * 4,
        metadata={"Dieu": "Điều 77", "source": "Nghị định 08/2022/NĐ-CP", "Corpus_Version": "epr-law-structure-v2"},
        document_id="law-77",
        source="legal",
    )


def deps(*, active_case=None, with_evidence=True):
    return WorkflowDependencies(
        history=HistoryDouble(active_case),
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=StaticRetrievalGateway(legal_documents=[law_doc()] if with_evidence else []),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway(),
        planner=BoundedPlanner(),
    )


CASES = [
    ("assessment_full_1", "Tôi là nhà sản xuất bao bì nhựa tại thị trường Việt Nam, có phải thực hiện EPR không?", "answer_complete", "assess_epr_obligation", True, None),
    ("assessment_full_2", "Doanh nghiệp tôi là nhà nhập khẩu chai nhựa vào thị trường Việt Nam, có phải tuân thủ EPR không?", "answer_complete", "assess_epr_obligation", True, None),
    ("assessment_full_3", "Công ty tôi sản xuất pin nhựa tại Việt Nam, có phải thực hiện EPR không?", "answer_complete", "assess_epr_obligation", True, None),
    ("assessment_missing_1", "Tôi là nhà sản xuất, có phải thực hiện EPR không?", "awaiting_user_input", "assess_epr_obligation", False, None),
    ("assessment_missing_2", "Tôi là nhà sản xuất bao bì, có phải thực hiện EPR không?", "awaiting_user_input", "assess_epr_obligation", False, None),
    ("assessment_missing_3", "Tôi là nhà sản xuất nhựa, có phải thực hiện EPR không?", "awaiting_user_input", "assess_epr_obligation", False, None),
    ("resume_assessment", "Vật liệu là nhựa", "answer_complete", "assess_epr_obligation", True, {"task_type": "assess_epr_obligation", "facts": {"business_role": "nhà sản xuất", "product_or_packaging": "bao bì", "activity_scope": "thị trường Việt Nam"}}),
    ("resume_checklist", "Vật liệu là giấy", "answer_complete", "build_compliance_checklist", True, {"task_type": "build_compliance_checklist", "facts": {"business_role": "nhà nhập khẩu", "product_or_packaging": "bao bì", "activity_scope": "thị trường Việt Nam"}}),
    ("checklist_full_1", "Lập checklist tuân thủ EPR cho nhà sản xuất bao bì nhựa tại thị trường Việt Nam", "answer_complete", "build_compliance_checklist", True, None),
    ("checklist_full_2", "Các bước cần làm EPR cho nhà nhập khẩu chai nhựa vào thị trường Việt Nam", "answer_complete", "build_compliance_checklist", True, None),
    ("evidence_fallback", "EPR và trách nhiệm tái chế hiện nay quy định thế nào?", "web_fallback", "legal_lookup", False, None),
    ("out_of_scope", "Quy định về chứng khoán là gì?", "out_of_scope", "legal_lookup", False, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,query,reason,task,with_evidence,active_case", CASES, ids=[case[0] for case in CASES])
async def test_mvp_trajectory(case_id, query, reason, task, with_evidence, active_case):
    state = await run_workflow(
        query,
        user_id="trajectory-user",
        conversation_id=f"conversation-{case_id}",
        deps=deps(active_case=active_case, with_evidence=with_evidence),
    )
    assert state["task_type"] == task
    assert state["termination_reason"] == reason
    if reason == "awaiting_user_input":
        assert state["missing_facts"]
    if reason == "answer_complete":
        assert state["citation_valid"] is True
    if reason == "web_fallback":
        assert state["source"] == "web_search"
