"""Unit tests for the autonomous agent Tool Registry."""

from __future__ import annotations

import pytest

from epr_agent.agent.tool_registry import (
    ALL_AGENT_TOOLS,
    ToolDependencies,
    ask_user_for_clarification,
    calculate_statutory_amounts,
    evaluate_legal_case,
    get_case_form_fields,
    load_conversation_context,
    lookup_answer_cache,
    search_legal_provisions,
    search_web_official,
    set_tool_dependencies,
)
from epr_agent.domain.epr_rules import CaseFormResolver
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import CachedAnswer
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.history import ContextSnapshot, HistoryGateway
from epr_agent.tools.retrieval import StaticRetrievalGateway


class FakeHistoryGateway(HistoryGateway):
    def __init__(self, snapshot: ContextSnapshot | None = None) -> None:
        self.snapshot = snapshot or ContextSnapshot(history=[], summary="", active_case=None)

    async def initialize(self) -> None:
        pass

    async def load(self, user_id: str, conversation_id: str, max_messages: int = 6) -> ContextSnapshot:
        return self.snapshot

    async def save_exchange(self, user_id: str, conversation_id: str, user_query: str, assistant_answer: str, metadata: dict | None = None) -> int:
        return 1

    async def save_case(self, user_id: str, conversation_id: str, active_case: dict) -> dict:
        return active_case

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        pass

    async def record_run(self, state: dict, started_at: float, ended_at: float) -> None:
        pass


class FakeGenerationGateway:
    async def chitchat(self, query: str, history: list) -> str:
        return "Xin chào!"

    async def answer(self, task_type: str, query: str, documents: list, facts: dict) -> str:
        return "Câu trả lời mẫu [1]."

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]:
        return "Kết quả tìm kiếm web", [
            DocumentRecord(content="Văn bản chính thức tại vbpl.vn", document_id="web-1", source="web", metadata={"title": "Nghị định 08", "official_url": "https://vbpl.vn/1", "authority": "official"})
        ]

    async def repair(self, answer: str, documents: list, task_type: str) -> str:
        return answer


class FakeCache:
    def __init__(self, cached: CachedAnswer | None = None) -> None:
        self.cached = cached

    async def lookup(self, task_type, query: str, route: str = "legal_lookup"):
        return self.cached, "test-cache-key"

    async def store(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def inject_test_deps():
    sample_doc = DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế sản phẩm bao bì của nhà sản xuất, nhập khẩu theo quy định của pháp luật bảo vệ môi trường.",
        document_id="doc-1",
        score=0.9,
        source="legal",
        metadata={"legal_anchor": "Điều 77", "Dieu": "77", "source_title": "Luật BVMT 2020", "source": "Luật BVMT 2020"},
    )
    deps = ToolDependencies(
        retrieval=StaticRetrievalGateway(legal_documents=[sample_doc]),
        evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=50),
        generation=FakeGenerationGateway(),
        cache=FakeCache(),
        history=FakeHistoryGateway(),
        case_resolver=CaseFormResolver(),
    )
    set_tool_dependencies(deps)
    yield
    set_tool_dependencies(None)


def test_tool_count():
    assert len(ALL_AGENT_TOOLS) == 8


@pytest.mark.asyncio
async def test_evaluate_legal_case_multi_domain():
    # Labor domain evaluation
    labor_res = await evaluate_legal_case(
        legal_domain="labor",
        facts={"dispute_type": "đơn phương sa thải", "monthly_salary_vnd": "10000000"},
    )
    assert labor_res["ok"] is True
    assert labor_res["domain"] == "labor"

    # Corporate domain evaluation
    corp_res = await evaluate_legal_case(
        legal_domain="corporate",
        facts={"shareholder_ratio_percent": "6.0"},
    )
    assert corp_res["ok"] is True
    assert corp_res["status"] == "threshold_met"


@pytest.mark.asyncio
async def test_calculate_statutory_amounts_tool():
    res = await calculate_statutory_amounts(
        calculation_type="overtime_salary",
        parameters={"hourly_wage_vnd": 60000, "overtime_hours": 5, "day_type": "weekend"},
    )
    assert res["ok"] is True
    assert res["statutory_rate_percent"] == 200
    assert res["total_overtime_pay_vnd"] == 600_000


@pytest.mark.asyncio
async def test_search_legal_provisions_sufficient():
    result = await search_legal_provisions("Điều 77 trách nhiệm tái chế")
    assert result["ok"] is True
    assert result["total_found"] == 1
    assert result["evidence_sufficient"] is True
    assert len(result["documents"]) == 1
    assert result["documents"][0]["metadata"]["legal_anchor"] == "Điều 77"


@pytest.mark.asyncio
async def test_search_legal_provisions_not_found():
    deps = ToolDependencies(
        retrieval=StaticRetrievalGateway(legal_documents=[]),
        evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=50),
        generation=FakeGenerationGateway(),
        cache=FakeCache(),
        history=FakeHistoryGateway(),
        case_resolver=CaseFormResolver(),
    )
    set_tool_dependencies(deps)
    result = await search_legal_provisions("Điều 999 quy định gì")
    assert result["ok"] is True
    assert result["evidence_sufficient"] is False
    assert result["total_found"] == 0
    assert result["suggested_followup_query"] is not None


@pytest.mark.asyncio
async def test_search_web_official():
    result = await search_web_official("Quy định EPR mới nhất")
    assert result["ok"] is True
    assert result["total_found"] == 1
    assert "vbpl.vn" in result["documents"][0]["content"]


@pytest.mark.asyncio
async def test_lookup_answer_cache_miss():
    result = await lookup_answer_cache("Câu hỏi chưa có cache")
    assert result["ok"] is True
    assert result["hit"] is False
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_lookup_answer_cache_hit():
    cached = CachedAnswer(
        answer="Trách nhiệm tái chế quy định tại Điều 77 [1].",
        evidence=[{"content": "Điều 77 quy định...", "document_id": "doc-1", "metadata": {"legal_anchor": "Điều 77"}}],
        citations=[{"index": 1, "document_id": "doc-1", "label": "Điều 77"}],
        source="legal",
    )
    deps = ToolDependencies(
        retrieval=StaticRetrievalGateway(),
        evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=10),
        generation=FakeGenerationGateway(),
        cache=FakeCache(cached=cached),
        history=FakeHistoryGateway(),
        case_resolver=CaseFormResolver(),
    )
    set_tool_dependencies(deps)
    result = await lookup_answer_cache("Điều 77")
    assert result["ok"] is True
    assert result["hit"] is True
    assert "[1]" in result["answer"]


@pytest.mark.asyncio
async def test_evaluate_legal_case_missing_facts():
    result = await evaluate_legal_case("epr", {"business_role": "manufacturer"})
    assert result["ok"] is True
    assert result["status"] == "needs_information"
    assert len(result["missing_facts"]) > 0


@pytest.mark.asyncio
async def test_evaluate_legal_case_complete():
    facts = {
        "business_role": "manufacturer",
        "object_kind": "commercial_packaging",
        "product_group": "bao_bi",
        "packaged_goods_category": "thuc_pham",
        "material": "pet",
        "market_placement": "vietnam_market",
        "activity_purpose": "commercial",
        "annual_revenue_vnd": "40000000000",
        "reused_by_producer": "no",
    }
    result = await evaluate_legal_case("epr", facts)
    assert result["ok"] is True
    assert result["status"] in {"likely_in_scope", "likely_out_of_scope", "needs_information", "cannot_determine"}


@pytest.mark.asyncio
async def test_evaluate_legal_case_traffic_domain():
    result = await evaluate_legal_case(
        "traffic",
        {"vehicle_type": "xe mô tô", "violation_act": "vượt đèn đỏ"},
    )
    assert result["ok"] is True
    assert result["domain"] == "traffic"
    assert "xe mô tô" in str(result.get("conclusion") or "")
    assert "Điều 6 Nghị định 100/2019/NĐ-CP" in str(result.get("applicable_provisions") or "")


@pytest.mark.asyncio
async def test_get_case_form_fields():
    result = await get_case_form_fields("assess_epr_obligation", {"business_role": "manufacturer"})
    assert result["ok"] is True
    assert len(result["fields"]) > 0
    assert "object_kind" in result["missing_facts"]


@pytest.mark.asyncio
async def test_load_conversation_context():
    snapshot = ContextSnapshot(
        history=[{"role": "user", "content": "Chào bạn"}],
        summary="Đang trao đổi về EPR",
        active_case={"task_type": "assess_epr_obligation"},
    )
    deps = ToolDependencies(
        retrieval=StaticRetrievalGateway(),
        evidence_evaluator=EvidenceEvaluator(),
        generation=FakeGenerationGateway(),
        cache=FakeCache(),
        history=FakeHistoryGateway(snapshot=snapshot),
        case_resolver=CaseFormResolver(),
    )
    set_tool_dependencies(deps)
    result = await load_conversation_context("u1", "c1")
    assert result["ok"] is True
    assert len(result["history_messages"]) == 1
    assert result["has_active_case"] is True


@pytest.mark.asyncio
async def test_ask_user_for_clarification():
    result = await ask_user_for_clarification("Vui lòng cho biết vật liệu bao bì?", ["material"])
    assert result["ok"] is True
    assert result["awaiting_user_input"] is True
    assert result["missing_fields"] == ["material"]
