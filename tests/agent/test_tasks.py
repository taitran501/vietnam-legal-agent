import pytest
from pydantic import ValidationError

from vietnam_legal_agent.domain.legal import explicit_anchors
from vietnam_legal_agent.domain.models import TaskType
from vietnam_legal_agent.domain.tasks import (
    ExtractedFacts,
    TaskUnderstanding,
    build_follow_up_question,
    classify_route,
    classify_task,
    detect_legal_domain,
    extract_facts,
    is_context_dependent_query,
    is_greeting,
    missing_facts,
    research_requested,
    rewrite_follow_up,
)


def test_classifies_general_lookup_case_assessment_and_procedure_requests():
    assert classify_task(
        "Điều 25 Bộ luật Lao động quy định thời gian thử việc tối đa bao lâu?"
    ) == TaskType.LEGAL_LOOKUP
    assert classify_task(
        "Tôi bị công ty sa thải đột ngột, có được bồi thường không?"
    ) == TaskType.CASE_ASSESSMENT
    assert classify_task(
        "Các bước đăng ký thành lập công ty TNHH là gì?"
    ) == TaskType.BUILD_COMPLIANCE_CHECKLIST


def test_case_assessment_classification_spans_ordinary_legal_topics():
    queries = (
        "Tôi bị công ty sa thải đột ngột, có được bồi thường không?",
        "Chủ nhà tăng tiền thuê giữa hợp đồng, tôi phải làm gì?",
        "Đất nhà tôi bị thu hồi thì có được bồi thường không?",
        "Cổ đông công ty tôi không được chia cổ tức, tôi nên làm gì?",
    )
    assert all(classify_task(query) == TaskType.CASE_ASSESSMENT for query in queries)


def test_personal_legal_problems_route_to_assessment_across_domains():
    queries = (
        "Công ty cho tôi nghỉ việc đột ngột có đúng luật không?",
        "Tôi làm thêm giờ nhưng không được trả lương, cần làm gì?",
        "Chủ nhà giữ tiền cọc sau khi tôi trả nhà, tôi nên làm gì?",
    )
    assert all(classify_task(query) == TaskType.CASE_ASSESSMENT for query in queries)


def test_request_for_new_official_material_routes_to_web_research():
    query = "Tìm văn bản chính thức mới về thuế thu nhập cá nhân."
    assert research_requested(query)
    assert classify_route(query).value == "research_web"


def test_follow_up_detection_uses_word_boundaries_and_same_turn_context():
    assert not is_context_dependent_query(
        "Sếp nói thử việc thì không cần trả lương, có đúng không?"
    )
    assert not is_context_dependent_query(
        "Công ty cho tôi nghỉ việc. Việc này có đúng luật không?"
    )
    assert is_context_dependent_query("Việc này có đúng luật không?")


def test_general_questions_about_rules_stay_on_legal_lookup_route():
    queries = (
        "Mức phạt nồng độ cồn hiện hành là bao nhiêu?",
        "Điều 36 Bộ luật Lao động quy định gì?",
        "Thời gian thử việc tối đa bao lâu?",
        "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?",
        "Mua hàng online nhận sản phẩm lỗi thì người mua có quyền gì?",
        "Khi cha mẹ ly hôn, tòa án căn cứ vào đâu để quyết định người trực tiếp nuôi con?",
    )
    for query in queries:
        assert classify_task(query) == TaskType.LEGAL_LOOKUP
        assert classify_route(query).value == "legal_lookup"


def test_new_question_is_not_captured_by_an_unfinished_prior_assessment():
    active = {"task_type": "case_assessment", "facts": {"employment_issue": "late wages"}}
    query = "Luật thừa kế quy định thế nào?"

    assert classify_task(query, active_case=active) is TaskType.LEGAL_LOOKUP
    assert classify_route(query, active_case=active).value == "legal_lookup"


def test_non_legal_and_greeting_routes_are_kept_distinct():
    assert classify_route("Giá Bitcoin hôm nay là bao nhiêu?").value == "out_of_scope"
    assert not is_greeting("Xin chào, bạn có thể giúp tôi tra cứu luật không?")
    assert classify_route("alo ai vay").value == "chitchat"
    assert classify_route("chào bạn").value == "chitchat"


def test_explicit_anchor_parser_supports_instrument_numbers():
    anchors = explicit_anchors("Luật số 08/2026/QH16 có hiệu lực từ ngày nào?")
    assert [anchor.document_number for anchor in anchors] == ["08/2026/QH16"]


def test_domain_detection_does_not_route_on_a_single_recycling_keyword():
    assert detect_legal_domain("Giấy phép môi trường đối với cơ sở xử lý chất thải") == "environmental"
    assert detect_legal_domain("Tôi muốn hỏi một vấn đề pháp luật nói chung") == "general"
    assert detect_legal_domain("Mức phạt nồng độ cồn khi lái xe là bao nhiêu?") == "traffic"


def test_fact_extraction_does_not_apply_fixed_intake_fields():
    assert extract_facts("Tôi bị công ty chậm trả lương hơn hai tuần") == {}
    assert missing_facts(TaskType.CASE_ASSESSMENT, {"salary_delay": "hơn hai tuần"}) == []
    assert build_follow_up_question(TaskType.CASE_ASSESSMENT, []) == ""


def test_follow_up_rewrite_uses_context_without_changing_standalone_queries():
    history = [{"role": "user", "content": "Chủ nhà tăng tiền thuê giữa hợp đồng."}]
    rewritten = rewrite_follow_up("Còn trường hợp đó thì sao?", history, None)
    assert "Chủ nhà tăng tiền thuê" in rewritten
    query = "Điều 35 Bộ luật Lao động quy định gì?"
    assert rewrite_follow_up(query, history, None) == query


def test_understanding_keeps_open_facts_and_closed_task_types():
    result = TaskUnderstanding(
        task_type="case_assessment",
        is_follow_up=True,
        standalone_query="Tôi bị công ty chậm trả lương hơn hai tuần.",
        facts=ExtractedFacts(values={"salary_delay": "hơn hai tuần"}),
        missing_facts=["contract_type"],
        confidence=0.9,
    )
    assert result.task_type == TaskType.CASE_ASSESSMENT
    assert result.facts.compact() == {"salary_delay": "hơn hai tuần"}
    assert result.missing_facts == []
    with pytest.raises(ValidationError):
        TaskUnderstanding(task_type="free_form_tool_call")


def test_query_plan_cleans_and_bounds_model_generated_retrieval_queries():
    result = TaskUnderstanding(
        retrieval_queries=[
            "  thời gian thử việc  ",
            "thời gian thử việc",
            "Điều 25",
            "thêm biến thể",
        ],
    )
    assert result.retrieval_queries == ["thời gian thử việc"]
