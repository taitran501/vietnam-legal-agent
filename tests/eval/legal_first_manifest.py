"""Deterministic 50-case contract for the legal-first bounded workflow."""

from __future__ import annotations


def _case(category: str, index: int, query: str, **extra: object) -> dict[str, object]:
    case = {
        "id": f"{category}_{index:02d}", "category": category, "query": query,
        "expected_task_type": "legal_lookup", "required_actions": ["retrieve_legal"],
        "forbidden_actions": ["retrieve_faq"], "termination": "answer_complete", "source_type": "legal",
        "expected_articles": [], "required_keywords": [], "cache_policy": "legal_only",
    }
    case.update(extra)
    return case


LEGAL_FIRST_CASES = [
    *[_case("chitchat", i, query, expected_task_type="chitchat", required_actions=[], termination="answer_complete", source_type="chitchat", cache_policy="never") for i, query in enumerate([
        "Xin chào", "Cảm ơn bạn", "Bạn là ai?", "Tạm biệt", "Hôm nay thế nào?", "Kể chuyện vui đi", "Bạn có thể làm gì?", "Chúc một ngày tốt lành",
    ], 1)],
    *[_case("common", i, query, required_keywords=keywords) for i, (query, keywords) in enumerate([
        ("Các đối tượng nào phải thực hiện trách nhiệm tái chế?", ["tái chế"]),
        ("Bao bì thương phẩm được hiểu thế nào?", ["bao bì"]),
        ("Khi nào bắt đầu thực hiện trách nhiệm tái chế?", ["thực hiện"]),
        ("Dầu nhớt có thuộc danh mục tái chế không?", ["dầu nhớt"]),
        ("Nhà sản xuất chọn hình thức thực hiện nghĩa vụ nào?", ["nghĩa vụ"]),
        ("Tỷ lệ tái chế bao bì được quy định ra sao?", ["tái chế"]),
        ("Báo cáo kết quả tái chế phải làm gì?", ["báo cáo"]),
        ("Điện thoại có thuộc đối tượng tái chế không?", ["tái chế"]),
        ("Cách tính đóng góp tài chính EPR?", ["tài chính"]),
        ("Cơ sở tái chế cần điều kiện gì?", ["điều kiện"]),
    ], 1)],
    *[_case("explicit", i, f"Điều {article} quy định gì về EPR?", expected_articles=[f"Điều {article}"], required_keywords=[f"Điều {article}"]) for i, article in enumerate([77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 77], 1)],
    *[_case("semantic", i, query) for i, query in enumerate([
        "đối tượng và lộ trình thực hiện trách nhiệm tái chế", "quy cách tái chế bắt buộc", "hình thức thực hiện trách nhiệm tái chế", "đăng ký kế hoạch tái chế", "công thức F bằng R nhân V nhân Fs", "hỗ trợ hoạt động tái chế", "kê khai đóng góp tài chính", "hệ thống thông tin EPR quốc gia",
    ], 1)],
    *[_case("fallback", i, query, termination="insufficient_evidence", source_type="error", cache_policy="never") for i, query in enumerate([
        "EPR cho ngành hàng không có quy định nào trong corpus này?", "Tiêu chuẩn quốc tế EPR mới nhất ngoài Nghị định 08 là gì?", "EPR tại Thái Lan quy định ra sao?", "Một quy định EPR chưa có trong văn bản hiện tại là gì?",
    ], 1)],
    _case("followup", 1, "Còn trường hợp đó thì sao?", required_actions=["retrieve_legal"], cache_policy="never"),
    _case("followup", 2, "Điều đó áp dụng với bao bì nhựa không?", required_actions=["retrieve_legal"], cache_policy="never"),
    _case("followup", 3, "Tóm tắt lại Điều 77", expected_articles=["Điều 77"], cache_policy="never"),
    _case("followup", 4, "Còn Điều 78?", expected_articles=["Điều 78"], cache_policy="never"),
    _case("assessment", 1, "Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?", expected_task_type="assess_epr_obligation", cache_policy="never"),
    _case("assessment", 2, "Tôi là nhà sản xuất, có phải thực hiện EPR không?", expected_task_type="assess_epr_obligation", required_actions=["ask_user"], termination="awaiting_user_input", source_type="follow_up", cache_policy="never"),
    _case("checklist", 1, "Lập checklist EPR cho nhà sản xuất bao bì nhựa tại Việt Nam.", expected_task_type="build_compliance_checklist", cache_policy="never"),
    _case("checklist", 2, "Lập checklist EPR cho tôi.", expected_task_type="build_compliance_checklist", required_actions=["ask_user"], termination="awaiting_user_input", source_type="follow_up", cache_policy="never"),
]

assert len(LEGAL_FIRST_CASES) == 50
