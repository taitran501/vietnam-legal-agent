from __future__ import annotations

import pytest

from epr_agent.agent.understanding import StructuredTaskUnderstandingGateway
from epr_agent.domain.routes import RouteType


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        ("Xin chào, bạn có thể giúp tôi những gì?", RouteType.CHITCHAT),
        (
            "Công ty tôi nhập khẩu chai nhựa PET để đóng nước bán tại Việt Nam. "
            + "Doanh nghiệp cần kiểm tra những nghĩa vụ EPR nào, và căn cứ pháp lý ở đâu?",
            RouteType.LEGAL_LOOKUP,
        ),
    ],
)
async def test_obvious_greeting_and_general_lookup_skip_route_model(query, expected_route, monkeypatch):
    def unexpected_model_call():
        raise AssertionError("the deterministic route should avoid an unnecessary model call")

    monkeypatch.setattr("epr_agent.infra.llm_instances.get_llm_router", unexpected_model_call)

    result = await StructuredTaskUnderstandingGateway().understand(query, [], "", None)

    assert result.route is expected_route
