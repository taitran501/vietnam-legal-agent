"""Balanced, behavior-first fixtures for the general legal assistant."""

from __future__ import annotations

from typing import Any


def _case(case_id: str, query: str, route: str, **extra: Any) -> dict[str, Any]:
    return {"id": case_id, "query": query, "expected_route": route, **extra}


QUERY_UNDERSTANDING_CASES = [
    *[_case(f"chat_{i:02}", query, "chitchat") for i, query in enumerate((
        "Xin chào", "Cảm ơn bạn", "Bạn là ai?", "Tạm biệt", "Chào buổi sáng", "Hello",
    ), 1)],
    *[_case(f"labor_{i:02}", query, "case_assessment") for i, query in enumerate((
        "Tôi bị công ty chậm trả lương, tôi có quyền gì?",
        "Công ty cho tôi nghỉ việc đột ngột có đúng luật không?",
        "Tôi làm thêm giờ nhưng không được trả lương, cần làm gì?",
    ), 1)],
    *[_case(f"civil_{i:02}", query, "case_assessment") for i, query in enumerate((
        "Chủ nhà giữ tiền cọc sau khi tôi trả nhà, tôi nên làm gì?",
        "Bên vay không trả tiền đúng hạn, tôi có thể đòi lãi không?",
        "Bên bán giao hàng sai hợp đồng thì xử lý thế nào?",
    ), 1)],
    *[_case(f"lookup_{i:02}", query, "legal_lookup") for i, query in enumerate((
        "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?",
        "Người ngồi sau xe máy không đội mũ bảo hiểm bị phạt bao nhiêu?",
        "Điều kiện đăng ký nhãn hiệu là gì?",
        "Điều 1 Luật số 82/2015/QH13 điều chỉnh những vấn đề nào về tài nguyên và môi trường biển?",
        "Khi nào phải quyết toán thuế thu nhập cá nhân?",
        "Điều 328 Bộ luật Dân sự quy định gì?",
    ), 1)],
    *[_case(f"checklist_{i:02}", query, "compliance_checklist", intent_hint="compliance_checklist") for i, query in enumerate((
        "Lập checklist giấy tờ cần bàn giao khi nghỉ việc.",
        "Tạo checklist thành lập công ty cổ phần.",
        "Lập danh sách giấy tờ cần chuẩn bị khi đăng ký nhãn hiệu.",
    ), 1)],
    *[_case(f"compare_{i:02}", query, "legal_explain_compare") for i, query in enumerate((
        "So sánh hợp đồng lao động xác định thời hạn và không xác định thời hạn.",
        "Phân biệt đặt cọc và trả trước theo Bộ luật Dân sự.",
        "So sánh quyền sở hữu chung và riêng của vợ chồng.",
    ), 1)],
    *[_case(f"research_{i:02}", query, "research_web", mode="research_web") for i, query in enumerate((
        "Tìm văn bản chính thức mới về thuế thu nhập cá nhân.",
        "Tra cứu nguồn công khai của Chính phủ về luật giao thông.",
    ), 1)],
    *[_case(f"scope_{i:02}", query, "out_of_scope") for i, query in enumerate((
        "Hướng dẫn cách nấu phở bò?", "Dự đoán kết quả bóng đá hôm nay?",
    ), 1)],
]


E2E_TRAJECTORIES = [
    _case("labor_lookup", "Người sử dụng lao động phải trả lương khi nào?", "legal_lookup", expected_outcome="completed"),
    _case("civil_lookup", "Tiền đặt cọc thuê nhà được xử lý thế nào?", "legal_lookup", expected_outcome="completed"),
    _case("corporate_lookup", "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?", "legal_lookup", expected_outcome="completed"),
    _case("traffic_lookup", "Người ngồi sau xe máy phải đội mũ bảo hiểm không?", "legal_lookup", expected_outcome="completed"),
    _case("family_lookup", "Tòa án xem xét điều gì khi quyết định người trực tiếp nuôi con?", "legal_lookup", expected_outcome="completed"),
    _case("environmental_lookup", "Điều 1 Luật số 82/2015/QH13 quy định những vấn đề nào về tài nguyên và môi trường biển?", "legal_lookup", expected_outcome="completed"),
    # V4 answers assessment/checklist requests in the ordinary legal chat path;
    # the requested output format is carried in the prompt, not a special UI route.
    _case("labor_checklist", "Lập checklist giấy tờ cần bàn giao khi nghỉ việc.", "legal_lookup", expected_outcome="completed", expected_result_type="legal_answer"),
    _case("corporate_checklist", "Lập checklist hồ sơ đăng ký công ty cổ phần.", "legal_lookup", expected_outcome="completed", expected_result_type="legal_answer"),
    _case("no_evidence", "Quy định hiện hành cho tình huống pháp lý rất cụ thể này là gì?", "legal_lookup", expected_outcome="insufficient_evidence", expected_result_type="none", expected_ui="safe_stop"),
    _case("out_of_scope", "Hướng dẫn cách nấu bún chả truyền thống.", "out_of_scope", expected_outcome="out_of_scope", expected_result_type="none", expected_ui="safe_stop"),
]


RETRIEVAL_CASES = [
    *[_case(f"explicit_{article}", f"Điều {article} quy định gì?", "legal_lookup", category="explicit", expected_articles=[f"Điều {article}"]) for article in (30, 48, 77, 81, 94, 111, 328)],
    *[_case(f"semantic_{i:02}", query, "legal_lookup", category="semantic") for i, query in enumerate((
        "quyền của người lao động khi bị chậm trả lương",
        "hoàn trả tiền đặt cọc thuê nhà",
        "số lượng cổ đông tối thiểu trong công ty cổ phần",
        "mức phạt người ngồi sau xe máy không đội mũ bảo hiểm",
        "quyền nuôi con sau khi ly hôn",
        "điều kiện đăng ký nhãn hiệu sản phẩm",
        "trách nhiệm môi trường của doanh nghiệp",
        "quyết toán thuế thu nhập cá nhân",
        "bồi thường khi vi phạm hợp đồng mua bán",
        "thủ tục khiếu nại quyết định hành chính",
    ), 1)],
    _case("no_evidence_foreign_law", "Luật lao động của Thái Lan quy định gì?", "legal_lookup", category="no_evidence", expected_termination="insufficient_evidence"),
    _case("no_evidence_uncovered", "Một quy định chưa được đề cập trong nguồn hiện có là gì?", "legal_lookup", category="no_evidence", expected_termination="insufficient_evidence"),
]


MANIFEST = {
    "version": "general-legal-agent-test-matrix-v2",
    "embedding_profile": "openai-text-embedding-3-small-v1",
    "query_understanding": QUERY_UNDERSTANDING_CASES,
    "retrieval": RETRIEVAL_CASES,
    "e2e": E2E_TRAJECTORIES,
}
