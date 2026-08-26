import pytest
from pydantic import ValidationError

from epr_agent.domain.legal import explicit_anchors
from epr_agent.domain.models import TaskType
from epr_agent.domain.tasks import (
    ExtractedFacts,
    TaskUnderstanding,
    build_follow_up_question,
    classify_route,
    classify_task,
    detect_legal_domain,
    extract_facts,
    is_greeting,
    missing_facts,
    rewrite_follow_up,
)


def test_classify_the_three_mvp_tasks():
    assert classify_task("EPR là gì?") == TaskType.LEGAL_LOOKUP
    assert classify_task("Tôi là nhà sản xuất bao bì nhựa, có phải thực hiện EPR không?") == TaskType.CASE_ASSESSMENT
    assert classify_task("Lập checklist tuân thủ EPR cho doanh nghiệp") == TaskType.BUILD_COMPLIANCE_CHECKLIST


def test_classify_case_assessment_is_domain_agnostic():
    assert classify_task("Tôi là nhân viên bị công ty sa thải đột ngột, có được bồi thường không?") == TaskType.CASE_ASSESSMENT
    assert classify_task("Công ty tôi có nghĩa vụ đăng ký kinh doanh khi bán hàng online không?") == TaskType.CASE_ASSESSMENT
    assert classify_task("Chủ nhà tăng giá thuê giữa chừng, tôi phải làm gì?") == TaskType.CASE_ASSESSMENT
    assert classify_task("Doanh nghiệp nhập khẩu bao bì có phải thực hiện EPR không?") == TaskType.CASE_ASSESSMENT


def test_classify_general_factual_questions_stay_lookup():
    assert classify_task("Mức phạt nồng độ cồn hiện hành là bao nhiêu?") == TaskType.LEGAL_LOOKUP
    assert classify_task("Điều 36 Bộ luật Lao động quy định gì?") == TaskType.LEGAL_LOOKUP
    assert classify_task("Thời gian thử việc tối đa bao lâu?") == TaskType.LEGAL_LOOKUP


def test_factual_corporate_and_instrument_questions_do_not_open_case_forms():
    assert classify_task(
        "Luật Doanh nghiệp quy định công ty cổ phần cần tối thiểu bao nhiêu cổ đông sáng lập?"
    ) == TaskType.LEGAL_LOOKUP
    assert classify_route(
        "Luật Doanh nghiệp quy định công ty cổ phần cần tối thiểu bao nhiêu cổ đông sáng lập?"
    ).value == "legal_lookup"
    assert classify_task("Luật số 08/2026/QH16 có hiệu lực từ ngày nào?") == TaskType.LEGAL_LOOKUP


def test_non_legal_unknown_query_is_closed_before_retrieval():
    assert classify_route("Giá Bitcoin hôm nay là bao nhiêu?").value == "out_of_scope"


def test_greeting_with_legal_request_is_not_chitchat():
    assert is_greeting("Xin chào, bạn có thể giúp tôi tra cứu luật không?") is False


def test_explicit_anchor_parser_supports_law_instrument_numbers():
    anchors = explicit_anchors("Luật số 08/2026/QH16 có hiệu lực từ ngày nào?")
    assert [anchor.document_number for anchor in anchors] == ["08/2026/QH16"]


def test_detect_legal_domain_for_supported_areas():
    assert detect_legal_domain("Tôi bị sa thải trái luật, có được bồi thường không?") == "labor"
    assert detect_legal_domain("Chủ nhà tăng giá thuê nhà giữa chừng có đúng không?") == "civil_contract"
    assert detect_legal_domain("Tôi muốn ly hôn đơn phương cần làm gì?") == "marriage_family"
    assert detect_legal_domain("Cổ đông sở hữu 7% có quyền triệu tập họp không?") == "corporate"
    assert detect_legal_domain("Đất nhà tôi bị thu hồi thì bồi thường thế nào?") == "land"
    assert detect_legal_domain("Mức phạt nồng độ cồn khi lái xe là bao nhiêu?") == "traffic"
    assert detect_legal_domain("Công ty tôi có nghĩa vụ tái chế bao bì không?") == "epr"
    assert detect_legal_domain("Một con mèo có mấy chân?") == "general"


def test_extract_facts_does_not_infer_unspecified_values():
    facts = extract_facts("Tôi là nhà sản xuất bao bì nhựa")
    assert facts == {
        "business_role": "nhà sản xuất",
        "product_or_packaging": "bao bì",
        "material": "nhựa",
    }
    assert missing_facts(TaskType.CASE_ASSESSMENT, {"business_role": "nhà sản xuất"}) == [
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
    assert result.task_type == TaskType.CASE_ASSESSMENT
    assert result.missing_facts == ["product_or_packaging"]
    with pytest.raises(ValidationError):
        TaskUnderstanding(task_type="free_form_tool_call")
