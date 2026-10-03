from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.understanding import StructuredTaskUnderstandingGateway
from vietnam_legal_agent.domain.routes import RouteType
from vietnam_legal_agent.domain.tasks import TaskUnderstanding


@pytest.mark.asyncio
async def test_obvious_greeting_skips_route_model(monkeypatch):
    def unexpected_model_call():
        raise AssertionError("the deterministic greeting route should avoid a model call")

    monkeypatch.setattr("vietnam_legal_agent.infra.llm_instances.get_llm_router", unexpected_model_call)

    result = await StructuredTaskUnderstandingGateway().understand(
        "Xin chào, bạn có thể giúp tôi những gì?", [], "", None
    )

    assert result.route is RouteType.CHITCHAT


@pytest.mark.asyncio
async def test_general_lookup_keeps_deterministic_route_and_accepts_semantic_search_variants(monkeypatch):
    class Model:
        async def ainvoke(self, _messages):
            return TaskUnderstanding(
                task_type="case_assessment",
                route=RouteType.CASE_ASSESSMENT,
                standalone_query="",
                retrieval_queries=["thời gian thử việc tối đa", "căn cứ pháp lý trong Bộ luật Lao động"],
                confidence=0.95,
            )

    class Router:
        def with_structured_output(self, _schema):
            return Model()

    monkeypatch.setattr("vietnam_legal_agent.infra.llm_instances.get_llm_router", lambda: Router())

    result = await StructuredTaskUnderstandingGateway().understand(
        "Thời gian thử việc tối đa được quy định ở đâu?", [], "", None
    )

    assert result.route is RouteType.LEGAL_LOOKUP
    assert result.task_type.value == "legal_lookup"
    assert result.retrieval_queries == ["thời gian thử việc tối đa"]


@pytest.mark.asyncio
async def test_general_rights_question_uses_complementary_focused_search_queries(monkeypatch):
    from vietnam_legal_agent.agent import understanding as understanding_module

    query = "Mua hàng online nhận sản phẩm lỗi thì người mua có quyền gì?"

    class PlanModel:
        async def ainvoke(self, _messages):
            return TaskUnderstanding(
                task_type="legal_lookup",
                route=RouteType.CASE_ASSESSMENT,
                standalone_query=query,
                retrieval_queries=["quyền người tiêu dùng khi nhận sản phẩm lỗi"],
            )

    class RewriteModel:
        async def ainvoke(self, _messages):
            return {
                "queries": [
                    "quyền người tiêu dùng với hàng hóa có khuyết tật",
                    "trách nhiệm khi cung cấp hàng hóa có khuyết tật",
                ]
            }

    class Router:
        def with_structured_output(self, schema):
            return RewriteModel() if schema is understanding_module._LegalRetrievalQueries else PlanModel()

    monkeypatch.setattr("vietnam_legal_agent.infra.llm_instances.get_llm_router", lambda: Router())

    result = await StructuredTaskUnderstandingGateway().understand(query, [], "", None)

    assert result.route is RouteType.LEGAL_LOOKUP
    assert result.retrieval_queries == [
        "quyền người tiêu dùng với hàng hóa có khuyết tật",
        "trách nhiệm khi cung cấp hàng hóa có khuyết tật",
    ]
    assert "sự kiện, chủ thể, thời điểm, điều kiện và kết quả" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "Dùng thuật ngữ pháp lý thông dụng hoặc tiêu đề chế định khi phù hợp" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "giữ nguyên sự chưa rõ đó thay vì giả định" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "thay đổi một thỏa thuận đang có hiệu lực" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "Giữ lại trong ít nhất một truy vấn thuật ngữ cụ thể" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "không đổi việc bị từ chối bảo hành thành câu hỏi chung về hàng hóa có lỗi" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "chủ thể và động từ nghĩa vụ thường dùng trong chính quy định áp dụng" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "trả về hai truy vấn bổ trợ thay vì gộp mọi chi tiết vào một câu rộng" in understanding_module._RETRIEVAL_QUERY_PROMPT
    assert "cổ đông" not in understanding_module._RETRIEVAL_QUERY_PROMPT


@pytest.mark.asyncio
async def test_case_assessment_also_gets_a_legal_retrieval_rewrite(monkeypatch):
    from vietnam_legal_agent.agent import understanding as understanding_module

    query = "Tôi cho bạn vay tiền, có giấy viết tay ghi ngày trả nhưng không ghi lãi. Quá hạn rồi thì bên vay có phải trả lãi chậm trả không?"

    class PlanModel:
        async def ainvoke(self, _messages):
            return TaskUnderstanding(
                task_type="case_assessment",
                route=RouteType.CASE_ASSESSMENT,
                standalone_query=query,
                retrieval_queries=[],
            )

    class RewriteModel:
        async def ainvoke(self, _messages):
            return {
                "queries": [
                    "lãi do chậm thực hiện nghĩa vụ trả tiền khi đến hạn",
                    "nghĩa vụ trả lãi trên khoản tiền chậm trả khi không có thỏa thuận",
                ]
            }

    class Router:
        def with_structured_output(self, schema):
            return RewriteModel() if schema is understanding_module._LegalRetrievalQueries else PlanModel()

    monkeypatch.setattr("vietnam_legal_agent.infra.llm_instances.get_llm_router", lambda: Router())

    result = await StructuredTaskUnderstandingGateway().understand(query, [], "", None)

    assert result.route is RouteType.CASE_ASSESSMENT
    assert result.retrieval_queries == [
        "lãi do chậm thực hiện nghĩa vụ trả tiền khi đến hạn",
        "nghĩa vụ trả lãi trên khoản tiền chậm trả khi không có thỏa thuận",
    ]


@pytest.mark.asyncio
async def test_model_case_assessment_is_not_replaced_by_narrow_fallback(monkeypatch):
    class Model:
        async def ainvoke(self, _messages):
            return TaskUnderstanding(
                task_type="case_assessment",
                route=RouteType.CASE_ASSESSMENT,
                standalone_query="",
                confidence=0.9,
            )

    class Router:
        def with_structured_output(self, _schema):
            return Model()

    monkeypatch.setattr("vietnam_legal_agent.infra.llm_instances.get_llm_router", lambda: Router())

    result = await StructuredTaskUnderstandingGateway().understand(
        "Tôi làm thêm giờ nhưng không được trả lương, cần làm gì?", [], "", None
    )

    assert result.route is RouteType.CASE_ASSESSMENT
    assert result.task_type.value == "case_assessment"


@pytest.mark.asyncio
async def test_generic_hypothetical_is_not_routed_as_a_personal_case(monkeypatch):
    from vietnam_legal_agent.agent import understanding as understanding_module

    query = "Bên nhận đặt cọc từ chối ký hợp đồng thì phải chịu hậu quả gì?"

    class PlanModel:
        async def ainvoke(self, _messages):
            return TaskUnderstanding(
                task_type="case_assessment",
                route=RouteType.CASE_ASSESSMENT,
                standalone_query=query,
                confidence=0.95,
            )

    class RewriteModel:
        async def ainvoke(self, _messages):
            return {"queries": ["hậu quả bên nhận đặt cọc từ chối giao kết hợp đồng"]}

    class Router:
        def with_structured_output(self, schema):
            return RewriteModel() if schema is understanding_module._LegalRetrievalQueries else PlanModel()

    monkeypatch.setattr("vietnam_legal_agent.infra.llm_instances.get_llm_router", lambda: Router())

    result = await StructuredTaskUnderstandingGateway().understand(query, [], "", None)

    assert result.route is RouteType.LEGAL_LOOKUP
    assert result.task_type.value == "legal_lookup"
    assert result.retrieval_queries == ["hậu quả bên nhận đặt cọc từ chối giao kết hợp đồng"]
