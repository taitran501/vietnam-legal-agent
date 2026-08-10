"""Canonical 60-case retrieval suite for Pipeline V3 local evaluation."""

from __future__ import annotations


def _case(case_id: str, query: str, route: str, **extra: object) -> dict[str, object]:
    return {"id": case_id, "query": query, "expected_route": route, **extra}


RETRIEVAL_CASES = [
    *[
        _case(f"explicit_{article}", f"Điều {article} quy định gì?", "legal_lookup", expected_articles=[f"Điều {article}"])
        for article in (77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92)
    ],
    *[
        _case(f"multi_{left}_{right}", f"So sánh Điều {left} và Điều {right}", "legal_explain_compare", expected_articles=[f"Điều {left}", f"Điều {right}"])
        for left, right in ((77, 78), (78, 79), (79, 80), (80, 81), (81, 82), (82, 83), (83, 84), (84, 85), (85, 86), (86, 87))
    ],
    *[_case(f"semantic_{index:02}", query, "legal_lookup") for index, query in enumerate([
        "đối tượng và lộ trình thực hiện trách nhiệm tái chế", "quy cách tái chế bắt buộc", "hình thức thực hiện trách nhiệm tái chế", "đăng ký kế hoạch tái chế",
        "hỗ trợ hoạt động tái chế", "kê khai đóng góp tài chính", "hệ thống thông tin EPR quốc gia", "trách nhiệm của nhà nhập khẩu",
        "sản phẩm điện tử thuộc diện tái chế", "bao bì có bắt buộc tái chế", "thời điểm đăng ký kế hoạch tái chế", "nộp báo cáo kết quả tái chế",
        "tỷ lệ tái chế pin", "đóng góp vào quỹ bảo vệ môi trường", "tổ chức thực hiện tái chế", "cơ sở tái chế được công nhận",
        "kiểm tra kế hoạch tái chế", "quy định về dầu nhớt", "quy định về săm lốp", "quy định về ắc quy",
    ], 1)],
    *[_case(f"lexical_{index:02}", query, "legal_lookup") for index, query in enumerate([
        "công thức F = R x V x Fs", "tỷ lệ tái chế R 2025", "Phụ lục XXII", "mã HS bao bì", "khoản 3 điều 77", "điểm a khoản 2", "mức đóng góp tài chính", "01/01/2024",
    ], 1)],
    *[_case(f"no_evidence_{index:02}", query, "legal_lookup", expected_termination="insufficient_evidence") for index, query in enumerate([
        "EPR cho ngành hàng không có quy định nào trong corpus này?", "Tiêu chuẩn quốc tế EPR mới nhất ngoài Nghị định 08 là gì?", "EPR tại Thái Lan quy định ra sao?",
        "Một quy định EPR chưa có trong văn bản hiện tại là gì?", "Luật EPR của châu Âu nói gì?", "Quy định EPR cho vật liệu chưa được đề cập?",
    ], 1)],
]

assert len(RETRIEVAL_CASES) == 60
