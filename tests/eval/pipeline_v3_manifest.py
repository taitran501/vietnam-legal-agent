"""Deterministic V3 evaluation contracts.

These manifests intentionally separate query understanding, retrieval, and
end-to-end workflow checks.  A local real-stack evaluator can consume exactly
the same cases without making the unit suite call OpenAI or Tavily.
"""

from __future__ import annotations

from epr_agent.evaluation.retrieval_cases import RETRIEVAL_CASES


def _case(case_id: str, query: str, route: str, **extra: object) -> dict[str, object]:
    return {"id": case_id, "query": query, "expected_route": route, **extra}


QUERY_UNDERSTANDING_CASES = [
    *[_case(f"chat_{index:02}", query, "chitchat") for index, query in enumerate([
        "Xin chào", "Cảm ơn bạn", "Bạn là ai?", "Tạm biệt", "Hôm nay thế nào?", "Chào buổi sáng", "Hello", "Cảm ơn nhé",
    ], 1)],
    *[_case(f"lookup_{index:02}", query, "legal_lookup") for index, query in enumerate([
        "Đối tượng nào phải thực hiện trách nhiệm tái chế?", "Bao bì thương phẩm được hiểu thế nào?",
        "Khi nào bắt đầu thực hiện trách nhiệm tái chế?", "Dầu nhớt có thuộc danh mục tái chế không?",
        "Nhà sản xuất có hình thức thực hiện nghĩa vụ nào?", "Tỷ lệ tái chế bao bì được quy định ra sao?",
        "Báo cáo kết quả tái chế phải làm gì?", "Điện thoại có thuộc đối tượng tái chế không?",
        "Cách tính đóng góp tài chính EPR?", "Cơ sở tái chế cần điều kiện gì?",
    ], 1)],
    *[_case(f"explain_{index:02}", query, "legal_explain_compare") for index, query in enumerate([
        "Giải thích Điều 77", "So sánh Điều 77 và Điều 78", "Phân biệt hai hình thức thực hiện trách nhiệm tái chế",
        "Tóm tắt Điều 79", "Điều 80 khác gì Điều 81", "Giải thích quy cách tái chế", "So sánh tỷ lệ tái chế giữa hai nhóm", "Tóm tắt điều khoản EPR về đóng góp tài chính",
    ], 1)],
    *[_case(f"assessment_{index:02}", query, "case_assessment") for index, query in enumerate([
        "Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?", "Công ty tôi nhập khẩu chai thủy tinh tại Việt Nam, cần đánh giá nghĩa vụ EPR.",
        "Tôi là nhà sản xuất pin kim loại, bán tại Việt Nam, có nghĩa vụ gì?", "Doanh nghiệp tôi là nhà sản xuất, có phải thực hiện EPR không?",
        "Công ty nhập khẩu bao bì có cần tuân thủ không?", "Trường hợp của tôi là bao bì nhựa, hãy đánh giá.",
        "Tôi sản xuất dầu nhớt, hoạt động nội địa, có thuộc EPR không?", "Doanh nghiệp bán lẻ có phải thực hiện EPR không?",
        "Công ty tôi xuất khẩu toàn bộ sản phẩm, có nghĩa vụ EPR không?", "Tôi là nhà nhập khẩu pin, cần đánh giá sơ bộ.",
        "Công ty sản xuất lốp cao su EPR tại Việt Nam có phải thực hiện không?", "Đánh giá nghĩa vụ EPR cho doanh nghiệp tôi.",
    ], 1)],
    *[_case(f"checklist_{index:02}", query, "compliance_checklist") for index, query in enumerate([
        "Lập checklist EPR cho nhà sản xuất bao bì nhựa tại Việt Nam.", "Các bước cần làm EPR cho nhà nhập khẩu chai nhựa.",
        "Tạo danh sách hồ sơ EPR cho công ty tôi.", "Lập checklist tuân thủ EPR cho pin kim loại.",
        "Tôi cần chuẩn bị những bước gì để tuân thủ EPR?", "Lập lộ trình tuân thủ EPR cho bao bì giấy.",
        "Checklist nghĩa vụ EPR cho dầu nhớt.", "Các việc cần làm trước khi kê khai EPR?",
    ], 1)],
    *[_case(f"research_{index:02}", query, "research_web", mode="research_web") for index, query in enumerate([
        "Tìm nguồn công khai về EPR", "Tìm trên web hướng dẫn mới về tái chế", "Tra cứu internet về Nghị định 08",
        "Tìm web văn bản chính thức về trách nhiệm tái chế", "Tôi muốn xem nguồn công khai", "Tìm nguồn mới trên web",
    ], 1)],
    *[_case(f"followup_{index:02}", query, "legal_lookup", is_follow_up=True) for index, query in enumerate([
        "Còn trường hợp đó thì sao?", "Điều đó áp dụng với bao bì nhựa không?", "Còn Điều 78?", "Vậy thời điểm áp dụng?",
    ], 1)],
    *[_case(f"scope_{index:02}", query, "out_of_scope") for index, query in enumerate([
        "Quy định về chứng khoán là gì?", "Luật lao động quy định gì về hợp đồng?", "Thuế thu nhập doanh nghiệp tính thế nào?", "Luật đất đai quy định gì?",
    ], 1)],
]

E2E_TRAJECTORIES = [
    *[_case(f"lookup_{index:02}", query, "legal_lookup") for index, query in enumerate([
        "Điều 77 quy định gì?", "Đối tượng nào phải tái chế?", "Bao bì thương phẩm là gì?", "Dầu nhớt có thuộc diện tái chế không?", "Tỷ lệ tái chế tính thế nào?", "Khi nào phải nộp báo cáo EPR?", "Nghĩa vụ của nhà sản xuất là gì?", "Điều 78 nói gì?",
    ], 1)],
    *[_case(f"compare_{index:02}", query, "legal_explain_compare") for index, query in enumerate([
        "So sánh Điều 77 và Điều 78", "Giải thích Điều 79", "Tóm tắt Điều 80", "Điều 81 khác gì Điều 82", "So sánh Điều 83 và Điều 84", "Giải thích Điều 85",
    ], 1)],
    *[_case(f"missing_case_{index:02}", query, "case_assessment", expected_termination="awaiting_user_input") for index, query in enumerate([
        "Tôi là nhà sản xuất, có phải thực hiện EPR không?", "Công ty tôi nhập khẩu bao bì, có nghĩa vụ gì.", "Đánh giá EPR cho công ty tôi.",
    ], 1)],
    _case("missing_case_04", "Tôi cần checklist EPR.", "compliance_checklist", expected_termination="awaiting_user_input"),
    *[_case(f"complete_case_{index:02}", query, route) for index, (query, route) in enumerate([
        ("Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?", "case_assessment"),
        ("Công ty tôi là nhà nhập khẩu chai thủy tinh tại Việt Nam, cần đánh giá EPR.", "case_assessment"),
        ("Lập checklist EPR cho nhà sản xuất bao bì nhựa tại Việt Nam.", "compliance_checklist"),
        ("Các bước cần làm EPR cho nhà nhập khẩu chai thủy tinh tại Việt Nam.", "compliance_checklist"),
    ], 1)],
    _case(
        "resume_01",
        "Vật liệu là nhựa.",
        "case_assessment",
        is_follow_up=True,
        prelude=["Tôi là nhà sản xuất bao bì tại Việt Nam, có phải thực hiện EPR không?"],
    ),
    _case(
        "resume_02",
        "Phạm vi là thị trường Việt Nam.",
        "case_assessment",
        is_follow_up=True,
        prelude=["Tôi là nhà sản xuất bao bì nhựa, có phải thực hiện EPR không?"],
    ),
    _case(
        "resume_03",
        "Sản phẩm là bao bì.",
        "case_assessment",
        is_follow_up=True,
        prelude=["Tôi là nhà sản xuất nhựa tại Việt Nam, có phải thực hiện EPR không?"],
    ),
    _case(
        "resume_04",
        "Vai trò là nhà nhập khẩu.",
        "case_assessment",
        is_follow_up=True,
        prelude=["Đánh giá EPR cho doanh nghiệp có bao bì nhựa đưa vào thị trường Việt Nam."],
    ),
    *[_case(f"research_{index:02}", query, "research_web", mode="research_web") for index, query in enumerate([
        "Tìm nguồn công khai về EPR", "Tìm trên web văn bản EPR", "Tìm web hướng dẫn tái chế", "Nguồn công khai nào nói về EPR?",
    ], 1)],
    _case("safe_01", "EPR tại quốc gia khác quy định thế nào?", "legal_lookup", expected_termination="insufficient_evidence"),
    _case("safe_02", "Nội dung EPR chưa có trong corpus?", "legal_lookup", expected_termination="insufficient_evidence"),
    _case("safe_03", "Điều 999 quy định gì?", "legal_lookup", expected_termination="insufficient_evidence"),
    _case("safe_04", "Quy định chứng khoán là gì?", "out_of_scope", expected_termination="out_of_scope"),
    _case("safe_05", "Quy định EPR của EU là gì?", "legal_lookup", expected_termination="insufficient_evidence"),
    _case("safe_06", "Văn bản không có nguồn thì sao?", "out_of_scope", expected_termination="out_of_scope"),
    *[_case(f"repair_{index:02}", query, "legal_lookup", requires_repair=True) for index, query in enumerate([
        "Điều 77 có nói gì về trách nhiệm tái chế?", "Tỷ lệ tái chế bao bì là bao nhiêu?", "Nghĩa vụ nhà nhập khẩu pin?", "Dầu nhớt có thuộc danh mục tái chế không?",
    ], 1)],
]

assert len(QUERY_UNDERSTANDING_CASES) == 60
assert len(RETRIEVAL_CASES) == 60
assert len(E2E_TRAJECTORIES) == 40
