"""Evaluation Manifest and Test Cases for Autonomous Agent Trajectory Harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTestCase:
    """Specification of one agent benchmark test case."""

    id: str
    category: str
    query: str
    expected_termination: str
    expected_tools: list[str] = field(default_factory=list)
    max_steps_allowed: int = 5
    expected_answer_contains: list[str] = field(default_factory=list)
    mock_facts: dict[str, str] = field(default_factory=dict)
    active_case: dict[str, Any] | None = None
    mock_first_search_empty: bool = False
    mock_all_search_empty: bool = False
    description: str = ""


AGENT_MANIFEST: list[AgentTestCase] = [
    # ── 1. Single-hop Legal Retrieval ──────────────────────────────────────────
    AgentTestCase(
        id="AG-001",
        category="single_hop",
        query="Điều 77 Luật Bảo vệ môi trường 2020 quy định về trách nhiệm gì?",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=3,
        expected_answer_contains=["Điều 77", "tái chế"],
        description="Tra cứu trực tiếp một điều khoản cụ thể đã biết tên.",
    ),
    AgentTestCase(
        id="AG-002",
        category="single_hop",
        query="Ngưỡng doanh thu miễn trừ trách nhiệm tái chế bao bì là bao nhiêu?",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=3,
        expected_answer_contains=["30 tỷ", "doanh thu"],
        description="Tra cứu ngưỡng doanh thu miễn trừ tái chế bao bì.",
    ),
    AgentTestCase(
        id="AG-003",
        category="single_hop",
        query="Thời hạn nộp tiền đóng góp tài chính FSF vào Quỹ Bảo vệ môi trường là ngày nào?",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=3,
        expected_answer_contains=["20", "tháng 4"],
        description="Tra cứu thời hạn nộp tiền FSF.",
    ),

    # ── 2. Multi-hop Legal Reasoning ──────────────────────────────────────────
    AgentTestCase(
        id="AG-004",
        category="multi_hop",
        query="Công ty sản xuất bao bì nhựa PET tại Việt Nam cần thực hiện tỷ lệ tái chế bao nhiêu và căn cứ theo điều khoản nào?",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=4,
        expected_answer_contains=["PET", "tỷ lệ", "[1]"],
        description="Tra cứu kết hợp giữa Luật BVMT và Nghị định 08 Phụ lục XXII.",
    ),
    AgentTestCase(
        id="AG-005",
        category="multi_hop",
        query="So sánh trách nhiệm tái chế sản phẩm bao bì và trách nhiệm xử lý chất thải theo Luật BVMT 2020.",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=4,
        expected_answer_contains=["Điều 77", "Điều 78"],
        description="So sánh 2 điều khoản nghĩa vụ EPR khác nhau.",
    ),

    # ── 3. Case Assessment (Đầy đủ thông tin) ──────────────────────────────────
    AgentTestCase(
        id="AG-006",
        category="assessment_complete",
        query="Tôi là nhà sản xuất bao bì nhựa PET đưa ra thị trường Việt Nam, doanh thu 40 tỷ/năm cho mục đích thương mại, không tự thu hồi tái sử dụng. Tôi có thuộc diện phải thực hiện EPR không?",
        expected_termination="answer_complete",
        expected_tools=["get_case_form_fields", "evaluate_epr_obligation", "search_legal_provisions"],
        max_steps_allowed=4,
        expected_answer_contains=["EPR", "thuộc"],
        mock_facts={
            "business_role": "manufacturer",
            "object_kind": "commercial_packaging",
            "product_group": "bao_bi",
            "packaged_goods_category": "thuc_pham",
            "material": "pet",
            "market_placement": "vietnam_market",
            "activity_purpose": "commercial",
            "annual_revenue_vnd": "40000000000",
            "reused_by_producer": "no",
        },
        description="Đánh giá nghĩa vụ EPR khi người dùng đã cung cấp đủ tất cả facts.",
    ),
    AgentTestCase(
        id="AG-007",
        category="assessment_exempt",
        query="Công ty tôi sản xuất bao bì giấy bán trong nước nhưng doanh thu chỉ đạt 20 tỷ đồng mỗi năm. Có được miễn trừ EPR không?",
        expected_termination="answer_complete",
        expected_tools=["get_case_form_fields", "evaluate_epr_obligation", "search_legal_provisions"],
        max_steps_allowed=4,
        expected_answer_contains=["miễn trừ", "30 tỷ"],
        mock_facts={
            "business_role": "manufacturer",
            "object_kind": "commercial_packaging",
            "product_group": "bao_bi",
            "packaged_goods_category": "thuc_pham",
            "material": "paper",
            "market_placement": "vietnam_market",
            "activity_purpose": "commercial",
            "annual_revenue_vnd": "20000000000",
            "reused_by_producer": "no",
        },
        description="Đánh giá trường hợp được miễn trừ do doanh thu dưới 30 tỷ.",
    ),

    # ── 4. Case Assessment (Thiếu thông tin -> Cần hỏi lại) ────────────────────
    AgentTestCase(
        id="AG-008",
        category="assessment_missing_facts",
        query="Tôi là nhà sản xuất bao bì, tôi có phải thực hiện EPR không?",
        expected_termination="awaiting_user_input",
        expected_tools=["get_case_form_fields", "ask_user_for_clarification"],
        max_steps_allowed=2,
        expected_answer_contains=["thông tin"],
        mock_facts={"business_role": "manufacturer", "object_kind": "commercial_packaging"},
        description="Agent nhận diện thiếu facts và kích hoạt câu hỏi bổ sung.",
    ),
    AgentTestCase(
        id="AG-009",
        category="assessment_missing_facts",
        query="Tôi muốn đánh giá nghĩa vụ EPR cho doanh nghiệp của tôi.",
        expected_termination="awaiting_user_input",
        expected_tools=["get_case_form_fields", "ask_user_for_clarification"],
        max_steps_allowed=2,
        expected_answer_contains=["thông tin"],
        mock_facts={},
        description="Không có facts nào, agent phải hỏi các thông tin cốt lõi.",
    ),

    # ── 5. Compliance Checklist ───────────────────────────────────────────────
    AgentTestCase(
        id="AG-010",
        category="checklist",
        query="Lập danh sách các việc cần chuẩn bị (checklist) để tuân thủ EPR cho doanh nghiệp nhập khẩu ắc quy.",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=3,
        expected_answer_contains=["đăng ký", "kê khai", "ắc quy"],
        description="Lập checklist chuẩn bị hồ sơ tuân thủ EPR.",
    ),

    # ── 6. Fault Tolerance & Recovery ─────────────────────────────────────────
    AgentTestCase(
        id="AG-011",
        category="fault_tolerance",
        query="Quy định xử phạt vi phạm hành chính về không đóng tiền FSF?",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=4,
        mock_first_search_empty=True,
        description="Lần search đầu trả về rỗng, agent tự động điều chỉnh query và thử lại.",
    ),

    # ── 7. Budget Enforcement & Loop Prevention ───────────────────────────────
    AgentTestCase(
        id="AG-012",
        category="budget_enforcement",
        query="Câu hỏi phức tạp vượt quá khả năng tìm kiếm",
        expected_termination="insufficient_evidence",
        max_steps_allowed=5,
        mock_all_search_empty=True,
        description="Khi không tìm được dữ liệu sau tối đa 5 bước, agent dừng an toàn.",
    ),

    # ── 8. Cache Utilization ──────────────────────────────────────────────────
    AgentTestCase(
        id="AG-013",
        category="cache_hit",
        query="Điều 77 Luật BVMT quy định trách nhiệm tái chế như thế nào?",
        expected_termination="cache_hit",
        expected_tools=["lookup_answer_cache"],
        max_steps_allowed=2,
        description="Tra cứu câu hỏi đã có sẵn trong Redis cache.",
    ),

    # ── 9. Chitchat Fast Path ─────────────────────────────────────────────────
    AgentTestCase(
        id="AG-014",
        category="chitchat",
        query="Xin chào bạn, bạn có thể giúp tôi việc gì?",
        expected_termination="answer_complete",
        expected_tools=[],
        max_steps_allowed=1,
        expected_answer_contains=["Xin chào"],
        description="Chitchat bypass không gọi tool nào.",
    ),

    # ── 10. Out of Scope Fast Path ────────────────────────────────────────────
    AgentTestCase(
        id="AG-015",
        category="out_of_scope",
        query="Hướng dẫn cách nấu món bún bò Huế ngon chuẩn vị",
        expected_termination="out_of_scope",
        expected_tools=[],
        max_steps_allowed=1,
        expected_answer_contains=["ngoài phạm vi"],
        description="Câu hỏi ngoài phạm vi pháp luật được ngắt ngay lập tức.",
    ),

    # ── 11. Layman / Non-Expert User Inquiries ────────────────────────────────
    AgentTestCase(
        id="AG-016",
        category="layman_vague",
        query="EPR là gì vậy bạn? Giải thích dễ hiểu giúp tôi với",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=3,
        expected_answer_contains=["EPR", "tái chế", "[1]"],
        description="Người dùng không chuyên hỏi khái niệm cơ bản bằng ngôn ngữ đời thường.",
    ),
    AgentTestCase(
        id="AG-017",
        category="layman_misconception",
        query="Em mở tiệm trà sữa mua cốc nhựa về bán mang đi, em có bị bắt nộp phí EPR không?",
        expected_termination="answer_complete",
        expected_tools=["search_legal_provisions"],
        max_steps_allowed=3,
        expected_answer_contains=["không phải", "[1]"],
        description="Chủ quán bán lẻ hỏi về việc sử dụng bao bì (không thuộc diện nộp phí).",
    ),
    AgentTestCase(
        id="AG-018",
        category="layman_workshop",
        query="Xưởng tôi sản xuất túi ni-lông bán cho các chợ ở Việt Nam, doanh thu 12 tỷ/năm",
        expected_termination="answer_complete",
        expected_tools=["get_case_form_fields", "evaluate_epr_obligation", "search_legal_provisions"],
        max_steps_allowed=4,
        expected_answer_contains=["miễn trừ", "[1]"],
        mock_facts={
            "business_role": "manufacturer",
            "object_kind": "commercial_packaging",
            "product_group": "bao_bi",
            "packaged_goods_category": "thuc_pham",
            "material": "plastic",
            "market_placement": "vietnam_market",
            "annual_revenue_vnd": "12000000000",
            "reused_by_producer": "no",
        },
        description="Chủ xưởng nhỏ cung cấp thông tin đời thường, agent tự trích xuất và kết luận miễn trừ.",
    ),
]
