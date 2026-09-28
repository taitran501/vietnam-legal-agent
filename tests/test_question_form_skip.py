"""Unit tests for Open-Design QuestionForm and Skip Flow Architecture."""

from __future__ import annotations

import pytest

from epr_agent.agent.tool_registry import ask_user_for_clarification, get_case_form_fields
from epr_agent.domain.legal_rules import (
    FormOptionModel,
    FormQuestionModel,
    LegalDomain,
    QuestionFormModel,
    UniversalCaseFormResolver,
)


def test_question_form_model_structure() -> None:
    """Test QuestionForm schema matches open-design form structure."""
    options = [
        FormOptionModel(label="HĐLĐ không xác định thời hạn", value="indefinite"),
        FormOptionModel(label="HĐLĐ xác định thời hạn (12-36 tháng)", value="definite"),
    ]
    question = FormQuestionModel(
        id="contract_type",
        label="Loại hợp đồng lao động đã ký",
        type="radio",
        options=options,
        required=True,
    )
    form = QuestionFormModel(
        id="form-labor-1",
        title="Thông tin bổ sung vụ việc lao động",
        domain="labor",
        questions=[question],
        allow_skip=True,
        submit_label="Tiếp tục",
        skip_label="Bỏ qua",
        helper_text="Bạn có thể chọn nhanh hoặc nhấn Bỏ qua.",
    )

    data = form.model_dump()
    assert data["allow_skip"] is True
    assert data["submit_label"] == "Tiếp tục"
    assert data["skip_label"] == "Bỏ qua"
    assert len(data["questions"]) == 1
    assert data["questions"][0]["options"][0]["value"] == "indefinite"


def test_universal_form_resolver_generates_open_design_form() -> None:
    """Test UniversalCaseFormResolver constructs open-design question form with allow_skip."""
    form_dict = UniversalCaseFormResolver.resolve_question_form(
        legal_domain=LegalDomain.LABOR.value,
        title="Xác định quyền lợi khi bị chấm dứt hợp đồng",
    )
    assert form_dict["domain"] == "labor"
    assert form_dict["allow_skip"] is True
    assert form_dict["submit_label"] == "Tiếp tục"
    assert form_dict["skip_label"] == "Bỏ qua"
    assert len(form_dict["questions"]) >= 3

    # Check question fields
    q_ids = [q["id"] for q in form_dict["questions"]]
    assert "contract_type" in q_ids
    assert "monthly_salary_vnd" in q_ids


@pytest.mark.asyncio
async def test_ask_user_for_clarification_tool_supports_skip() -> None:
    """Test ask_user_for_clarification tool encapsulates QuestionForm and allow_skip flag."""
    res = await ask_user_for_clarification(
        legal_domain="labor",
        question="Vui lòng cung cấp thêm thông tin hợp đồng",
        suggested_options=[
            {"label": "HĐ không xác định thời hạn", "value": "indefinite"},
            {"label": "HĐ xác định thời hạn", "value": "definite"},
        ],
    )
    assert res["status"] == "need_clarification"
    assert res["allow_skip"] is True
    assert res["skip_label"] == "Bỏ qua"
    assert "question_form" in res
    assert res["question_form"]["allow_skip"] is True


@pytest.mark.asyncio
async def test_get_case_form_fields_tool() -> None:
    """Test get_case_form_fields tool returns structured questions with allow_skip."""
    res = await get_case_form_fields(legal_domain="tax")
    assert res["domain"] == "tax"
    assert res["allow_skip"] is True
    assert "question_form" in res
    assert len(res["question_form"]["questions"]) >= 2
