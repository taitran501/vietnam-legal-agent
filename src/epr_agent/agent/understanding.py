"""Structured task understanding for the closed legal workflow.

The model may classify and extract explicit facts, but it cannot select a tool
or create a new task.  The graph recomputes required facts and the bounded
planner remains the only component that chooses transitions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from epr_agent.domain.routes import RouteType
from epr_agent.domain.tasks import TaskUnderstanding, deterministic_task_understanding, preserve_explicit_anchors

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Bạn là thành phần Phân tích & Hiểu yêu cầu (Task Understanding) của Trợ lý Pháp luật Việt Nam toàn diện, am hiểu sâu sắc mọi lĩnh vực pháp luật Việt Nam (Lao động, Đất đai, Dân sự, Hợp đồng, Doanh nghiệp, Hôn nhân gia đình, Giao thông, Thuế, Hình sự, Môi trường/EPR...).

Nhiệm vụ của bạn là tiếp nhận câu nói/yêu cầu của người dùng bằng tiếng Việt tự nhiên (bao gồm cả khẩu ngữ đời thường, tiếng lóng, cách viết tắt, không dấu, câu chào cộc lốc hay chia sẻ tình huống phức tạp), hiểu đúng bản chất ý định và trả về cấu trúc QueryPlan phù hợp.

════════════════════ NGUYÊN TẮC ĐỊNH TUYẾN (ROUTE CLASSIFICATION) ════════════════════
1. 'chitchat':
   - Các tương tác giao tiếp, chào hỏi, xưng hô, hỏi thăm đời thường, KHÔNG chứa câu hỏi pháp lý hay vụ việc tranh chấp.
   - Bao gồm: chào hỏi ("alo", "xin chào", "hi", "hey", "chào bạn"), hỏi danh tính/tư cách ("alo ai vay", "ai vậy", "ai đấy", "bạn là ai", "bạn tên gì", "bot hả"), hỏi năng lực hỗ trợ ("bạn làm được gì", "hướng dẫn tôi", "giúp gì được"), cảm ơn ("cảm ơn bạn", "thanks"), tạm biệt ("tạm biệt", "bye"), hoặc tán gẫu thông thường.

2. 'legal_lookup':
   - Tra cứu quy định pháp luật khách quan: định nghĩa, điều khoản, số hiệu luật/nghị định, mức phạt, thời hạn, điều kiện, quyền và nghĩa vụ theo quy định pháp luật hiện hành.
   - Ví dụ: "Thời gian thử việc tối đa của đại học là bao lâu?", "Mức phạt nồng độ cồn xe máy", "Điều 36 Bộ luật Lao động", "Quy định về thời hiệu khởi kiện tranh chấp hợp đồng".

3. 'legal_explain_compare':
   - Yêu cầu giải thích chi tiết, làm rõ hoặc so sánh sự khác nhau giữa các văn bản, chế định hoặc khái niệm pháp lý.
   - Ví dụ: "So sánh hợp đồng lao động xác định thời hạn và không xác định thời hạn", "Phân biệt tài sản chung và tài sản riêng vợ chồng", "Tóm tắt điểm mới của Luật Đất đai 2024".

4. 'case_assessment':
   - Người dùng mô tả tình huống, mâu thuẫn, tranh chấp hoặc hoàn cảnh cụ thể của bản thân, người thân hoặc doanh nghiệp và hỏi cách xử lý, xem có vi phạm không, quyền lợi được bảo vệ ra sao.
   - Ví dụ: "Tôi bị công ty đuổi việc bất ngờ không báo trước 30 ngày", "Chủ nhà tự ý tăng tiền trọ 30% có đúng luật không", "Ba mẹ tôi cho đất bằng giấy viết tay từ 1995 giờ có làm sổ đỏ được không", "Tôi va quẹt xe máy bị người ta giữ xe đòi 10 triệu".

5. 'compliance_checklist':
   - Yêu cầu cung cấp danh mục hồ sơ giấy tờ cần chuẩn bị, các bước thực hiện thủ tục hành chính/pháp lý tuần tự, lộ trình tuân thủ.
   - Ví dụ: "Thủ tục làm sổ đỏ lần đầu cần những giấy tờ gì?", "Hồ sơ đăng ký thành lập công ty TNHH", "Các bước xin cấp giấy phép xây dựng nhà ở".

6. 'research_web':
   - Khi người dùng chủ động yêu cầu tìm kiếm trên internet, tin tức báo chí mới nhất hoặc nguồn web công khai ngoài kho văn bản.
   - Ví dụ: "Tìm trên internet xem quy định mới nhất về biển số định danh", "Tra cứu trên mạng tin tức mới về bỏ sổ hộ khẩu giấy".

7. 'out_of_scope':
   - Các câu hỏi hoàn toàn không thuộc lĩnh vực pháp luật, quy định hay thủ tục hành chính Việt Nam (công thức nấu ăn, viết code lập trình, giải trí, kết quả bóng đá, crypto/tiền ảo, viết thơ...).

════════════════════ XỬ LÝ NGỮ CẢNH & VIẾT LẠI TRUY VẤN (STANDALONE QUERY) ════════════════════
- is_follow_up = True: Chỉ khi câu nói phụ thuộc vào ngữ cảnh trao đổi trước đó (ví dụ: "còn trường hợp đó thì sao?", "mức phạt thế nào?", "vậy tôi phải làm gì tiếp?").
- standalone_query:
  + Nếu là câu hỏi độc lập hoặc chitchat: Giữ nguyên câu nói của người dùng.
  + Nếu là câu follow-up: Viết lại thành một câu tiếng Việt độc lập, đầy đủ ngữ cảnh để làm truy vấn tra cứu.
- Trích xuất facts (business_role, product_or_packaging, material, activity_scope): Chỉ lấy thông tin người dùng nêu rõ ràng, không suy đoán."""



class TaskUnderstandingGateway(Protocol):
    async def understand(
        self,
        query: str,
        history: list[dict[str, Any]],
        summary: str,
        active_case: dict[str, Any] | None,
    ) -> TaskUnderstanding: ...


class StructuredTaskUnderstandingGateway:
    """Use OpenAI structured output, with a deterministic safe fallback."""

    async def understand(
        self,
        query: str,
        history: list[dict[str, Any]],
        summary: str,
        active_case: dict[str, Any] | None,
    ) -> TaskUnderstanding:
        try:
            from epr_agent.infra.llm_instances import get_llm_router

            model = get_llm_router().with_structured_output(TaskUnderstanding)
            payload = {
                "query": query,
                "recent_history": [
                    {"role": item.get("role", ""), "content": str(item.get("content", ""))[:800]}
                    for item in history[-6:]
                ],
                "conversation_summary": summary[:1200],
                "active_case": active_case or {},
            }
            result = await model.ainvoke(
                [
                    ("system", _SYSTEM_PROMPT),
                    ("human", "Hãy phân tích yêu cầu sau đây và trả về cấu trúc QueryPlan:\n" + json.dumps(payload, ensure_ascii=False)),
                ]
            )
            if not isinstance(result, TaskUnderstanding):
                result = TaskUnderstanding.model_validate(result)
            if not result.standalone_query or not result.standalone_query.strip():
                result.standalone_query = query
            result.standalone_query = preserve_explicit_anchors(query, result.standalone_query)
            if not result.research_requested:
                result.research_requested = (result.route == RouteType.RESEARCH_WEB)
            return result
        except Exception as exc:  # noqa: BLE001 - safe fallback is intentional
            logger.warning("Structured task understanding unavailable; using safe fallback: %s", exc)
            return deterministic_task_understanding(query, history, active_case)


class StaticTaskUnderstandingGateway:
    """Injected double for unit and trajectory tests."""

    def __init__(self, result: TaskUnderstanding) -> None:
        self.result = result
        self.calls = 0

    async def understand(
        self,
        query: str,
        history: list[dict[str, Any]],
        summary: str,
        active_case: dict[str, Any] | None,
    ) -> TaskUnderstanding:
        self.calls += 1
        return self.result
