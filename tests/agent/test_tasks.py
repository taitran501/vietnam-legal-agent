import pytest
from pydantic import ValidationError

from epr_agent.domain.models import TaskType
from epr_agent.domain.tasks import (
    ExtractedFacts,
    TaskUnderstanding,
    build_follow_up_question,
    classify_task,
    extract_facts,
    missing_facts,
    rewrite_follow_up,
)


def test_classify_the_three_mvp_tasks():
    assert classify_task("EPR là gì?") == TaskType.LEGAL_LOOKUP
    assert classify_task("Tôi là nhà sản xuất bao bì nhựa, có phải thực hiện EPR không?") == TaskType.ASSESS_EPR_OBLIGATION
    assert classify_task("Lập checklist tuân thủ EPR cho doanh nghiệp") == TaskType.BUILD_COMPLIANCE_CHECKLIST


def test_extract_facts_does_not_infer_unspecified_values():
    facts = extract_facts("Tôi là nhà sản xuất bao bì nhựa")
    assert facts == {
        "business_role": "nhà sản xuất",
        "product_or_packaging": "bao bì",
        "material": "nhựa",
    }
    assert missing_facts(TaskType.ASSESS_EPR_OBLIGATION, {"business_role": "nhà sản xuất"}) == [
        "product_or_packaging",
        "material",
        "activity_scope",
    ]


def test_follow_up_is_rewritten_only_when_it_depends_on_context():
    history = [{"role": "user", "content": "Bao bì nhựa có phải tái chế không?"}]
    rewritten = rewrite_follow_up("Còn trường hợp đó thì sao?", history, None)
    assert "Bao bì nhựa" in rewritten
    assert "Còn trường hợp đó" in rewritten
    assert rewrite_follow_up("Điều 77 quy định gì?", history, None) == "Điều 77 quy định gì?"


def test_follow_up_question_explains_which_facts_are_missing():
    question = build_follow_up_question(
        TaskType.BUILD_COMPLIANCE_CHECKLIST,
        ["business_role", "material"],
    )
    assert "vai trò" in question
    assert "vật liệu" in question


def test_structured_understanding_has_a_closed_task_surface():
    result = TaskUnderstanding(
        task_type="assess_epr_obligation",
        is_follow_up=True,
        standalone_query="Doanh nghiệp sản xuất bao bì nhựa tại Việt Nam có phải thực hiện EPR không?",
        facts=ExtractedFacts(business_role="nhà sản xuất", material="nhựa"),
        missing_facts=["product_or_packaging", "unknown"],
        confidence=0.9,
    )
    assert result.task_type == TaskType.ASSESS_EPR_OBLIGATION
    assert result.missing_facts == ["product_or_packaging"]
    with pytest.raises(ValidationError):
        TaskUnderstanding(task_type="free_form_tool_call")
