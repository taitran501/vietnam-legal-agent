"""Versioned, behavior-first fixtures for Pipeline V4 local evaluation.

The manifest is deliberately data-only.  Test oracles describe observable
workflow decisions and evidence requirements; they do not contain a golden
LLM answer string.
"""

from __future__ import annotations

from typing import Any


def _case(case_id: str, query: str, route: str, **extra: Any) -> dict[str, Any]:
    return {"id": case_id, "query": query, "expected_route": route, **extra}


def _assessment(
    case_id: str,
    query: str,
    *,
    product_group: str,
    expected_status: str = "likely_in_scope",
    facts: dict[str, str] | None = None,
    missing: list[str] | None = None,
    required_issues: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return _case(
        case_id,
        query,
        "case_assessment",
        product_group=product_group,
        supplied_facts=facts or {},
        expected_missing_facts=missing or [],
        required_issues=required_issues or ["actor", "covered_object", "market_scope", "exemption", "effective_date"],
        expected_outcome="completed" if not missing else "needs_information",
        expected_result_type="assessment" if not missing else "none",
        expected_assessment_status="needs_information" if missing else expected_status,
        forbidden=["answer_complete"] if missing else ["insufficient_evidence"],
        expected_ui="assessment_result" if not missing else "missing_facts",
        **extra,
    )


# Twelve completed assessments cover every EPR group represented by the rule
# pack, with different actors and packaging facts.
ASSESSMENT_COMPLETE_CASES = [
    _assessment(
        "assessment_bao_bi_nhua",
        "Tôi là nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng.",
        product_group="bao_bi",
    ),
    _assessment(
        "assessment_bao_bi_giay",
        "Tôi là nhà nhập khẩu bao bì giấy dùng cho mỹ phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng.",
        product_group="bao_bi",
    ),
    _assessment(
        "assessment_ac_quy",
        "Tôi là nhà sản xuất ắc quy kim loại, bán tại Việt Nam, kinh doanh thương mại.",
        product_group="ac_quy",
    ),
    _assessment(
        "assessment_pin",
        "Tôi là nhà nhập khẩu pin kim loại, đưa ra thị trường Việt Nam, kinh doanh thương mại.",
        product_group="pin",
    ),
    _assessment(
        "assessment_dau_nhot",
        "Tôi là nhà sản xuất dầu nhớt, đưa ra thị trường Việt Nam, kinh doanh thương mại.",
        product_group="dau_nhot",
    ),
    _assessment(
        "assessment_sam_lop",
        "Tôi là nhà nhập khẩu săm lốp cao su, bán tại Việt Nam, kinh doanh thương mại.",
        product_group="sam_lop",
    ),
    _assessment(
        "assessment_dien_tu",
        "Tôi là nhà sản xuất thiết bị điện tử, đưa ra thị trường Việt Nam, kinh doanh thương mại.",
        product_group="dien_tu",
    ),
    _assessment(
        "assessment_phuong_tien",
        "Tôi là nhà nhập khẩu ô tô, đưa ra thị trường Việt Nam, kinh doanh thương mại.",
        product_group="phuong_tien",
    ),
    _assessment(
        "assessment_pin_exported",
        "Tôi là nhà sản xuất pin kim loại bán tại Việt Nam, kinh doanh thương mại.",
        product_group="pin",
    ),
    _assessment(
        "assessment_ac_quy_importer",
        "Tôi là nhà nhập khẩu ắc quy, đưa ra thị trường Việt Nam, kinh doanh thương mại.",
        product_group="ac_quy",
    ),
    _assessment(
        "assessment_dien_tu_importer",
        "Tôi là nhà nhập khẩu máy tính điện tử, bán tại Việt Nam, kinh doanh thương mại.",
        product_group="dien_tu",
    ),
    _assessment(
        "assessment_bao_bi_plastic_other",
        "Tôi là nhà sản xuất bao bì nhựa dùng cho hàng hóa khác, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng.",
        product_group="bao_bi",
        expected_status="likely_out_of_scope",
    ),
]


ASSESSMENT_MISSING_CASES = [
    _assessment(
        "missing_role",
        "Đánh giá nghĩa vụ EPR cho doanh nghiệp tôi.",
        product_group="unknown",
        missing=["business_role", "object_kind", "product_group", "market_placement", "activity_purpose"],
    ),
    _assessment(
        "missing_object",
        "Tôi là nhà sản xuất, đưa ra thị trường Việt Nam, kinh doanh thương mại.",
        product_group="unknown",
        missing=["object_kind", "product_group"],
    ),
    _assessment(
        "missing_market",
        "Tôi là nhà sản xuất bao bì nhựa, kinh doanh thương mại.",
        product_group="bao_bi",
        missing=["market_placement", "packaged_goods_category"],
    ),
    _assessment(
        "missing_packaged_category",
        "Tôi là nhà sản xuất bao bì nhựa đưa ra thị trường Việt Nam, kinh doanh thương mại.",
        product_group="bao_bi",
        missing=["packaged_goods_category", "annual_revenue_vnd", "reused_by_producer"],
    ),
    _assessment(
        "missing_revenue",
        "Tôi là nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, không thu hồi để tái sử dụng.",
        product_group="bao_bi",
        missing=["annual_revenue_vnd"],
    ),
    _assessment(
        "missing_reuse",
        "Tôi là nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 40 tỷ đồng.",
        product_group="bao_bi",
        missing=["reused_by_producer"],
    ),
    _assessment(
        "missing_purpose",
        "Tôi là nhà sản xuất pin kim loại đưa ra thị trường Việt Nam.",
        product_group="pin",
        missing=["activity_purpose"],
        resume_query="Kinh doanh thương mại.",
        resume_expected_outcome="completed",
    ),
    _assessment(
        "missing_followup_1",
        "Còn trường hợp này thì sao?",
        product_group="unknown",
        missing=["business_role", "object_kind", "product_group", "market_placement", "activity_purpose"],
    ),
    _assessment(
        "missing_followup_2",
        "Vật liệu là nhựa.",
        product_group="unknown",
        missing=["business_role", "object_kind", "product_group", "market_placement", "activity_purpose"],
    ),
    _assessment(
        "missing_checklist_context",
        "Tôi cần lập checklist EPR.",
        product_group="unknown",
        missing=["business_role", "object_kind", "product_group", "market_placement", "activity_purpose"],
    ),
    _assessment(
        "missing_importer_scope",
        "Tôi là nhà nhập khẩu bao bì giấy.",
        product_group="bao_bi",
        missing=["market_placement", "packaged_goods_category", "activity_purpose"],
    ),
    _assessment(
        "missing_research_scope",
        "Tôi là nhà sản xuất dầu nhớt, hoạt động tại Việt Nam.",
        product_group="dau_nhot",
        missing=["market_placement"],
        resume_query="Đưa ra thị trường Việt Nam và kinh doanh thương mại.",
        resume_expected_outcome="completed",
    ),
]


EXEMPTION_CASES = [
    _assessment("exemption_export", "Tôi là nhà sản xuất pin, chỉ xuất khẩu toàn bộ sản phẩm.", product_group="pin", expected_status="likely_out_of_scope"),
    _assessment("exemption_reexport", "Tôi là nhà nhập khẩu dầu nhớt tạm nhập tái xuất.", product_group="dau_nhot", expected_status="likely_out_of_scope"),
    _assessment("exemption_research", "Tôi là nhà sản xuất pin đưa ra thị trường Việt Nam nhưng chỉ phục vụ nghiên cứu thử nghiệm.", product_group="pin", expected_status="likely_out_of_scope"),
    _assessment("exemption_low_revenue", "Tôi là nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 10 tỷ đồng, không thu hồi để tái sử dụng.", product_group="bao_bi", expected_status="likely_out_of_scope"),
    _case("scope_securities", "Quy định về chứng khoán là gì?", "out_of_scope", expected_outcome="out_of_scope", expected_result_type="none", expected_ui="safe_stop"),
    _case("scope_labor", "Luật lao động quy định gì về hợp đồng?", "out_of_scope", expected_outcome="out_of_scope", expected_result_type="none", expected_ui="safe_stop"),
    _case("scope_foreign_law", "Quy định EPR của EU là gì?", "legal_lookup", expected_outcome="insufficient_evidence", expected_result_type="none", expected_ui="safe_stop"),
    _case("scope_unrelated_tax", "Thuế thu nhập doanh nghiệp tính thế nào?", "out_of_scope", expected_outcome="out_of_scope", expected_result_type="none", expected_ui="safe_stop"),
]


INSUFFICIENT_EVIDENCE_CASES = [
    _case("evidence_missing_article", "Điều 999 quy định gì?", "legal_lookup", expected_outcome="insufficient_evidence", expected_result_type="none", expected_ui="safe_stop"),
    _case("evidence_missing_appendix", "Tỷ lệ tái chế của nhóm chưa có trong corpus là bao nhiêu?", "legal_lookup", expected_outcome="insufficient_evidence", expected_result_type="none", expected_ui="safe_stop"),
    _case("evidence_assessment_gap", "Tôi là nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng; cần áp dụng cho nhóm chưa có trong corpus.", "case_assessment", expected_outcome="insufficient_evidence", expected_result_type="none", expected_ui="safe_stop"),
    _case("evidence_checklist_gap", "Lập checklist EPR cho nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng; cần áp dụng cho nhóm chưa có trong corpus.", "compliance_checklist", expected_outcome="insufficient_evidence", expected_result_type="none", expected_ui="safe_stop"),
]


CHECKLIST_CASES = [
    _case(
        "checklist_complete_packaging",
        "Lập checklist EPR cho nhà sản xuất bao bì nhựa dùng cho thực phẩm, đưa ra thị trường Việt Nam, kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng.",
        "compliance_checklist",
        expected_outcome="completed",
        expected_result_type="checklist",
        expected_missing_facts=[],
        expected_ui="checklist_result",
        required_issues=["actor", "covered_object", "market_scope", "exemption", "effective_date", "recycling_rate", "implementation", "reporting", "financial"],
    ),
    _case(
        "checklist_complete_importer",
        "Các bước cần làm EPR cho nhà nhập khẩu pin kim loại bán tại Việt Nam, kinh doanh thương mại.",
        "compliance_checklist",
        expected_outcome="completed",
        expected_result_type="checklist",
        expected_missing_facts=[],
        expected_ui="checklist_result",
    ),
    _case(
        "checklist_missing_facts",
        "Lập checklist EPR cho doanh nghiệp tôi.",
        "compliance_checklist",
        expected_outcome="needs_information",
        expected_result_type="none",
        expected_missing_facts=["business_role", "object_kind", "product_group", "market_placement"],
        expected_ui="missing_facts",
    ),
    _case(
        "checklist_missing_packaging_facts",
        "Lập checklist EPR cho nhà sản xuất bao bì nhựa.",
        "compliance_checklist",
        expected_outcome="needs_information",
        expected_result_type="none",
        expected_missing_facts=["market_placement", "packaged_goods_category"],
        expected_ui="missing_facts",
    ),
]


E2E_TRAJECTORIES = [*ASSESSMENT_COMPLETE_CASES, *ASSESSMENT_MISSING_CASES, *EXEMPTION_CASES, *INSUFFICIENT_EVIDENCE_CASES, *CHECKLIST_CASES]
assert len(E2E_TRAJECTORIES) == 40


QUERY_UNDERSTANDING_CASES = [
    *[_case(f"chat_{i:02}", query, "chitchat") for i, query in enumerate(("Xin chào", "Cảm ơn bạn", "Bạn là ai?", "Tạm biệt", "Chào buổi sáng", "Hello", "Cảm ơn nhé", "Bạn khỏe không?"), 1)],
    *[_case(f"lookup_{i:02}", query, "legal_lookup") for i, query in enumerate(("Điều 77 quy định gì?", "Đối tượng nào phải tái chế EPR?", "Bao bì thương phẩm EPR là gì?", "Khi nào bắt đầu nghĩa vụ EPR?", "Tỷ lệ tái chế EPR là bao nhiêu?", "Nhà nhập khẩu EPR có trách nhiệm gì?", "Điều kiện cơ sở tái chế EPR?", "Báo cáo EPR cần gì?", "Công thức đóng góp tài chính EPR?", "Phụ lục XXII EPR nói gì?"), 1)],
    *[_case(f"compare_{i:02}", query, "legal_explain_compare") for i, query in enumerate(("So sánh Điều 77 và Điều 78 về EPR", "Giải thích Điều 79 về EPR", "Phân biệt hai hình thức thực hiện EPR", "Điều 80 khác gì Điều 81 thế nào?", "Tóm tắt Điều 82 về EPR", "So sánh tỷ lệ tái chế EPR", "Giải thích quy cách tái chế EPR", "So sánh trách nhiệm nhà sản xuất và nhập khẩu EPR"), 1)],
    *[_case(f"assessment_{i:02}", query, "case_assessment") for i, query in enumerate(("Tôi là nhà sản xuất, có phải EPR không?", "Đánh giá nghĩa vụ EPR cho công ty tôi", "Nhà nhập khẩu bao bì của công ty tôi có phải tuân thủ EPR không?", "Trường hợp EPR của tôi cần đánh giá", "Tôi bán pin tại Việt Nam, có nghĩa vụ EPR gì?", "Doanh nghiệp tôi có thuộc EPR không?", "Kiểm tra nghĩa vụ EPR cho tôi với vai trò nhà sản xuất", "Tôi cần biết trường hợp EPR của mình có phải tái chế không?"), 1)],
    *[_case(f"checklist_{i:02}", query, "compliance_checklist") for i, query in enumerate(("Lập checklist EPR", "Các bước cần làm để tuân thủ EPR", "Tạo danh sách hồ sơ EPR", "Lập lộ trình tuân thủ trách nhiệm tái chế EPR", "Checklist EPR cho nhà nhập khẩu", "Tôi cần chuẩn bị những gì để tuân thủ EPR?"), 1)],
    *[_case(f"research_{i:02}", query, "research_web", mode="research_web") for i, query in enumerate(("Tìm nguồn công khai về EPR", "Tìm trên web văn bản chính thức", "Tìm nguồn mới về tái chế", "Tra cứu internet về Nghị định 08"), 1)],
    *[_case(f"followup_{i:02}", query, "legal_lookup", is_follow_up=True) for i, query in enumerate(("Còn trường hợp đó thì sao?", "Điều đó áp dụng với bao bì nhựa không?", "Vậy thời điểm áp dụng?", "Còn Điều 78?"), 1)],
    *[_case(f"scope_{i:02}", query, "out_of_scope") for i, query in enumerate(("Luật đất đai quy định gì?", "Hợp đồng lao động thế nào?", "Thuế doanh nghiệp tính ra sao?", "Quy định chứng khoán là gì?"), 1)],
    *[_case(f"ambiguous_{i:02}", query, "out_of_scope", expected_behavior="clarify_or_safe_stop") for i, query in enumerate(("Nghĩa vụ này là gì?", "Có phải làm không?", "Quy định đó áp dụng thế nào?", "Tôi cần biết thêm."), 1)],
    *[_case(f"hinted_{i:02}", query, route, intent_hint=route) for i, (query, route) in enumerate((("Tìm Điều 77", "legal_lookup"), ("Giải thích Điều 78", "legal_explain_compare"), ("Kiểm tra nghĩa vụ EPR của tôi", "case_assessment"), ("Lập checklist EPR cho tôi", "compliance_checklist")), 1)],
]
assert len(QUERY_UNDERSTANDING_CASES) == 60


RETRIEVAL_CASES = [
    *[_case(f"explicit_{article}", f"Điều {article} quy định gì?", "legal_lookup", category="explicit", expected_articles=[f"Điều {article}"]) for article in range(77, 93)],
    *[_case(f"multi_{left}_{right}", f"So sánh Điều {left} và Điều {right}", "legal_explain_compare", category="multi_anchor", expected_articles=[f"Điều {left}", f"Điều {right}"]) for left, right in ((77, 78), (78, 79), (79, 80), (80, 81), (81, 82), (82, 83), (83, 84), (84, 85), (85, 86), (86, 87))],
    *[_case(f"semantic_{i:02}", query, "legal_lookup", category="semantic") for i, query in enumerate(("đối tượng và lộ trình trách nhiệm tái chế EPR", "quy cách tái chế EPR bắt buộc", "hình thức thực hiện trách nhiệm tái chế EPR", "đăng ký kế hoạch tái chế EPR", "hỗ trợ hoạt động tái chế EPR", "kê khai đóng góp tài chính EPR", "trách nhiệm EPR của nhà nhập khẩu", "sản phẩm điện tử thuộc diện tái chế EPR", "bao bì có bắt buộc tái chế EPR", "cơ sở tái chế EPR được công nhận", "quy định EPR về dầu nhớt", "quy định EPR về săm lốp", "quy định EPR về ắc quy", "tỷ lệ tái chế EPR của pin", "thời điểm báo cáo EPR", "điều kiện thực hiện tái chế EPR", "hệ thống thông tin EPR", "mức đóng góp tài chính EPR", "tổ chức thực hiện tái chế EPR", "kiểm tra kế hoạch tái chế EPR"), 1)],
    *[_case(f"lexical_{i:02}", query, "legal_lookup", category="lexical") for i, query in enumerate(("công thức EPR F = R x V x Fs", "tỷ lệ tái chế EPR R 2025", "Phụ lục XXII EPR", "mã HS bao bì EPR", "Khoản 3 Điều 77 EPR", "Điểm a Khoản 2 EPR", "01/01/2024 EPR", "Nghị định 08/2022/NĐ-CP EPR"), 1)],
    *[_case(f"no_evidence_{i:02}", query, "legal_lookup", category="no_evidence", expected_termination="insufficient_evidence") for i, query in enumerate(("EPR cho ngành hàng không có quy định nào?", "Tiêu chuẩn quốc tế EPR ngoài Nghị định 08 là gì?", "EPR tại Thái Lan quy định ra sao?", "Một quy định EPR chưa có trong văn bản hiện tại là gì?", "Luật EPR của châu Âu nói gì?", "EPR cho vật liệu chưa được đề cập trong corpus là gì?"), 1)],
]
assert len(RETRIEVAL_CASES) == 60


MANIFEST = {
    "version": "pipeline-v4-test-matrix-v1",
    "embedding_profile": "openai-text-embedding-3-small-v1",
    "query_understanding": QUERY_UNDERSTANDING_CASES,
    "retrieval": RETRIEVAL_CASES,
    "e2e": E2E_TRAJECTORIES,
}
