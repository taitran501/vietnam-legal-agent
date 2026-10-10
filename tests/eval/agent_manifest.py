"""Cross-domain evaluation cases for the autonomous legal agent."""

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
    AgentTestCase(
        id="AG-001", category="single_hop",
        query="Tiền lương làm thêm giờ vào ngày nghỉ hằng tuần được tính thế nào?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=3, expected_answer_contains=["căn cứ pháp luật"],
        description="Câu hỏi lao động ngắn bằng ngôn ngữ thường.",
    ),
    AgentTestCase(
        id="AG-002", category="single_hop",
        query="Chủ nhà có được tự ý giữ tiền đặt cọc sau khi tôi trả nhà không?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=3, expected_answer_contains=["căn cứ pháp luật"],
        description="Câu hỏi dân sự về thuê nhà và đặt cọc.",
    ),
    AgentTestCase(
        id="AG-003", category="single_hop",
        query="Vượt đèn đỏ khi đi xe máy có thể bị xử phạt thế nào?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=3, expected_answer_contains=["căn cứ pháp luật"],
        description="Câu hỏi giao thông thông dụng.",
    ),
    AgentTestCase(
        id="AG-004", category="multi_hop",
        query="Tôi bị cho nghỉ việc mà không được báo trước; tôi nên kiểm tra những quyền lợi nào?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=4, expected_answer_contains=["các căn cứ liên quan"],
        description="Tình huống lao động cần tra cứu nhiều khía cạnh.",
    ),
    AgentTestCase(
        id="AG-005", category="multi_hop",
        query="So sánh thủ tục ly hôn đơn phương và thuận tình ở mức khái quát.",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=4, expected_answer_contains=["các căn cứ liên quan"],
        description="Câu hỏi gia đình cần đối chiếu hai thủ tục.",
    ),
    AgentTestCase(
        id="AG-006", category="assessment_complete",
        query="Công ty thông báo chấm dứt hợp đồng lao động của tôi ngay hôm nay. Tôi đã làm việc ba năm; tôi cần xem xét những gì?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=4, expected_answer_contains=["căn cứ pháp luật"],
        mock_facts={"employment_years": "3", "notice_received": "no"},
        description="Phân tích tình huống lao động theo dữ kiện tự nhiên, không dùng biểu mẫu.",
    ),
    AgentTestCase(
        id="AG-007", category="assessment_exempt",
        query="Tôi thuê nhà đủ hạn và bàn giao nguyên trạng. Chủ nhà vẫn chưa trả cọc; tôi có thể làm gì?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=4, expected_answer_contains=["căn cứ pháp luật"],
        mock_facts={"lease_ended": "yes", "property_returned": "yes", "deposit_returned": "no"},
        description="Đánh giá tranh chấp dân sự từ những dữ kiện người dùng nêu.",
    ),
    AgentTestCase(
        id="AG-008", category="assessment_missing_facts",
        query="Công ty cho tôi nghỉ việc. Việc này có đúng luật không?",
        expected_termination="awaiting_user_input", expected_tools=["ask_user_for_clarification"],
        max_steps_allowed=2, expected_answer_contains=["hợp đồng"],
        description="Chỉ hỏi một dữ kiện thiết yếu bằng câu hỏi tự nhiên.",
    ),
    AgentTestCase(
        id="AG-009", category="assessment_missing_facts",
        query="Chủ nhà không trả tiền cọc cho tôi, tôi phải làm sao?",
        expected_termination="awaiting_user_input", expected_tools=["ask_user_for_clarification"],
        max_steps_allowed=2, expected_answer_contains=["thỏa thuận"],
        description="Làm rõ một dữ kiện có ý nghĩa thay vì mở form thu thập hàng loạt thông tin.",
    ),
    AgentTestCase(
        id="AG-010", category="checklist",
        query="Tôi muốn đăng ký thành lập công ty TNHH. Cần chuẩn bị những gì?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=3, expected_answer_contains=["căn cứ pháp luật"],
        description="Yêu cầu thủ tục doanh nghiệp.",
    ),
    AgentTestCase(
        id="AG-011", category="fault_tolerance",
        query="Tôi bị xử phạt vi phạm hành chính nhưng cho rằng quyết định sai. Tôi có thể khiếu nại không?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=4, mock_first_search_empty=True,
        description="Tra cứu phục hồi sau một lượt retrieval rỗng.",
    ),
    AgentTestCase(
        id="AG-012", category="budget_enforcement",
        query="Tra cứu quy định cho một sự việc nhưng kho hiện không có tài liệu liên quan.",
        expected_termination="insufficient_evidence", max_steps_allowed=5,
        mock_all_search_empty=True,
        description="Khi thiếu căn cứ sau giới hạn thử, giải thích đúng khoảng trống.",
    ),
    AgentTestCase(
        id="AG-013", category="cache_hit",
        query="Tiền làm thêm giờ vào ngày nghỉ hằng tuần được tính thế nào?",
        expected_termination="cache_hit", expected_tools=["lookup_answer_cache"],
        max_steps_allowed=2,
        description="Dùng lại câu trả lời đã lưu cùng căn cứ nguồn.",
    ),
    AgentTestCase(
        id="AG-014", category="chitchat",
        query="Xin chào, bạn có thể giúp tôi việc gì?",
        expected_termination="answer_complete", max_steps_allowed=1,
        expected_answer_contains=["Xin chào"], description="Chào hỏi không cần retrieval.",
    ),
    AgentTestCase(
        id="AG-015", category="out_of_scope",
        query="Hướng dẫn cách nấu món bún bò Huế ngon chuẩn vị",
        expected_termination="out_of_scope", max_steps_allowed=1,
        expected_answer_contains=["ngoài phạm vi"], description="Yêu cầu ngoài chủ đề pháp luật.",
    ),
    AgentTestCase(
        id="AG-016", category="layman_vague",
        query="Tiền cọc thuê nhà của tôi bị giữ lại là sao vậy?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=3, expected_answer_contains=["căn cứ pháp luật"],
        description="Hiểu câu hỏi ngắn, ít thuật ngữ pháp lý.",
    ),
    AgentTestCase(
        id="AG-017", category="layman_misconception",
        query="Sếp nói thử việc thì không cần trả lương, có đúng không?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=3, expected_answer_contains=["căn cứ pháp luật"],
        description="Kiểm tra nhận định phổ biến về quyền lao động.",
    ),
    AgentTestCase(
        id="AG-018", category="layman_workshop",
        query="Xe máy va chạm làm hỏng xe người khác. Tôi nên xử lý thế nào?",
        expected_termination="answer_complete", expected_tools=["search_legal_provisions"],
        max_steps_allowed=4, expected_answer_contains=["căn cứ pháp luật"],
        description="Tình huống dân sự, giao thông bằng lời kể đời thường.",
    ),
]
