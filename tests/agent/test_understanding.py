from __future__ import annotations

import pytest

from epr_agent.agent.understanding import StructuredTaskUnderstandingGateway
from epr_agent.domain.routes import RouteType
from epr_agent.domain.tasks import TaskUnderstanding


@pytest.mark.asyncio
async def test_obvious_greeting_skips_route_model(monkeypatch):
    def unexpected_model_call():
        raise AssertionError("the deterministic greeting route should avoid a model call")

    monkeypatch.setattr("epr_agent.infra.llm_instances.get_llm_router", unexpected_model_call)

    result = await StructuredTaskUnderstandingGateway().understand(
        "Xin chào, bạn có thể giúp tôi những gì?", [], "", None
    )

    assert result.route is RouteType.CHITCHAT


@pytest.mark.asyncio
async def test_general_lookup_keeps_deterministic_route_and_accepts_semantic_search_variants(monkeypatch):
    class Model:
        async def ainvoke(self, _messages):
            return TaskUnderstanding(
                task_type="assess_epr_obligation",
                route=RouteType.CASE_ASSESSMENT,
                standalone_query="",
                retrieval_queries=["nghĩa vụ EPR về bao bì", "căn cứ pháp lý EPR"],
                confidence=0.95,
            )

    class Router:
        def with_structured_output(self, _schema):
            return Model()

    monkeypatch.setattr("epr_agent.infra.llm_instances.get_llm_router", lambda: Router())

    result = await StructuredTaskUnderstandingGateway().understand(
        "Nghĩa vụ EPR về bao bì được quy định ở đâu?", [], "", None
    )

    assert result.route is RouteType.LEGAL_LOOKUP
    assert result.task_type.value == "legal_lookup"
    assert result.retrieval_queries == ["nghĩa vụ EPR về bao bì", "căn cứ pháp lý EPR"]
