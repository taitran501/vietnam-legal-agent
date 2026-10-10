"""Balanced 60-case retrieval suite spanning ordinary Vietnamese legal topics."""

from __future__ import annotations


def _case(case_id: str, query: str, route: str, **extra: object) -> dict[str, object]:
    return {"id": case_id, "query": query, "expected_route": route, **extra}


_EXPLICIT_ANCHORS = (
    ("labor_36", "Điều 36", "Điều 36 Bộ luật Lao động quy định gì?"),
    ("labor_41", "Điều 41", "Điều 41 Bộ luật Lao động quy định gì?"),
    ("labor_94", "Điều 94", "Điều 94 Bộ luật Lao động quy định gì?"),
    ("labor_97", "Điều 97", "Điều 97 Bộ luật Lao động quy định gì?"),
    ("civil_328", "Điều 328", "Điều 328 Bộ luật Dân sự quy định gì?"),
    ("civil_357", "Điều 357", "Điều 357 Bộ luật Dân sự quy định gì?"),
    ("family_81", "Điều 81", "Điều 81 Luật Hôn nhân và Gia đình quy định gì?"),
    ("company_111", "Điều 111", "Điều 111 Luật Doanh nghiệp quy định gì?"),
    ("company_115", "Điều 115", "Điều 115 Luật Doanh nghiệp quy định gì?"),
    ("land_93", "Điều 93", "Điều 93 Luật Đất đai quy định gì?"),
    ("environment_54", "Điều 54", "Điều 54 Luật Bảo vệ môi trường quy định gì?"),
    ("traffic_6", "Điều 6", "Điều 6 Nghị định xử phạt giao thông quy định gì?"),
)

_COMPARISONS = (
    ("labor_36_41", 36, 41),
    ("labor_94_97", 94, 97),
    ("civil_328_357", 328, 357),
    ("family_81_82", 81, 82),
    ("company_111_115", 111, 115),
    ("land_93_96", 93, 96),
    ("environment_54_55", 54, 55),
    ("traffic_6_7", 6, 7),
)

_SEMANTIC_QUERIES = (
    "Người sử dụng lao động chậm trả lương thì người lao động có quyền gì?",
    "Làm thêm giờ vào ngày nghỉ được trả lương thế nào?",
    "Khi nghỉ việc, công ty phải thanh toán quyền lợi trong thời hạn nào?",
    "Chủ nhà không trả tiền cọc sau khi trả nhà thì giải quyết thế nào?",
    "Bên vay trả nợ trễ hạn có phải trả lãi không?",
    "Bên bán giao hàng không đúng thỏa thuận thì người mua có quyền gì?",
    "Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?",
    "Cổ đông thiểu số có quyền yêu cầu triệu tập cuộc họp không?",
    "Thành lập công ty cần chuẩn bị hồ sơ nào?",
    "Sau khi ly hôn, tòa án quyết định quyền nuôi con dựa trên điều gì?",
    "Tài sản chung của vợ chồng được phân chia theo nguyên tắc nào?",
    "Cha mẹ có nghĩa vụ cấp dưỡng cho con trong trường hợp nào?",
    "Nhà nước thu hồi đất ở thì người dân được bồi thường ra sao?",
    "Điều kiện cấp giấy chứng nhận quyền sử dụng đất là gì?",
    "Thủ tục đăng ký biến động đất đai được thực hiện thế nào?",
    "Người ngồi sau xe máy có bắt buộc đội mũ bảo hiểm không?",
    "Vượt đèn đỏ bằng xe máy bị xử phạt thế nào?",
    "Điều khiển xe khi có nồng độ cồn bị phạt ra sao?",
    "Khi nào cá nhân phải quyết toán thuế thu nhập?",
    "Người phụ thuộc được giảm trừ gia cảnh như thế nào?",
    "Cá nhân có thu nhập từ nhiều nơi hoàn thuế ra sao?",
    "Điều kiện đăng ký nhãn hiệu hàng hóa là gì?",
    "Sử dụng tác phẩm có bản quyền khi nào cần xin phép?",
    "Chủ sở hữu sáng chế được bảo hộ trong thời hạn bao lâu?",
    "Người mua có quyền đổi trả hàng hóa có lỗi thế nào?",
    "Khiếu nại quyết định xử phạt hành chính trong thời hạn nào?",
    "Cơ quan nào giải quyết khiếu nại lần đầu?",
    "Điều kiện xin giấy phép xây dựng nhà ở riêng lẻ là gì?",
    "Cơ sở kinh doanh ăn uống cần tuân thủ điều kiện an toàn thực phẩm nào?",
    "Quy định bảo vệ tài nguyên và môi trường biển áp dụng cho những hoạt động nào?",
)

_OUT_OF_CORPUS_QUERIES = (
    "Luật lao động của Thái Lan quy định thời gian thử việc tối đa bao lâu?",
    "Mức thuế thu nhập cá nhân hiện hành ở Singapore là bao nhiêu?",
    "Tòa án Hoa Kỳ xử lý tranh chấp thuê nhà thế nào?",
    "Quy định mới nhất của Liên minh châu Âu về trí tuệ nhân tạo là gì?",
    "Một thủ tục chuyên ngành không được nêu trong các nguồn hiện có là gì?",
    "Văn bản địa phương chưa có trong kho quy định mức phí nào?",
    "Luật của Nhật Bản quy định quyền nuôi con sau ly hôn ra sao?",
    "Tiêu chuẩn quốc tế mới nhất cho sản phẩm này là gì?",
    "Một điều khoản không xuất hiện trong nguồn đã truy xuất quy định gì?",
    "Quy định chi tiết của tỉnh chưa có trong nguồn hiện tại là gì?",
)

RETRIEVAL_CASES = [
    *[
        _case(f"explicit_{case_id}", query, "legal_lookup", category="explicit", expected_articles=[anchor])
        for case_id, anchor, query in _EXPLICIT_ANCHORS
    ],
    *[
        _case(
            f"compare_{case_id}",
            f"So sánh Điều {left} và Điều {right} trong văn bản pháp luật tương ứng.",
            "legal_explain_compare",
            category="compare",
            expected_articles=[f"Điều {left}", f"Điều {right}"],
        )
        for case_id, left, right in _COMPARISONS
    ],
    *[
        _case(f"semantic_{index:02}", query, "legal_lookup", category="semantic")
        for index, query in enumerate(_SEMANTIC_QUERIES, 1)
    ],
    *[
        _case(
            f"no_evidence_{index:02}",
            query,
            "legal_lookup",
            category="no_evidence",
            expected_termination="insufficient_evidence",
        )
        for index, query in enumerate(_OUT_OF_CORPUS_QUERIES, 1)
    ],
]

assert len(RETRIEVAL_CASES) == 60
