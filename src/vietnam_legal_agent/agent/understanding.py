"""Structured task understanding for the closed legal workflow.

The model may classify and extract explicit facts, but it cannot select a tool
or create a new task.  The graph recomputes required facts and the bounded
planner remains the only component that chooses transitions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

from vietnam_legal_agent.domain.legal import explicit_anchors
from vietnam_legal_agent.domain.routes import RouteType
from vietnam_legal_agent.domain.tasks import (
    TaskUnderstanding,
    deterministic_task_understanding,
    is_general_factual_lookup_query,
    is_general_lookup_explanation_query,
    is_greeting,
    preserve_explicit_anchors,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Bạn là thành phần Phân tích & Hiểu yêu cầu của trợ lý pháp luật Việt Nam đa lĩnh vực, tiếp nhận câu hỏi thuộc các ngành luật khác nhau.

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
   - Chỉ chọn khi người dùng mô tả hoàn cảnh cụ thể của bản thân/người thân/doanh nghiệp và cần đánh giá, hoặc hỏi cách giải quyết một tranh chấp cụ thể. Tình huống giả định/ngôi thứ ba hỏi chung về quy tắc, quyền hoặc tiêu chí pháp lý vẫn là legal_lookup.
   - Ví dụ: "Tôi bị công ty đuổi việc bất ngờ không báo trước 30 ngày", "Chủ nhà tự ý tăng tiền trọ 30% có đúng luật không", "Ba mẹ tôi cho đất bằng giấy viết tay từ 1995 giờ có làm sổ đỏ được không", "Tôi va quẹt xe máy bị người ta giữ xe đòi 10 triệu".

5. 'compliance_checklist':
   - Yêu cầu cung cấp danh mục hồ sơ giấy tờ cần chuẩn bị, các bước thực hiện thủ tục hành chính/pháp lý tuần tự, lộ trình tuân thủ.
   - Ví dụ: "Thủ tục làm sổ đỏ lần đầu cần những giấy tờ gì?", "Hồ sơ đăng ký thành lập công ty TNHH", "Các bước xin cấp giấy phép xây dựng nhà ở".

6. 'research_web':
   - Khi người dùng chủ động yêu cầu tìm kiếm trên internet, tin tức báo chí mới nhất hoặc nguồn web công khai ngoài kho văn bản.
   - Ví dụ: "Tìm trên internet xem quy định mới nhất về biển số định danh", "Tra cứu trên mạng tin tức mới về bỏ sổ hộ khẩu giấy".

7. 'out_of_scope':
   - Các câu hỏi hoàn toàn không thuộc lĩnh vực pháp luật, quy định hay thủ tục hành chính Việt Nam (công thức nấu ăn, viết code lập trình, giải trí, kết quả bóng đá, crypto/tiền ảo, viết thơ...).

Trường 'route' quyết định luồng sản phẩm. Trường 'task_type' phải khớp với route: case_assessment -> case_assessment; compliance_checklist -> build_compliance_checklist; chitchat -> chitchat; các route tra cứu/giải thích/tìm nguồn/out_of_scope -> legal_lookup. Câu hỏi về nội dung một nghĩa vụ pháp luật nói chung là legal_lookup; chỉ chọn case_assessment khi người dùng yêu cầu đánh giá hoàn cảnh cụ thể của họ hoặc một tổ chức cụ thể.

════════════════════ XỬ LÝ NGỮ CẢNH & VIẾT LẠI TRUY VẤN (STANDALONE QUERY) ════════════════════
- is_follow_up = True: Chỉ khi câu nói phụ thuộc vào ngữ cảnh trao đổi trước đó (ví dụ: "còn trường hợp đó thì sao?", "mức phạt thế nào?", "vậy tôi phải làm gì tiếp?").
- standalone_query:
  + Nếu là câu hỏi độc lập hoặc chitchat: Giữ nguyên câu nói của người dùng.
  + Nếu là câu follow-up: Viết lại thành một câu tiếng Việt độc lập, đầy đủ ngữ cảnh để làm truy vấn tra cứu.
- retrieval_queries: Với mọi câu hỏi pháp lý cần tra cứu, tạo 1 truy vấn bổ sung ngắn; nếu câu hỏi bao quát nhiều căn cứ, có thể tạo thêm một truy vấn khác biệt để tăng recall. Chỉ để trống khi người dùng đã nêu chính xác điều/văn bản cần tra hoặc không thuộc route tra cứu. Truy vấn phải nhắm cùng chủ thể, giai đoạn pháp lý, quyền/nghĩa vụ và kết quả người dùng hỏi, nhưng dùng khái niệm pháp lý chính thức thay cho cách nói đời thường. Nếu người dùng hỏi tiêu chí quyết định, nêu tiêu chuẩn pháp lý cụ thể có khả năng xuất hiện trong điều luật thay vì chỉ viết chung chung "căn cứ pháp lý" hoặc "tiêu chí". Nếu dùng từ khẩu ngữ, chuyển sang thuật ngữ pháp lý tương ứng. Đây là cụm từ tìm kiếm, không phải câu trả lời cho người dùng; không thêm số hiệu điều/văn bản, dữ kiện, hoặc khẳng định pháp lý. Không mở rộng sang nghĩa vụ của chủ thể khác hay quy định kề cận.
  + Chỉ đổi cách diễn đạt để tăng khả năng tìm đúng quy tắc; không tự thêm số hiệu văn bản, điều khoản, mốc thời gian, dữ kiện hoặc kết luận pháp lý. Không nêu văn bản hay khái niệm cụ thể nếu câu hỏi và ngữ cảnh không hỗ trợ.
  + Giữ nguyên mọi văn bản, điều, khoản, điểm và phụ lục mà người dùng đã nêu.
  + Để trống với chitchat hoặc câu hỏi ngoài phạm vi pháp luật.
- Trích xuất facts bằng các khóa ngắn gọn phù hợp với chính tình huống hiện tại; chỉ ghi nhận dữ kiện người dùng nói rõ, không áp một bộ trường cố định cho mọi lĩnh vực và không suy đoán."""


class _LegalRetrievalQueries(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=2)


_RETRIEVAL_QUERY_PROMPT = """Bạn tạo tối đa hai truy vấn nội bộ ngắn, bổ trợ nhau, để tìm đúng điều khoản pháp luật Việt Nam cho câu hỏi.

Viết một cụm truy vấn ngắn, khác cách nói của người dùng nhưng giữ đúng vấn đề pháp lý, chủ thể, giai đoạn và kết quả họ hỏi. Xác định chế định pháp lý và vai trò theo ý nghĩa của tình huống; không giữ nguyên nhãn khẩu ngữ như "người mua" nếu thuật ngữ pháp luật phù hợp hơn. Ưu tiên thuật ngữ của quyền/nghĩa vụ được hỏi và sự kiện làm phát sinh chúng. Chuyển chi tiết bối cảnh sang khái niệm pháp lý tương ứng khi nó làm thay đổi quy định áp dụng, tránh để cách diễn đạt đời thường kéo truy vấn sang chế định lân cận.

Ví dụ chuyển đổi:
- "mua hàng online nhận sản phẩm lỗi, người mua có quyền gì" -> "quyền của người tiêu dùng khi nhận hàng hóa có khuyết tật trong giao dịch từ xa".
- "bị cho nghỉ việc không báo trước" -> "đơn phương chấm dứt hợp đồng lao động, nghĩa vụ báo trước và quyền của người lao động".
- "ba mẹ ly hôn thì con ở với ai" -> "giao con cho một bên trực tiếp nuôi khi cha mẹ ly hôn, quyền lợi mọi mặt của con".
- "Luật bảo vệ quyền lợi người tiêu dùng quy định những quyền cơ bản nào" -> ["quyền của người tiêu dùng trong giao dịch hàng hóa và dịch vụ", "người tiêu dùng quyền an toàn sức khỏe thông tin lựa chọn"].

Nếu câu hỏi hẹp, chỉ trả về một truy vấn. Nếu câu hỏi bao quát nhiều quyền/nghĩa vụ hoặc nhiều căn cứ có thể áp dụng, có thể trả về hai cụm tìm kiếm ngắn khác nhau về từ khóa nhưng cùng nhắm một câu hỏi; một cụm nên dùng tên chế định/tiêu đề pháp lý, cụm kia dùng các khái niệm nội dung phân biệt. Không lặp lại cùng truy vấn bằng cách đổi vài từ.

Với câu hỏi liệt kê một nhóm quyền/nghĩa vụ, không chỉ lặp lại cụm "quyền cơ bản" hoặc tên luật. Hãy thêm các khái niệm nội dung đặc trưng thường xuất hiện trong chính quy định được hỏi (ví dụ an toàn, thông tin, lựa chọn đối với quyền người tiêu dùng). Không chèn mọi từ khóa liên quan nếu chúng dẫn sang một luật khác.

Nếu câu hỏi có ngưỡng số hoặc tỷ lệ sở hữu, giữ nguyên con số, chủ thể, mẫu số và điều kiện đạt ngưỡng trong truy vấn. Ưu tiên cách diễn đạt pháp lý cho nhóm đủ điều kiện đó; không làm rơi ngưỡng để trả về quyền chung của một loại tài sản hoặc nhóm chủ thể lân cận. Không tự đổi một loại cổ phần hoặc tư cách chủ thể nếu câu hỏi chưa xác định.
Ví dụ: "cổ đông sở hữu 5% cổ phần có những quyền gì" -> "quyền của cổ đông hoặc nhóm cổ đông sở hữu từ 5% tổng số cổ phần phổ thông trở lên; quyền của cổ đông phổ thông". Đây là cách giữ nguyên ngưỡng để tìm đúng điều kiện áp dụng, không phải kết luận rằng người hỏi đang sở hữu cổ phần phổ thông.

Không suy ra quyền cụ thể chỉ từ phép chuyển thuật ngữ. Nếu chủ thể hoặc tính chất giao dịch còn mơ hồ, chọn thuật ngữ bao quát và giữ lại chi tiết được nêu; không khẳng định thêm dữ kiện. Nếu người dùng hỏi căn cứ quyết định, tìm chính tiêu chí/chuẩn pháp lý quyết định. Đây chỉ là từ khóa tìm nguồn, không phải câu trả lời.

Không trả lời câu hỏi, không tự đặt điều luật/số hiệu văn bản, không đổi sang quyền/nghĩa vụ của chủ thể khác hoặc vấn đề pháp lý gần kề. Trả về đúng một hoặc hai truy vấn theo schema."""



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
        if is_greeting(query):
            return deterministic_task_understanding(query, history, active_case)
        try:
            from vietnam_legal_agent.infra.llm_instances import get_llm_router

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

            # Keep the model-generated search reformulations while pinning
            # straightforward legal lookups to the deterministic route. This
            # lets retrieval benefit from semantic variation without letting
            # a model turn an ordinary question into case advice/checklist.
            if not active_case:
                deterministic = deterministic_task_understanding(query, history, active_case)
                deterministic_general = (
                    deterministic.route is not RouteType.CASE_ASSESSMENT
                    and deterministic.route is not RouteType.COMPLIANCE_CHECKLIST
                )
                should_correct_case_route = (
                    result.route is RouteType.CASE_ASSESSMENT and deterministic_general
                )
                if (
                    is_general_lookup_explanation_query(query)
                    or is_general_factual_lookup_query(query)
                    or should_correct_case_route
                ):
                    # A generic third-person hypothetical is not a personal
                    # case just because the planner inferred one. Retain the
                    # model route when the deterministic reading also sees a
                    # concrete personal dispute or checklist request.
                    result.task_type = deterministic.task_type
                    result.route = deterministic.route
                    result.is_follow_up = deterministic.is_follow_up
                    result.standalone_query = preserve_explicit_anchors(
                        query,
                        deterministic.standalone_query or query,
                    )
                    result.explicit_anchors = deterministic.explicit_anchors
                    result.legal_topics = deterministic.legal_topics
                    result.research_requested = deterministic.research_requested
                    result.facts = deterministic.facts
                    result.missing_facts = deterministic.missing_facts
                    result.confidence = deterministic.confidence

            if not result.research_requested:
                result.research_requested = (result.route == RouteType.RESEARCH_WEB)
            if (
                result.route in {RouteType.LEGAL_LOOKUP, RouteType.LEGAL_EXPLAIN_COMPARE}
                and not explicit_anchors(result.standalone_query or query)
            ):
                try:
                    # Route understanding and search-term generation are
                    # separate jobs. Replace a broad planner paraphrase with
                    # one query aimed at formal legal terminology.
                    rewrite_model = get_llm_router().with_structured_output(_LegalRetrievalQueries)
                    rewrite = await rewrite_model.ainvoke(
                        [
                            ("system", _RETRIEVAL_QUERY_PROMPT),
                            (
                                "human",
                                json.dumps(
                                    {"user_query": query, "standalone_query": result.standalone_query or query},
                                    ensure_ascii=False,
                                ),
                            ),
                        ]
                    )
                    if not isinstance(rewrite, _LegalRetrievalQueries):
                        rewrite = _LegalRetrievalQueries.model_validate(rewrite)
                    rewritten_queries = []
                    seen_rewrites = {(result.standalone_query or query).casefold()}
                    for candidate in rewrite.queries:
                        rewritten_query = " ".join(candidate.split())[:3000]
                        key = rewritten_query.casefold()
                        if rewritten_query and key not in seen_rewrites:
                            seen_rewrites.add(key)
                            rewritten_queries.append(rewritten_query)
                    if rewritten_queries:
                        result.retrieval_queries = rewritten_queries
                except Exception as exc:  # noqa: BLE001 - original query remains the retrieval fallback
                    logger.info("Legal retrieval query rewrite unavailable: %s", type(exc).__name__)
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
