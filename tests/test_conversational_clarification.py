from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.tool_registry import (
    ALL_AGENT_TOOLS,
    ask_user_for_clarification,
)


@pytest.mark.parametrize(
    "question",
    [
        "Công ty đã chậm trả lương trong bao lâu?",
        "Chủ nhà đã thông báo tăng tiền thuê bằng cách nào?",
        "Bạn muốn tra cứu thủ tục khiếu nại nào?",
    ],
)
@pytest.mark.asyncio
async def test_clarification_is_one_natural_language_question_without_a_form(question: str):
    result = await ask_user_for_clarification(question)

    assert result == {
        "action": "ask_user",
        "status": "need_clarification",
        "question": question,
        "awaiting_user_input": True,
        "ok": True,
    }
    assert "fields" not in result
    assert "question_form" not in result


def test_agent_toolset_has_no_case_form_or_fixed_intake_tool():
    tool_names = {tool.__name__ for tool in ALL_AGENT_TOOLS}
    assert "get_case_form_fields" not in tool_names
    assert "ask_user_for_clarification" in tool_names
