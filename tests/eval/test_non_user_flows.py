"""Test suite and verification for Non-Expert / Layman User Query Flows.

Simulates real-world queries from non-legal, non-technical users such as:
1. Layman business descriptions (tiệm trà sữa, xưởng hộp xốp, bán hàng online)
2. Vague & conceptual questions ("EPR là gì, giải thích dễ hiểu")
3. Multi-turn step-by-step guidance & clarification
4. Common misconceptions (bán lẻ vs sản xuất/nhập khẩu)
5. Colloquial language & typo tolerance
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from epr_agent.agent.agent_loop import AgentRunConfig, AgentRunResult, EprAgentRunner
from epr_agent.agent.runtime import AgentWorkflowRuntime, WorkflowDependencies
from epr_agent.agent.tool_registry import ToolDependencies, set_tool_dependencies
from epr_agent.domain.epr_rules import CaseFormResolver, extract_explicit_epr_facts
from epr_agent.domain.models import DocumentRecord, TaskType, TerminationReason
from epr_agent.tools.cache import CachedAnswer
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.history import ContextSnapshot, HistoryGateway
from epr_agent.tools.retrieval import StaticRetrievalGateway


class MockHistory(HistoryGateway):
    def __init__(self, history: list | None = None, active_case: dict | None = None) -> None:
        self._history = history or []
        self._active_case = active_case

    async def initialize(self) -> None: pass
    async def load(self, user_id: str, conversation_id: str, max_messages: int = 6) -> ContextSnapshot:
        return ContextSnapshot(history=self._history, summary="", active_case=self._active_case)
    async def save_exchange(self, *args, **kwargs) -> int: return 1
    async def save_case(self, *args, **kwargs) -> dict: return {}
    async def clear_case(self, *args, **kwargs) -> None: pass
    async def record_run(self, *args, **kwargs) -> None: pass


class MockGen:
    async def chitchat(self, query: str, history: list) -> str:
        return "Chào bạn! Tôi có thể giải thích quy định EPR một cách đơn giản, dễ hiểu cho bạn."
    async def answer(self, *args, **kwargs) -> str: return "Trả lời mẫu"
    async def web(self, *args, **kwargs) -> tuple: return "web", []
    async def repair(self, *args, **kwargs) -> str: return ""


class MockCache:
    async def lookup(self, *args, **kwargs): return None, "key"
    async def store(self, *args, **kwargs): pass


@pytest.fixture(autouse=True)
def setup_environment():
    sample_docs = [
        DocumentRecord(
            content="Điều 77 Luật BVMT 2020 quy định nhà sản xuất, nhập khẩu sản phẩm, bao bì phải thực hiện trách nhiệm tái chế (EPR) khi đưa ra thị trường Việt Nam.",
            document_id="doc-dieu-77",
            score=0.95,
            source="legal",
            metadata={"legal_anchor": "Điều 77", "Dieu": "77", "source": "Luật BVMT 2020"},
        ),
        DocumentRecord(
            content="Nghị định 08/2022/NĐ-CP Điều 54 quy định ngưỡng miễn trừ trách nhiệm tái chế bao bì đối với nhà sản xuất có doanh thu bán hàng dưới 30 tỷ đồng/năm.",
            document_id="doc-dieu-54",
            score=0.92,
            source="legal",
            metadata={"legal_anchor": "Điều 54", "Dieu": "54", "source": "Nghị định 08/2022/NĐ-CP"},
        ),
        DocumentRecord(
            content="Nghị định 08/2022/NĐ-CP quy định đối tượng thực hiện EPR là tổ chức, cá nhân sản xuất hoặc nhập khẩu trực tiếp sản phẩm, bao bì. Cơ sở kinh doanh bán lẻ, sử dụng bao bì để đóng gói tại chỗ không phải là nhà sản xuất bao bì.",
            document_id="doc-retail",
            score=0.90,
            source="legal",
            metadata={"legal_anchor": "Điều 52", "Dieu": "52", "source": "Nghị định 08/2022/NĐ-CP"},
        ),
    ]
    tool_deps = ToolDependencies(
        retrieval=StaticRetrievalGateway(legal_documents=sample_docs),
        evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=10),
        generation=MockGen(),
        cache=MockCache(),
        history=MockHistory(),
        case_resolver=CaseFormResolver(),
    )
    set_tool_dependencies(tool_deps)
    yield
    set_tool_dependencies(None)


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES CHO NON-USER FLOWS
# ══════════════════════════════════════════════════════════════════════════════


def test_fact_extraction_from_layman_language():
    """Kiểm tra trích xuất fact khi người dùng dùng từ ngữ đời thường/bình dân."""
    # 1. Hộp xốp đựng cơm -> bao bì thương phẩm
    q1 = "Xưởng em làm hộp xốp đựng cơm bán cho quán ăn tại Việt Nam, doanh thu 15 tỷ"
    facts1 = extract_explicit_epr_facts(q1)
    assert facts1.get("business_role") is not None
    assert facts1["business_role"].value == "manufacturer"
    assert facts1.get("market_placement") is not None
    assert facts1["market_placement"].value == "vietnam_market"
    assert facts1.get("annual_revenue_vnd") is not None
    assert facts1["annual_revenue_vnd"].value == "15000000000"

    # 2. Xưởng sản xuất chai nhựa nhỏ bán trong nước
    q2 = "Công ty tôi là nhà sản xuất chai nhựa PET bán ở thị trường VN, doanh thu 45 tỷ một năm"
    facts2 = extract_explicit_epr_facts(q2)
    assert facts2["business_role"].value == "manufacturer"
    assert facts2["material"].value == "pet"
    assert facts2["market_placement"].value == "vietnam_market"
    assert facts2["annual_revenue_vnd"].value == "45000000000"

    # 3. Nhập khẩu trực tiếp
    q3 = "Bên em nhập khẩu ắc quy xe máy từ Trung Quốc về bán tại VN"
    facts3 = extract_explicit_epr_facts(q3)
    assert facts3["business_role"].value == "importer"
    assert facts3["product_group"].value == "ac_quy"
    assert facts3["market_placement"].value == "vietnam_market"


@pytest.mark.asyncio
async def test_non_user_vague_question_flow():
    """Người dùng không chuyên hỏi câu rất chung chung: 'EPR là gì vậy?'"""
    class VagueQueryLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: list) -> AIMessage:
            if self.calls == 0:
                self.calls += 1
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "search_legal_provisions", "args": {"query": "EPR trách nhiệm mở rộng nhà sản xuất Điều 77"}, "id": "c1"}],
                )
            return AIMessage(
                content="EPR (Extended Producer Responsibility) là quy định yêu cầu nhà sản xuất, nhập khẩu phải có trách nhiệm thu hồi và tái chế sản phẩm, bao bì do mình đưa ra thị trường [1].\n\nNói một cách đơn giản, nếu bạn sản xuất hoặc nhập khẩu các mặt hàng như bao bì, pin, ắc quy, dầu nhớt, săm lốp hay đồ điện tử, bạn sẽ phải đóng góp kinh phí hoặc tự tổ chức tái chế [1].",
            )

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=3), llm=VagueQueryLLM())
    result = await runner.run("EPR là gì vậy bạn? Giải thích dễ hiểu giúp tôi với")

    assert result.termination_reason == "answer_complete"
    assert "EPR" in result.answer
    assert "[1]" in result.answer
    assert len(result.trajectory) == 1
    assert result.trajectory[0].tool == "search_legal_provisions"


@pytest.mark.asyncio
async def test_non_user_retailer_misconception_flow():
    """Người dùng là chủ tiệm trà sữa hỏi: 'Tôi bán trà sữa dùng cốc nhựa có phải nộp tiền EPR không?'"""
    class RetailerLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: list) -> AIMessage:
            if self.calls == 0:
                self.calls += 1
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "search_legal_provisions", "args": {"query": "đối tượng chịu trách nhiệm EPR nhà sản xuất bao bì Điều 77"}, "id": "c1"}],
                )
            return AIMessage(
                content="Chào bạn, nếu bạn chỉ là cơ sở kinh doanh đồ uống (tiệm trà sữa) mua cốc nhựa có sẵn về để đựng nước bán cho khách, bạn là người sử dụng bao bì chứ KHÔNG phải là nhà sản xuất hoặc nhập khẩu cốc nhựa [1].\n\nDo đó, bạn KHÔNG phải thực hiện nghĩa vụ EPR hay nộp tiền tái chế cho số cốc nhựa này. Trách nhiệm EPR thuộc về đơn vị trực tiếp sản xuất ra chiếc cốc nhựa đó hoặc doanh nghiệp nhập khẩu cốc nhựa vào Việt Nam [1].",
            )

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=3), llm=RetailerLLM())
    result = await runner.run("Em mở tiệm trà sữa mua cốc nhựa về bán mang đi, em có bị bắt nộp phí EPR không?")

    assert result.termination_reason == "answer_complete"
    assert "KHÔNG phải" in result.answer or "không phải" in result.answer.lower()
    assert "[1]" in result.answer


@pytest.mark.asyncio
async def test_non_user_multi_turn_incomplete_flow():
    """Người dùng hỏi chưa đủ thông tin, Agent chủ động hỏi làm rõ từng bước."""
    # Turn 1: User chỉ nói "Tôi có xưởng sản xuất nhỏ, có phải làm EPR không?"
    class Step1LLM:
        async def ainvoke(self, messages: list) -> AIMessage:
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "ask_user_for_clarification",
                    "args": {
                        "question": "Chào bạn! Để xác định xưởng của bạn có thuộc diện thực hiện EPR hay không, bạn vui lòng cho biết:\n1. Xưởng bạn sản xuất sản phẩm/bao bì gì (ví dụ: chai nhựa, hộp giấy, ắc quy...)?\n2. Sản phẩm bán trong nước hay xuất khẩu?\n3. Doanh thu ước tính khoảng bao nhiêu tỷ đồng/năm?",
                        "missing_fields": ["product_group", "market_placement", "annual_revenue_vnd"],
                    },
                    "id": "clarify_1",
                }],
            )

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=2), llm=Step1LLM())
    result = await runner.run("Tôi có xưởng sản xuất nhỏ, có phải làm EPR không?")

    assert result.termination_reason == "awaiting_user_input"
    assert result.awaiting_user_input is True
    assert "sản xuất sản phẩm" in result.answer
    assert "Doanh thu" in result.answer


@pytest.mark.asyncio
async def test_non_user_exemption_conclusion_flow():
    """Người dùng cung cấp thông tin doanh thu thấp, Agent tính toán và kết luận miễn trừ rõ ràng."""
    class ExemptionLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: list) -> AIMessage:
            if self.calls == 0:
                self.calls += 1
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "evaluate_epr_obligation",
                        "args": {
                            "facts": {
                                "business_role": "manufacturer",
                                "object_kind": "commercial_packaging",
                                "product_group": "bao_bi",
                                "packaged_goods_category": "thuc_pham",
                                "material": "plastic",
                                "market_placement": "vietnam_market",
                                "annual_revenue_vnd": "12000000000",
                                "reused_by_producer": "no",
                            }
                        },
                        "id": "eval_1",
                    }],
                )
            if self.calls == 1:
                self.calls += 1
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "search_legal_provisions", "args": {"query": "ngưỡng miễn trừ doanh thu bao bì 30 tỷ Điều 54"}, "id": "search_1"}],
                )
            return AIMessage(
                content="Tin vui cho bạn: Xưởng sản xuất bao bì nhựa của bạn có doanh thu 12 tỷ đồng/năm (dưới mức 30 tỷ đồng/năm), nên thuộc diện ĐƯỢC MIỄN TRỪ trách nhiệm tái chế bao bì theo quy định tại Điều 54 Nghị định 08/2022/NĐ-CP [1].\n\nBạn không cần phải nộp tiền đóng góp tái chế (FSF) cho số bao bì này [1].",
            )

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=4), llm=ExemptionLLM())
    result = await runner.run(
        "Xưởng tôi sản xuất túi ni-lông bán cho các chợ ở Việt Nam, doanh thu 12 tỷ/năm",
        history=[],
        active_case=None,
    )

    assert result.termination_reason == "answer_complete"
    assert "MIỄN TRỪ" in result.answer or "miễn trừ" in result.answer.lower()
    assert "12 tỷ" in result.answer or "30 tỷ" in result.answer
    assert "[1]" in result.answer
